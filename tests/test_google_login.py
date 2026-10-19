import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from app import create_app
from extensions import db
from models import User


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False
    TRIAL_DAYS = 14
    GOOGLE_CLIENT_ID = "cid.apps.googleusercontent.com"
    GOOGLE_CLIENT_SECRET = "test-secret"


def _resp(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


class GoogleLoginTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _start(self):
        resp = self.client.get("/giris/google")
        self.assertEqual(resp.status_code, 302)
        url = urlparse(resp.headers["Location"])
        self.assertEqual(url.netloc, "accounts.google.com")
        q = parse_qs(url.query)
        self.assertEqual(q["client_id"][0], TestConfig.GOOGLE_CLIENT_ID)
        self.assertIn("/giris/google/donus", q["redirect_uri"][0])
        return q["state"][0]

    def _callback(self, state, profile):
        with patch("routes.auth.requests.post", return_value=_resp({"access_token": "at"})), \
             patch("routes.auth.requests.get", return_value=_resp(profile)):
            return self.client.get(f"/giris/google/donus?state={state}&code=abc")

    def test_buttons_shown(self):
        for path in ("/giris", "/kayit"):
            self.assertIn("Google ile devam et", self.client.get(path).get_data(as_text=True))
        self.assertIn("Giriş yap", self.client.get("/").get_data(as_text=True))

    def test_new_user_created_with_trial(self):
        state = self._start()
        resp = self._callback(state, {"sub": "g-1", "email": "Yeni@Restoran.com", "email_verified": True, "name": "Ali Usta"})
        self.assertEqual(resp.status_code, 302)
        user = User.query.filter_by(email="yeni@restoran.com").first()
        self.assertIsNotNone(user)
        self.assertEqual(user.google_sub, "g-1")
        self.assertTrue(user.is_trial)
        self.assertIsNotNone(user.email_verified_at)
        self.assertEqual(self.client.get("/panel/").status_code, 200)

    def test_existing_email_user_is_linked(self):
        u = User(name="Eski", email="eski@restoran.com")
        u.set_password("sifre12345")
        db.session.add(u)
        db.session.commit()
        state = self._start()
        self._callback(state, {"sub": "g-2", "email": "eski@restoran.com", "email_verified": True})
        db.session.expire_all()
        self.assertEqual(User.query.count(), 1)
        self.assertEqual(User.query.first().google_sub, "g-2")
        self.assertTrue(User.query.first().check_password("sifre12345"))

    def test_bad_state_and_unverified_email_rejected(self):
        self._start()
        resp = self._callback("yanlis", {"sub": "g-3", "email": "x@y.com", "email_verified": True})
        self.assertIn("/giris", resp.headers["Location"])
        state = self._start()
        self._callback(state, {"sub": "g-4", "email": "z@y.com", "email_verified": False})
        self.assertEqual(User.query.count(), 0)

    def test_disabled_without_config(self):
        self.app.config["GOOGLE_CLIENT_ID"] = ""
        self.assertNotIn("Google ile devam et", self.client.get("/giris").get_data(as_text=True))
        self.assertIn("/giris", self.client.get("/giris/google").headers["Location"])


if __name__ == "__main__":
    unittest.main()

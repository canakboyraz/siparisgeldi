import re
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app import create_app
from extensions import db
from models import Integration, User


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False
    TRIAL_DAYS = 14
    SMTP_HOST = "smtp.example.invalid"
    SMTP_FROM = "SiparisGeldi <destek@example.invalid>"
    ENCRYPTION_KEY = "ZfzQ9FdJ80pGo55_U2X3dy_tZbW_Fi_66XjjFLGO9Bo="
    PLAN_LIMIT_SCOPE = "trial"
    TELEGRAM_BOT_TOKEN = ""


class AuthBase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def csrf(self, path="/kayit"):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="_csrf_token" value="([^"]+)"', html).group(1)

    def register(self, email="yeni@example.invalid", password="guclusifre1", accept=True):
        data = {"_csrf_token": self.csrf(), "name": "Lezzet", "email": email,
                "password": password, "confirm_password": password}
        if accept:
            data["accept_terms"] = "1"
        return self.client.post("/kayit", data=data)


class RegisterTrialTest(AuthBase):
    @patch("notifications.email.send_email", return_value=True)
    def test_register_starts_trial_and_sends_verification(self, send):
        resp = self.register()
        self.assertEqual(resp.status_code, 302)
        user = User.query.filter_by(email="yeni@example.invalid").one()
        self.assertTrue(user.is_trial)
        self.assertTrue(user.is_pro_active)
        self.assertTrue(user.has_multi_platform_access)
        self.assertAlmostEqual((user.pro_expires_at - datetime.utcnow()).days, 13, delta=1)
        self.assertFalse(user.feature_multi_platform)
        self.assertIn("/eposta-dogrula/", send.call_args.args[2])

    @patch("notifications.email.send_email", return_value=True)
    def test_short_password_and_missing_consent_rejected(self, _send):
        self.register(password="kisa123")
        self.assertIsNone(User.query.filter_by(email="yeni@example.invalid").first())
        self.register(accept=False)
        self.assertIsNone(User.query.filter_by(email="yeni@example.invalid").first())

    @patch("notifications.email.send_email", return_value=True)
    def test_verification_link_marks_email_verified(self, send):
        self.register()
        text_body = send.call_args.args[2]
        path = re.search(r"https?://[^/]+(/eposta-dogrula/\S+)", text_body).group(1)
        self.client.get(path)
        user = User.query.filter_by(email="yeni@example.invalid").one()
        self.assertIsNotNone(user.email_verified_at)


class PasswordResetTest(AuthBase):
    def setUp(self):
        super().setUp()
        user = User(email="sahip@example.invalid", name="Sahip")
        user.set_password("eskisifre1")
        db.session.add(user)
        db.session.commit()

    @patch("notifications.email.send_email", return_value=True)
    def test_reset_flow_changes_password_once(self, send):
        token = self.csrf("/sifremi-unuttum")
        self.client.post("/sifremi-unuttum", data={"_csrf_token": token, "email": "sahip@example.invalid"})
        path = re.search(r"https?://[^/]+(/sifre-sifirla/\S+)", send.call_args.args[2]).group(1)

        token = self.csrf(path)
        self.client.post(path, data={"_csrf_token": token, "password": "yenisifre99",
                                     "confirm_password": "yenisifre99"})
        user = User.query.filter_by(email="sahip@example.invalid").one()
        self.assertTrue(user.check_password("yenisifre99"))
        self.assertIsNotNone(user.email_verified_at)

        # Aynı bağlantı ikinci kez kullanılamaz (şifre hash'i değişti).
        resp = self.client.get(path)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/sifremi-unuttum", resp.headers["Location"])

    @patch("notifications.email.send_email", return_value=True)
    def test_unknown_email_gets_same_response_without_mail(self, send):
        token = self.csrf("/sifremi-unuttum")
        resp = self.client.post("/sifremi-unuttum", data={"_csrf_token": token, "email": "yok@example.invalid"})
        self.assertEqual(resp.status_code, 302)
        send.assert_not_called()


class PlanLimitTest(AuthBase):
    def _user_with_two_platforms(self, is_trial=True):
        user = User(email=f"u{is_trial}@example.invalid", name="U", plan="pro", is_trial=is_trial,
                    pro_started_at=datetime.utcnow() - timedelta(days=15),
                    pro_expires_at=datetime.utcnow() - timedelta(days=1))
        user.set_password("x" * 10)
        db.session.add(user)
        db.session.commit()
        first = Integration(user_id=user.id, platform="trendyolgo", is_active=True,
                            created_at=datetime.utcnow() - timedelta(days=10))
        second = Integration(user_id=user.id, platform="migros", is_active=True,
                             created_at=datetime.utcnow() - timedelta(days=5))
        db.session.add_all([first, second])
        db.session.commit()
        return user, first, second

    @patch("notifications.dispatcher.send_to_user", return_value=True)
    def test_expired_trial_keeps_only_oldest_platform(self, _notify):
        import monitoring
        user, first, second = self._user_with_two_platforms(is_trial=True)
        monitoring.enforce_plan_limits(self.app)
        self.assertTrue(db.session.get(Integration, first.id).is_active)
        self.assertFalse(db.session.get(Integration, second.id).is_active)

    @patch("notifications.dispatcher.send_to_user", return_value=True)
    def test_paid_expired_untouched_in_trial_scope(self, _notify):
        import monitoring
        user, first, second = self._user_with_two_platforms(is_trial=False)
        monitoring.enforce_plan_limits(self.app)
        self.assertTrue(db.session.get(Integration, second.id).is_active)


class MonitoringTest(AuthBase):
    def test_stale_integration_detected(self):
        import monitoring
        user = User(email="m@example.invalid", name="M")
        user.set_password("x" * 10)
        db.session.add(user)
        db.session.commit()
        intg = Integration(user_id=user.id, platform="trendyolgo", is_active=True, tgo_supplier_id="1",
                           last_sync_at=datetime.utcnow() - timedelta(minutes=30))
        intg.tgo_api_key = "k"
        fresh = Integration(user_id=user.id, platform="hepsiburada", is_active=True,
                            hb_merchant_id="m", hb_username="u",
                            last_sync_at=datetime.utcnow())
        fresh.hb_service_key = "s"
        db.session.add_all([intg, fresh])
        db.session.commit()
        stale = monitoring.find_stale_integrations()
        self.assertEqual([i.id for i in stale], [intg.id])

    def test_healthz_reports_worker_state(self):
        import monitoring
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.get_json()["worker"], "stale")
        monitoring.heartbeat(self.app)
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)

    def test_parallel_runner_processes_every_integration(self):
        import worker
        user = User(email="p@example.invalid", name="P")
        user.set_password("x" * 10)
        db.session.add(user)
        db.session.commit()
        ids = []
        for platform in ("trendyolgo", "trendyolgo_market", "hepsiburada"):
            intg = Integration(user_id=user.id, platform=platform, is_active=True)
            db.session.add(intg)
            db.session.commit()
            ids.append(intg.id)
        seen = []

        def handler(intg):
            seen.append(intg.id)
            if intg.platform == "hepsiburada":
                raise RuntimeError("api down")

        worker._run_integrations(self.app, ids, handler, "TEST")
        db.session.expire_all()
        self.assertEqual(sorted(seen), sorted(ids))
        self.assertEqual(db.session.get(Integration, ids[2]).last_error, "api down")
        self.assertIsNotNone(db.session.get(Integration, ids[0]).last_sync_at)


class PagesRenderTest(AuthBase):
    @patch("notifications.email.send_email", return_value=True)
    def test_public_and_dashboard_pages_render(self, _send):
        for path in ("/", "/giris", "/kayit", "/sifremi-unuttum", "/kar-hesaplayici"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.register()
        for path in ("/panel/", "/panel/abonelik", "/panel/profil"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, path)
        html = self.client.get("/panel/").get_data(as_text=True)
        self.assertIn("Kurulumu tamamla", html)
        self.assertIn("Pro deneme", html)


if __name__ == "__main__":
    unittest.main()


class ResendApiTest(unittest.TestCase):
    def test_resend_host_uses_https_api(self):
        class C(TestConfig):
            SMTP_HOST = "smtp.resend.com"
            SMTP_USER = "resend"
            SMTP_PASSWORD = "re_test_key"
            SMTP_FROM = "SiparişGeldi <destek@siparisgeldi.net>"
        app = create_app(C, start_scheduler=False)
        with app.app_context():
            from notifications import email as mailer
            with patch("notifications.email.requests.post") as post, patch("smtplib.SMTP") as smtp:
                post.return_value.status_code = 200
                self.assertTrue(mailer.send_email("a@example.invalid", "Konu", "metin"))
                smtp.assert_not_called()
                args, kwargs = post.call_args
                self.assertEqual(args[0], "https://api.resend.com/emails")
                self.assertEqual(kwargs["headers"]["Authorization"], "Bearer re_test_key")
                self.assertEqual(kwargs["json"]["to"], ["a@example.invalid"])
                self.assertIn("destek@siparisgeldi.net", kwargs["json"]["from"])
            db.drop_all()

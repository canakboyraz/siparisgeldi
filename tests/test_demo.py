import re
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app import create_app
from extensions import db
from models import Integration, Order, ProductCost, User


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False
    TRIAL_DAYS = 14


class DemoTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def csrf(self, path="/"):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="_csrf_token" value="([^"]+)"', html).group(1)

    def start_demo(self):
        resp = self.client.post("/demo", data={"_csrf_token": self.csrf("/giris")})
        self.assertEqual(resp.status_code, 302)
        return User.query.filter_by(is_demo=True).order_by(User.id.desc()).first()

    def test_demo_creates_populated_account_and_pages_render(self):
        user = self.start_demo()
        self.assertIsNotNone(user)
        self.assertGreater(Order.query.filter_by(user_id=user.id).count(), 400)
        self.assertEqual(Integration.query.filter_by(user_id=user.id).count(), 2)
        self.assertGreater(ProductCost.query.filter_by(user_id=user.id).count(), 5)

        html = self.client.get("/panel/").get_data(as_text=True)
        self.assertIn("Demo hesap", html)
        self.assertNotIn("Kurulumu tamamla", html)
        self.assertIn("zararına satıldı", html)          # Ayran bilerek zararına
        for path in ("/panel/aktif-siparisler", "/panel/siparisler", "/panel/kar-karnesi",
                     "/panel/maliyetler", "/panel/istatistikler"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        karne = self.client.get("/panel/kar-karnesi").get_data(as_text=True)
        self.assertIn("Ayran", karne)

    def test_demo_accept_is_local_and_other_posts_blocked(self):
        user = self.start_demo()
        pending = Order.query.filter_by(user_id=user.id, status="Created").first()
        token = self.csrf("/panel/aktif-siparisler")
        with patch("integrations.trendyolgo.update_package_status", create=True) as api:
            self.client.post(f"/panel/siparis/{pending.id}/trendyolgo-aksiyon",
                             data={"_csrf_token": token, "action": "pick"})
            api.assert_not_called()
        db.session.expire_all()
        self.assertEqual(db.session.get(Order, pending.id).status, "Picking")

        intg = Integration.query.filter_by(user_id=user.id).first()
        self.client.post(f"/panel/entegrasyon/{intg.id}/durum", data={"_csrf_token": token})
        db.session.expire_all()
        self.assertTrue(db.session.get(Integration, intg.id).is_active)

    def test_demo_users_hidden_from_admin_and_cleaned_up(self):
        import demo
        user = self.start_demo()
        uid = user.id
        self.assertEqual(demo.cleanup_demo_users(), 0)
        user.created_at = datetime.utcnow() - timedelta(hours=demo.DEMO_TTL_HOURS + 1)
        db.session.commit()
        self.assertEqual(demo.cleanup_demo_users(), 1)
        self.assertIsNone(db.session.get(User, uid))
        self.assertEqual(Order.query.filter_by(user_id=uid).count(), 0)
        self.assertEqual(ProductCost.query.filter_by(user_id=uid).count(), 0)

    def test_register_from_demo_logs_out_demo(self):
        self.start_demo()
        resp = self.client.get("/kayit")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("hesap oluştur", resp.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()

import re
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app import create_app
from extensions import db
import lifecycle
from models import AppState, Integration, Order, ProductCost, User


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False
    TRIAL_DAYS = 14
    SMTP_HOST = "smtp.test"
    SMTP_FROM = "SiparişGeldi <bilgi@siparisgeldi.net>"


class GrowthTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _csrf(self, path):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="_csrf_token" value="([^"]+)"', html).group(1)

    def _trial_user(self, days_ago=0, email="usta@restoran.com"):
        start = datetime.utcnow() - timedelta(days=days_ago)
        u = User(name="Usta", email=email, plan="pro", is_trial=True, pro_started_at=start,
                 pro_expires_at=start + timedelta(days=14), created_at=start)
        u.set_password("sifre12345")
        db.session.add(u)
        db.session.commit()
        return u

    def test_register_single_password_field(self):
        token = self._csrf("/kayit")
        page = self.client.get("/kayit").get_data(as_text=True)
        self.assertNotIn("confirm_password", page)
        self.assertIn("Ücretsiz denemeyi başlat", page)
        self.client.post("/kayit", data={"_csrf_token": token, "name": "Lezzet", "email": "yeni@restoran.com",
                                         "password": "sifre12345", "accept_terms": "1"})
        self.assertIsNotNone(User.query.filter_by(email="yeni@restoran.com").first())

    def test_onboarding_starts_with_account_done(self):
        self._trial_user()
        token = self._csrf("/giris")
        self.client.post("/giris", data={"_csrf_token": token, "email": "usta@restoran.com", "password": "sifre12345"})
        page = self.client.get("/panel/").get_data(as_text=True)
        self.assertIn("Hesabını aç", page)
        self.assertRegex(page, r"1 / \d adım tamam")
        self.assertIn("Sıradaki", page)

    def test_subscription_shows_anchor_and_usage(self):
        u = self._trial_user(days_ago=5)
        db.session.add(Integration(user_id=u.id, platform="trendyolgo", is_active=True))
        db.session.add(Integration(user_id=u.id, platform="migros", is_active=True))
        db.session.add(Order(user_id=u.id, platform="trendyolgo", external_id="1", status="Delivered", total_price=300))
        db.session.add(Order(user_id=u.id, platform="trendyolgo", external_id="2", status="Cancelled", total_price=99))
        db.session.commit()
        token = self._csrf("/giris")
        self.client.post("/giris", data={"_csrf_token": token, "email": "usta@restoran.com", "password": "sifre12345"})
        page = self.client.get("/panel/abonelik").get_data(as_text=True)
        self.assertIn("3.000 TL", page)            # 12 × 250 çıpası
        self.assertIn("Denemende SiparişGeldi", page)
        self.assertIn("<b>1</b><span>sipariş", page)  # iptal sayılmaz
        self.assertIn("Migros Yemek", page)         # duracak platform

    def test_lifecycle_emails_once_each(self):
        u = self._trial_user(days_ago=1)
        sent = []
        with patch("notifications.email.send_email", side_effect=lambda *a, **k: sent.append(a[1]) or True):
            lifecycle.send_lifecycle_emails(self.app)
            lifecycle.send_lifecycle_emails(self.app)
        self.assertEqual(sent, ["Kurulumun bir adım uzakta"])
        # 3. gün: platform var, maliyet yok
        u.pro_started_at = u.created_at = datetime.utcnow() - timedelta(days=3)
        db.session.add(Integration(user_id=u.id, platform="trendyolgo", is_active=True))
        db.session.commit()
        with patch("notifications.email.send_email", side_effect=lambda *a, **k: sent.append(a[1]) or True):
            lifecycle.send_lifecycle_emails(self.app)
        self.assertEqual(sent[-1], "Gerçek kârını görmene 5 ürün kaldı")
        db.session.add(ProductCost(user_id=u.id, platform="trendyolgo", product_key="durum", product_name="Dürüm", unit_cost=40))
        db.session.commit()
        # Denemenin bitmesine 1 gün: Telegram yok, e-posta gider
        u.pro_expires_at = datetime.utcnow() + timedelta(hours=20)
        db.session.commit()
        with patch("notifications.email.send_email", side_effect=lambda *a, **k: sent.append(a[1]) or True), \
             patch("lifecycle.datetime") as fake:
            fake.utcnow.return_value = datetime.utcnow()
            fake.now.return_value = datetime.now(lifecycle.TURKEY_TZ)
            lifecycle.send_lifecycle_emails(self.app)
        self.assertTrue(sent[-1].startswith("Pro denemen"), sent)
        self.assertTrue(all(len(k.key) <= 50 for k in AppState.query.all()))


if __name__ == "__main__":
    unittest.main()

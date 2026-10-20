import re
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app import create_app
from extensions import db
from integrations import paytr
from models import Payment, User


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False
    TRIAL_DAYS = 0
    PAYTR_MERCHANT_ID = "1"
    PAYTR_MERCHANT_KEY = "key"
    PAYTR_MERCHANT_SALT = "salt"


class YearlyPlanTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()
        u = User(name="Usta", email="usta@restoran.com")
        u.set_password("sifre12345")
        db.session.add(u)
        db.session.commit()
        self.uid = u.id
        token = self._csrf("/giris")
        self.client.post("/giris", data={"_csrf_token": token, "email": "usta@restoran.com", "password": "sifre12345"})

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _csrf(self, path):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="_csrf_token" value="([^"]+)"', html).group(1)

    def _pay(self, period):
        token = self._csrf("/panel/abonelik")
        with patch("routes.paytr.paytr.iframe_token", return_value="tok") as it:
            resp = self.client.post("/payment/paytr/start", data={"_csrf_token": token, "period": period})
        self.assertEqual(resp.status_code, 200)
        payment = Payment.query.order_by(Payment.id.desc()).first()
        kurus = str(int(round(payment.amount * 100)))
        sig = paytr._hmac(payment.merchant_oid + "salt" + "success" + kurus, "key")
        r = self.client.post("/payment/paytr/callback", data={"merchant_oid": payment.merchant_oid, "status": "success",
                                                      "total_amount": kurus, "hash": sig})
        self.assertEqual(r.get_data(as_text=True), "OK")
        db.session.expire_all()
        return payment, it

    def test_subscription_page_offers_both(self):
        html = self.client.get("/panel/abonelik").get_data(as_text=True)
        self.assertIn('value="yearly"', html)
        self.assertIn("2.500 TL", html)
        self.assertIn("2 ay bedava", html)

    def test_yearly_payment_gives_365_days(self):
        payment, it = self._pay("yearly")
        self.assertEqual(payment.amount, 2500.0)
        self.assertEqual(payment.period, "yearly")
        self.assertIn("Yillik", it.call_args.kwargs["item_name"])
        user = db.session.get(User, self.uid)
        self.assertGreater(user.pro_expires_at, datetime.utcnow() + timedelta(days=364))
        self.assertIn("Pro · Yıllık", self.client.get("/panel/abonelik").get_data(as_text=True))

    def test_monthly_payment_and_unknown_period(self):
        payment, _ = self._pay("bogus")
        self.assertEqual(payment.period, "monthly")
        self.assertEqual(payment.amount, 250.0)
        user = db.session.get(User, self.uid)
        self.assertLess(user.pro_expires_at, datetime.utcnow() + timedelta(days=31))

    def test_legal_pages_show_yearly_and_no_auto_renewal(self):
        refund = self.client.get("/iptal-iade-politikasi").get_data(as_text=True)
        self.assertIn("Kalan Aylara Göre İade", refund)
        self.assertIn("1.458 TL", refund)
        for path in ("/mesafeli-satis-sozlesmesi", "/on-bilgilendirme-formu"):
            html = self.client.get(path).get_data(as_text=True)
            self.assertIn("2.500 TL", html)
            self.assertNotIn("her ay yenilenir", html)


if __name__ == "__main__":
    unittest.main()

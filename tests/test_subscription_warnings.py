import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app import create_app
from extensions import db
from models import User
from worker import send_subscription_expiry_warnings


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False


class SubscriptionWarningTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.context = self.app.app_context()
        self.context.push()
        self.user = User(
            email="subscription@example.invalid",
            name="Subscription Test",
            password_hash="unused",
            plan="pro",
            pro_expires_at=datetime.utcnow() + timedelta(days=5),
            whatsapp_number="05000000000",
            notification_channel="whatsapp",
        )
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def test_warning_is_sent_once_per_day(self):
        with patch("worker.send_to_user", return_value=True) as send:
            send_subscription_expiry_warnings(self.app)
            send_subscription_expiry_warnings(self.app)

        self.assertEqual(send.call_count, 1)
        self.assertIsNotNone(self.user.pro_expiry_notice_sent_on)
        self.assertEqual(send.call_args.kwargs["wa_template"], "abonelik_uyarisi")
        self.assertEqual(len(send.call_args.kwargs["wa"]), 3)

    def test_warning_is_not_sent_before_threshold(self):
        self.user.pro_expires_at = datetime.utcnow() + timedelta(days=8)
        db.session.commit()

        with patch("worker.send_to_user", return_value=True) as send:
            send_subscription_expiry_warnings(self.app)

        send.assert_not_called()
        self.assertIsNone(self.user.pro_expiry_notice_sent_on)


if __name__ == "__main__":
    unittest.main()

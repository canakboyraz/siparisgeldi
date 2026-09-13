import json
import unittest
from datetime import datetime
from unittest.mock import patch

from app import create_app
from extensions import db
from integrations import trendyol_marketplace as tmp
from models import Integration, Order, User
from worker import _is_refunded_order, _send_period_report


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False


class TrendyolMarketplaceReportTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        user = User(email="trendyol-report@example.invalid", name="Report Test", password_hash="unused")
        db.session.add(user)
        db.session.flush()
        self.integration = Integration(user_id=user.id, platform=tmp.PLATFORM, is_active=True)
        db.session.add(self.integration)
        db.session.add_all([
            Order(user_id=user.id, platform=tmp.PLATFORM, external_id="valid-1",
                  status="Delivered", total_price=5250.0, created_at=datetime.utcnow()),
            Order(user_id=user.id, platform=tmp.PLATFORM, external_id="return-1",
                  status="Delivered", total_price=200.0, created_at=datetime.utcnow(),
                  raw_json=json.dumps({"status": "Delivered", "shipmentPackageStatus": "Returned"})),
            Order(user_id=user.id, platform=tmp.PLATFORM, external_id="return-2",
                  status="Delivered", total_price=200.0, created_at=datetime.utcnow(),
                  raw_json=json.dumps({"status": "Delivered", "packageStatus": "REFUNDED"})),
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_status_prioritizes_return_over_delivered(self):
        self.assertEqual(
            tmp.status({"status": "Delivered", "shipmentPackageStatus": "Returned"}),
            "Returned",
        )
        self.assertTrue(tmp.is_refunded({"status": "Delivered", "packageStatus": "REFUNDED"}))

    def test_report_deducts_refunds_even_when_saved_status_is_stale(self):
        orders = Order.query.filter_by(user_id=self.integration.user_id, platform=tmp.PLATFORM).all()
        self.assertEqual(sum(order.total_price for order in orders), 5650.0)
        self.assertTrue(all(_is_refunded_order(order) for order in orders if order.external_id.startswith("return")))

        with patch("worker.send_to_user", return_value=True) as send:
            _send_period_report(self.integration, "Günlük", "13.09.2026", orders)

        message = send.call_args.args[1]
        whatsapp_params = send.call_args.kwargs["wa"]
        self.assertIn("İade Sipariş:</b> 2 (400.00 ₺)", message)
        self.assertIn("Geçerli Ciro:</b> 5250.00 ₺", message)
        self.assertEqual(whatsapp_params[2], "5250.00 ₺")


if __name__ == "__main__":
    unittest.main()

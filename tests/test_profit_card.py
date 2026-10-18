import json
import re
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import pytz

from app import create_app
from extensions import db
from models import Order, PlatformCommission, PlatformExpense, ProductCost, User, Integration
import profit_report

TR = pytz.timezone("Europe/Istanbul")


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False
    TRIAL_DAYS = 0
    TELEGRAM_BOT_TOKEN = "test-token"


def _utc(day, hour=12):
    return TR.localize(datetime.combine(day, datetime.min.time()) + timedelta(hours=hour)) \
        .astimezone(pytz.utc).replace(tzinfo=None)


class ProfitCardTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.user = User(email="karne@example.invalid", name="Karne", telegram_chat_id="42")
        self.user.set_password("x" * 10)
        db.session.add(self.user)
        db.session.commit()
        uid = self.user.id
        db.session.add(Integration(user_id=uid, platform="trendyolgo", is_active=True))
        db.session.add(PlatformCommission(user_id=uid, platform="trendyolgo", percentage=20))
        db.session.add(ProductCost(user_id=uid, platform="trendyolgo", product_key="d", product_name="Dürüm", unit_cost=60))
        db.session.add(ProductCost(user_id=uid, platform="trendyolgo", product_key="a", product_name="Ayran", unit_cost=25))
        db.session.add(PlatformExpense(user_id=uid, platform="genel", name="Paket", amount=5,
                                       expense_type="per_order", day_from=datetime(2026, 1, 1).date(),
                                       day_to=datetime(2026, 12, 31).date()))
        self.start, self.end = profit_report.last_week_range(datetime(2026, 10, 19).date())  # 12–18 Ekim
        day = self.start + timedelta(days=2)

        def order(ext, lines, status="Delivered", when=day):
            db.session.add(Order(user_id=uid, platform="trendyolgo", external_id=ext, status=status,
                                 total_price=sum(l["price"] for l in lines),
                                 raw_json=json.dumps({"lines": lines}), created_at=_utc(when)))

        order("1", [{"name": "Dürüm", "quantity": 1, "price": 150}, {"name": "Ayran", "quantity": 1, "price": 20}])
        order("2", [{"name": "Lahmacun", "quantity": 1, "price": 80}])
        order("3", [{"name": "Dürüm", "quantity": 1, "price": 150}], status="Cancelled")
        order("4", [{"name": "Dürüm", "quantity": 1, "price": 150}], when=self.start - timedelta(days=3))  # önceki hafta
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_weekly_numbers(self):
        r = profit_report.compute_with_previous(self.user.id, self.start, self.end)
        self.assertEqual(r["orders"], 2)                      # iptal hariç
        self.assertAlmostEqual(r["revenue"], 250)
        self.assertAlmostEqual(r["commission"], 50)
        self.assertAlmostEqual(r["cost"], 85)
        self.assertAlmostEqual(r["other"], 10)                # 2 sipariş × 5 TL
        self.assertAlmostEqual(r["profit"], 105)
        self.assertEqual([p["name"] for p in r["loss_products"]], ["Ayran"])
        self.assertAlmostEqual(r["loss_products"][0]["profit"], 20 - 4 - 25)
        self.assertEqual(r["top_products"][0]["name"], "Dürüm")
        self.assertEqual(r["uncosted_count"], 1)
        self.assertAlmostEqual(r["uncosted_revenue_share"], 32)
        self.assertAlmostEqual(r["previous"]["revenue"], 150)
        self.assertAlmostEqual(r["revenue_change"], (250 - 150) / 150 * 100)

    def test_telegram_text_hides_loss_names_for_free(self):
        import utils
        r = profit_report.compute_with_previous(self.user.id, self.start, self.end)
        free = profit_report.telegram_text(r, utils.platform_label, show_details=False, panel_url="u")
        pro = profit_report.telegram_text(r, utils.platform_label, show_details=True, panel_url="u")
        self.assertIn("1 ürün zararına satıldı", free)
        self.assertNotIn("Ayran", free)
        self.assertIn("Ayran", pro)
        self.assertIn("250 TL", pro)

    @patch("notifications.telegram.send_message", return_value=True)
    def test_weekly_job_sends_once(self, send):
        import monitoring
        with patch("profit_report.last_week_range", return_value=(self.start, self.end)):
            monitoring.send_weekly_profit_cards(self.app)
            monitoring.send_weekly_profit_cards(self.app)
        self.assertEqual(send.call_count, 1)
        self.assertIn("Haftalık Kâr Karnesi", send.call_args.args[2])

    def test_page_renders(self):
        client = self.app.test_client()
        with client.session_transaction() as s:
            s["_user_id"] = str(self.user.id)
            s["_fresh"] = True
        html = client.get(f"/panel/kar-karnesi?hafta={self.start.isoformat()}").get_data(as_text=True)
        self.assertIn("Kâr karnesi", html)
        self.assertIn("250 TL", html)
        self.assertIn("1 ürün", html)            # ücretsiz: zarar listesi kilitli
        self.assertNotIn("<td>Ayran</td>", html)
        resp = client.get("/panel/")
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_shows_recent_loss_alert(self):
        today = datetime.now(TR).date()
        db.session.add(Order(user_id=self.user.id, platform="trendyolgo", external_id="t1", status="Delivered",
                             total_price=20, raw_json=json.dumps({"lines": [{"name": "Ayran", "quantity": 1, "price": 20}]}),
                             created_at=_utc(today, hour=0) + timedelta(minutes=5)))
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as s:
            s["_user_id"] = str(self.user.id)
            s["_fresh"] = True
        html = client.get("/panel/").get_data(as_text=True)
        self.assertIn("Son 7 günde 1 ürün zararına satıldı", html)


if __name__ == "__main__":
    unittest.main()

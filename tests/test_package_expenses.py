import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app import create_app
from extensions import db
from models import User, Order, PlatformExpense, DailyAdvertisingExpense


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False


class PackageExpensesTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.context = self.app.app_context()
        self.context.push()
        user = User(email="test@example.invalid", name="Test", password_hash="unused")
        other = User(email="other@example.invalid", name="Other", password_hash="unused")
        db.session.add_all([user, other])
        db.session.flush()
        self.user_id = user.id
        for n in range(22):
            db.session.add(Order(user_id=user.id, platform="trendyolgo", external_id=str(n), status="Delivered"))
        for status in ("Cancelled", "Refunded"):
            db.session.add(Order(user_id=user.id, platform="trendyolgo", external_id=status, status=status))
        db.session.add(Order(user_id=user.id, platform="migros", external_id="1", status="Delivered"))
        db.session.add(Order(user_id=other.id, platform="trendyolgo", external_id="1", status="Delivered"))
        db.session.add(Order(user_id=user.id, platform="trendyolgo", external_id="old", status="Delivered",
                             created_at=datetime.utcnow() - timedelta(days=100)))
        db.session.commit()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True
            session["_csrf_token"] = "test"

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def save(self, amount="10", expense_type="per_order", platform="trendyolgo", name="Ambalaj"):
        return self.client.post("/panel/maliyetler", data={"_csrf_token": "test", "form_type": "expense",
            "expense_platform": platform, "expense_name": name, "expense_amount": amount, "expense_type": expense_type})

    def test_package_cost_and_upsert(self):
        self.assertEqual(self.save().status_code, 302)
        self.save()
        self.assertEqual(PlatformExpense.query.count(), 1)
        with patch("routes.dashboard.render_template", return_value="ok") as render:
            self.client.get("/panel/maliyetler?days=30&platform=trendyolgo")
            values = render.call_args.kwargs
            self.assertEqual(values["order_counts"]["trendyolgo"], 22)
            self.assertEqual(values["expense_total"], 220)
            self.assertEqual(values["profit_total"], -220)
        # Exercise Jinja as well as the calculation.
        result = self.client.get("/panel/maliyetler?days=30&platform=trendyolgo")
        self.assertEqual(result.status_code, 200)
        self.assertIn("220.00 TL", result.get_data(as_text=True))

    def test_general_expense_respects_platform_and_fixed_cost(self):
        self.save(platform="genel")
        self.save(amount="5", expense_type="fixed", platform="migros", name="Sabit")
        with patch("routes.dashboard.render_template", return_value="ok") as render:
            self.client.get("/panel/maliyetler?platform=migros&q=missing")
            self.assertEqual(render.call_args.kwargs["expense_total"], 15)

    def test_invalid_number_is_not_saved(self):
        for value in ("nan", "inf", "-1"):
            self.save(amount=value)
        self.assertEqual(PlatformExpense.query.count(), 0)

    def test_daily_advertising_expense_is_upserted_and_added_to_daily_profit(self):
        day = (datetime.utcnow() - timedelta(days=1)).date()
        payload = {
            "_csrf_token": "test",
            "form_type": "advertising",
            "advertising_day": day.isoformat(),
            "advertising_amount": "125.50",
        }
        self.assertEqual(self.client.post("/panel/maliyetler", data=payload).status_code, 302)
        payload["advertising_amount"] = "150.00"
        self.client.post("/panel/maliyetler", data=payload)
        self.assertEqual(DailyAdvertisingExpense.query.count(), 1)
        self.assertEqual(DailyAdvertisingExpense.query.first().amount, 150.0)

        with patch("routes.dashboard.render_template", return_value="ok") as render:
            self.client.get(f"/panel/maliyetler?start_date={day.isoformat()}&end_date={day.isoformat()}")
            values = render.call_args.kwargs
            row = next(item for item in values["daily_rows"] if item["date"] == day)
            self.assertEqual(row["advertising_expense"], 150.0)
            self.assertEqual(row["expense"], 150.0)
            self.assertEqual(row["profit"], -150.0)
            self.assertEqual(values["advertising_total"], 150.0)
            self.assertEqual(values["expense_total"], 150.0)


if __name__ == "__main__":
    unittest.main()

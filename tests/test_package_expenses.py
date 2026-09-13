import unittest
from calendar import monthrange
from datetime import datetime, timedelta
from unittest.mock import patch

from app import create_app
from extensions import db
from models import User, Order, PlatformExpense, DailyAdvertisingExpense, MonthlyExpense


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
        day = (datetime.utcnow() - timedelta(days=3)).date()
        end_day = day + timedelta(days=2)
        payload = {
            "_csrf_token": "test",
            "form_type": "advertising",
            "advertising_day_from": day.isoformat(),
            "advertising_day_to": end_day.isoformat(),
            "advertising_amount": "125.50",
        }
        self.assertEqual(self.client.post("/panel/maliyetler", data=payload).status_code, 302)
        payload["advertising_amount"] = "150.00"
        self.client.post("/panel/maliyetler", data=payload)
        self.assertEqual(DailyAdvertisingExpense.query.count(), 3)
        self.assertEqual(DailyAdvertisingExpense.query.filter_by(day=day).first().amount, 150.0)

        with patch("routes.dashboard.render_template", return_value="ok") as render:
            self.client.get(f"/panel/maliyetler?start_date={day.isoformat()}&end_date={end_day.isoformat()}")
            values = render.call_args.kwargs
            row = next(item for item in values["daily_rows"] if item["date"] == day)
            self.assertEqual(row["advertising_expense"], 150.0)
            self.assertEqual(row["expense"], 150.0)
            self.assertEqual(row["profit"], -150.0)
            self.assertEqual(values["advertising_total"], 450.0)
            self.assertEqual(values["expense_total"], 450.0)
            self.assertEqual(row["estimated_profit"], 0.0)

    def test_cost_page_renders_without_advertising_records(self):
        response = self.client.get("/panel/maliyetler?days=30")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Gün gün kârlılık", response.get_data(as_text=True))

    def test_cost_entry_contains_expense_inputs_and_keeps_user_on_page(self):
        response = self.client.get("/panel/maliyet-girisi")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Platforma özel diğer giderler", response.get_data(as_text=True))
        saved = self.client.post("/panel/maliyetler", data={
            "_csrf_token": "test", "return_to": "entry", "form_type": "expense",
            "expense_platform": "trendyolgo", "expense_name": "Paket",
            "expense_amount": "10", "expense_type": "per_order",
        })
        self.assertEqual(saved.status_code, 302)
        self.assertIn("/panel/maliyet-girisi", saved.headers["Location"])

    def test_advertising_expense_with_existing_order_day_does_not_raise_key_error(self):
        day = datetime.utcnow().date()
        db.session.add(DailyAdvertisingExpense(user_id=self.user_id, day=day, amount=75.0))
        db.session.add(Order(user_id=self.user_id, platform="trendyolgo", external_id="same-day",
                             status="Delivered", created_at=datetime.utcnow()))
        db.session.commit()
        response = self.client.get(f"/panel/maliyetler?start_date={day.isoformat()}&end_date={day.isoformat()}")
        self.assertEqual(response.status_code, 200)

    def test_monthly_expense_is_upserted_and_included_in_profit(self):
        month = datetime.utcnow().date().replace(day=1)
        payload = {
            "_csrf_token": "test",
            "expense_month": month.strftime("%Y-%m"),
            "expense_name": "Kira",
            "expense_amount": "3000",
        }
        self.assertEqual(self.client.post("/panel/aylik-giderler", data=payload).status_code, 302)
        payload["expense_amount"] = "3500"
        self.client.post("/panel/aylik-giderler", data=payload)
        self.assertEqual(MonthlyExpense.query.count(), 1)
        self.assertEqual(MonthlyExpense.query.first().amount, 3500.0)
        monthly_page = self.client.get(f"/panel/aylik-giderler?month={month.strftime('%Y-%m')}")
        self.assertEqual(monthly_page.status_code, 200)
        self.assertIn("Kira", monthly_page.get_data(as_text=True))
        with patch("routes.dashboard.render_template", return_value="ok") as render:
            self.client.get(f"/panel/maliyetler?start_date={month.isoformat()}&end_date={month.isoformat()}")
            expected = 3500.0 / monthrange(month.year, month.month)[1]
            self.assertAlmostEqual(render.call_args.kwargs["monthly_expense_total"], expected)
        expense_id = MonthlyExpense.query.first().id
        edit_page = self.client.get(f"/panel/aylik-giderler?month={month.strftime('%Y-%m')}&edit_id={expense_id}")
        self.assertEqual(edit_page.status_code, 200)
        payload["expense_id"] = str(expense_id)
        payload["expense_amount"] = "3600"
        self.assertEqual(self.client.post("/panel/aylik-giderler", data=payload).status_code, 302)
        self.assertEqual(MonthlyExpense.query.first().amount, 3600.0)
        self.assertEqual(self.client.post(f"/panel/aylik-giderler/{expense_id}/sil", data={"_csrf_token": "test"}).status_code, 302)
        self.assertEqual(MonthlyExpense.query.count(), 0)


if __name__ == "__main__":
    unittest.main()

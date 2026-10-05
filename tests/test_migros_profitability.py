import json
import unittest
from datetime import datetime
from unittest.mock import patch

from app import create_app
from extensions import db
from models import Order, PlatformCommission, PlatformExpense, ProductCost, User
from routes.dashboard import _cost_product_lines


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False


class MigrosProductLinesTest(unittest.TestCase):
    def test_price_is_line_total_in_pennies_not_unit_price(self):
        for quantity in (1, 2, 4):
            with self.subTest(quantity=quantity):
                lines = _cost_product_lines("migros", {
                    "items": [{"name": "Coffee", "amount": quantity, "price": 11000}],
                })
                self.assertEqual(lines[0]["revenue"], 110.0 * quantity)
                self.assertEqual(lines[0]["quantity"], quantity)

    def test_explicit_total_is_not_multiplied_and_zero_is_preserved(self):
        lines = _cost_product_lines("migros", {"items": [
            {"name": "Coffee", "amount": 2, "totalPrice": 11000, "price": 5500},
            {"name": "Free", "amount": 3, "totalPrice": 0, "price": 5500},
        ]})
        self.assertEqual([line["revenue"] for line in lines], [110.0, 0.0])

    def test_only_explicit_unit_price_is_multiplied(self):
        lines = _cost_product_lines("migros", {"items": [
            {"name": "Coffee", "amount": 3, "unitPrice": 2550},
        ]})
        self.assertEqual(lines[0]["revenue"], 76.5)

    def test_options_and_discounts_do_not_inflate_gross_revenue(self):
        lines = _cost_product_lines("migros", {
            "prices": {"total": {"amountAsPenny": 20100},
                       "discounted": {"amountAsPenny": 18100}},
            "items": [{"name": "Pizza", "amount": 1, "price": 16900,
                       "options": [{"primaryPrice": 3200, "quantity": 1}]}],
        })
        self.assertEqual(lines[0]["revenue"], 201.0)

    def test_multiple_products_share_order_total_and_keep_quantities(self):
        lines = _cost_product_lines("migros", {
            "prices": {"total": {"amountAsPenny": 50000}},
            "items": [{"name": "Coffee", "amount": 2, "price": 10000},
                      {"name": "Sandwich", "amount": 1, "price": 30000}],
        })
        self.assertEqual([line["revenue"] for line in lines], [200.0, 300.0])
        self.assertEqual([line["quantity"] for line in lines], [2.0, 1.0])

    def test_zero_order_total_remains_zero(self):
        lines = _cost_product_lines("migros", {
            "prices": {"total": {"amountAsPenny": 0}},
            "items": [{"name": "Coffee", "amount": 2, "price": 11000}],
        })
        self.assertEqual(lines[0]["revenue"], 0.0)


class MigrosProfitabilityPageTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        user = User(email="migros-profit@example.invalid", name="Test", password_hash="unused")
        db.session.add(user)
        db.session.flush()
        self.user_id = user.id
        payload = {"prices": {"total": {"amountAsPenny": 11000}},
                   "items": [{"name": "Coffee", "price": 5500, "amount": 2}]}
        db.session.add_all([
            Order(user_id=user.id, platform="migros", external_id="sale", status="Completed",
                  total_price=110.0, raw_json=json.dumps(payload), created_at=datetime.utcnow()),
            Order(user_id=user.id, platform="migros", external_id="cancel", status="Cancelled",
                  total_price=110.0, raw_json=json.dumps(payload), created_at=datetime.utcnow()),
            Order(user_id=user.id, platform="migros", external_id="refund", status="Refunded",
                  total_price=110.0, raw_json=json.dumps(payload), created_at=datetime.utcnow()),
            ProductCost(user_id=user.id, platform="all", product_key="coffee",
                        product_name="Coffee", unit_cost=20.0),
            PlatformCommission(user_id=user.id, platform="migros", percentage=30.0),
            PlatformExpense(user_id=user.id, platform="migros", name="Packaging", amount=10.0,
                            expense_type="per_order", day_from=datetime.utcnow().date(),
                            day_to=datetime.utcnow().date()),
        ])
        db.session.commit()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_daily_and_period_profit_use_tl_revenue_and_quantity_cost(self):
        with patch("routes.dashboard.render_template", return_value="ok") as render:
            response = self.client.get("/panel/maliyetler?platform=migros&days=30")
            self.assertEqual(response.status_code, 200)
            values = render.call_args.kwargs
        self.assertEqual(values["revenue_total"], 110.0)
        self.assertEqual(values["cost_total"], 40.0)
        self.assertEqual(values["commission_total"], 33.0)
        self.assertEqual(values["expense_total"], 10.0)
        self.assertEqual(values["profit_total"], 27.0)
        product = values["products"][0]
        self.assertEqual(product["quantity"], 2.0)
        self.assertEqual(product["avg_price"], 55.0)
        row = values["daily_rows"][0]
        self.assertEqual(row["orders"], 1)
        self.assertEqual(row["revenue"], 110.0)
        self.assertEqual(row["commission"], 33.0)
        self.assertEqual(row["cost"], 40.0)
        self.assertEqual(row["estimated_profit"], 27.0)
        self.assertEqual(row["profit"], 27.0)
        self.assertEqual(self.client.get("/panel/maliyetler?platform=migros").status_code, 200)


if __name__ == "__main__":
    unittest.main()

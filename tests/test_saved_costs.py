import unittest
from unittest.mock import patch

from app import create_app
from extensions import db
from models import User, ProductCost


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False


class SavedCostsTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.context = self.app.app_context()
        self.context.push()
        user = User(email="test@example.invalid", name="Test", password_hash="unused")
        other = User(email="other@example.invalid", name="Other", password_hash="unused")
        db.session.add_all([user, other])
        db.session.flush()
        self.latte = ProductCost(user_id=user.id, platform="all", product_key="latte", product_name="Latte", unit_cost=250)
        self.americano = ProductCost(user_id=user.id, platform="all", product_key="americano", product_name="Americano", unit_cost=18)
        self.foreign = ProductCost(user_id=other.id, platform="all", product_key="latte", product_name="Latte", unit_cost=30)
        db.session.add_all([self.latte, self.americano, self.foreign])
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

    def test_entry_page_lists_saved_costs(self):
        with patch("routes.dashboard.render_template", return_value="ok") as render:
            self.client.get("/panel/maliyet-girisi")
        names = [row.product_name for row in render.call_args.kwargs["saved_costs"]]
        self.assertEqual(names, ["Americano", "Latte"])

    def test_update_changes_only_edited_values(self):
        response = self.client.post("/panel/maliyet-girisi/kayitli", data={
            "_csrf_token": "test",
            f"saved_cost_{self.latte.id}": "25,50",
            f"saved_cost_{self.americano.id}": "18.00",
            f"saved_cost_{self.foreign.id}": "1",
        })
        self.assertEqual(response.status_code, 302)
        self.assertAlmostEqual(db.session.get(ProductCost, self.latte.id).unit_cost, 25.5)
        self.assertAlmostEqual(db.session.get(ProductCost, self.americano.id).unit_cost, 18)
        self.assertAlmostEqual(db.session.get(ProductCost, self.foreign.id).unit_cost, 30)

    def test_invalid_value_is_skipped(self):
        self.client.post("/panel/maliyet-girisi/kayitli", data={
            "_csrf_token": "test", f"saved_cost_{self.latte.id}": "-5"})
        self.assertAlmostEqual(db.session.get(ProductCost, self.latte.id).unit_cost, 250)

    def test_delete_own_row_only(self):
        self.client.post("/panel/maliyet-girisi/kayitli", data={"_csrf_token": "test", "delete_id": self.foreign.id})
        self.assertIsNotNone(db.session.get(ProductCost, self.foreign.id))
        self.client.post("/panel/maliyet-girisi/kayitli", data={"_csrf_token": "test", "delete_id": self.latte.id})
        self.assertIsNone(db.session.get(ProductCost, self.latte.id))


if __name__ == "__main__":
    unittest.main()

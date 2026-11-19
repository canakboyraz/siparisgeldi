import unittest

from app import create_app
from extensions import db
from models import User, ProductAlias, ProductCost
from routes.dashboard import _cost_product_lines, alias_suggestions


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False


class ProductAliasTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.context = self.app.app_context()
        self.context.push()
        user = User(email="test@example.invalid", name="Test", password_hash="unused")
        db.session.add(user)
        db.session.flush()
        self.user_id = user.id
        db.session.add(ProductCost(user_id=user.id, platform="all", product_key="magnolia cup",
                                   product_name="Magnolia Cup", unit_cost=80))
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

    def test_suggestions_keep_size_and_ice_apart(self):
        groups = alias_suggestions(["Magnolia Cup", "MagnoliaCup", "Latte", "Latte Ice", "Ice Latte",
                                    "Latte Büyük", "Latte (Büyük)", "Tiramisu - Mascarpone", "Tiramisu (Mascarpone)"])
        self.assertIn(["Magnolia Cup", "MagnoliaCup"], groups)
        self.assertIn(["Ice Latte", "Latte Ice"], groups)
        self.assertIn(["Latte (Büyük)", "Latte Büyük"], groups)
        self.assertFalse(any("Latte" in g and "Latte Ice" in g for g in groups))

    def test_merge_maps_lines_and_copies_cost(self):
        r = self.client.post("/panel/urun-eslestirme", data={
            "_csrf_token": "test", "action": "merge", "canonical": "Magnolia",
            "names": ["Magnolia", "Magnolia Cup", "Mangolia"]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(ProductAlias.query.count(), 2)
        cost = ProductCost.query.filter_by(product_key="magnolia").one()
        self.assertEqual(cost.unit_cost, 80)
        aliases = {a.alias_key: a.canonical_name for a in ProductAlias.query.all()}
        data = {"lines": [{"name": "Mangolia", "quantity": 1, "price": 150}]}
        line = _cost_product_lines("trendyolgo", data, aliases)[0]
        self.assertEqual(line["name"], "Magnolia")
        # ayır
        alias = ProductAlias.query.filter_by(alias_key="mangolia").one()
        self.client.post("/panel/urun-eslestirme", data={"_csrf_token": "test", "action": "unlink", "alias_id": alias.id})
        self.assertEqual(ProductAlias.query.count(), 1)


if __name__ == "__main__":
    unittest.main()

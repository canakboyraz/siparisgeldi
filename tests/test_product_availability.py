import unittest
from unittest.mock import patch

from app import create_app
from extensions import db
from models import Integration, MenuCategory, MenuItem, ProductAlias, User


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False


TGO_MENU = [
    {"id": 11, "name": "Sahlep", "status": "ACTIVE", "price": 210},
    {"id": 12, "name": "Latte", "status": "PASSIVE", "price": 180},
]


class ProductAvailabilityTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.context = self.app.app_context()
        self.context.push()
        user = User(email="av@example.invalid", name="Test", password_hash="unused")
        db.session.add(user)
        db.session.flush()
        self.uid = user.id
        intg = Integration(user_id=user.id, platform="trendyolgo", is_active=True,
                           tgo_supplier_id="1", tgo_store_id="2")
        intg.tgo_api_key, intg.tgo_api_secret = "k", "s"
        db.session.add(intg)
        cat = MenuCategory(user_id=user.id, name="Sıcak")
        db.session.add(cat)
        db.session.flush()
        db.session.add(MenuItem(user_id=user.id, category_id=cat.id, name="Salep", price=200, is_available=True))
        db.session.add(ProductAlias(user_id=user.id, alias_key="salep", alias_name="Salep", canonical_name="Sahlep"))
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

    @patch("integrations.trendyolgo.get_meal_products", return_value=TGO_MENU)
    def test_page_groups_aliases(self, _menu):
        html = self.client.get("/panel/urun-durumu").get_data(as_text=True)
        self.assertIn("Sahlep", html)
        self.assertIn("QR menü · Açık", html)
        self.assertIn("Trendyol Go · Kapalı", html)   # Latte

    @patch("integrations.trendyolgo.set_meal_product_status")
    @patch("integrations.trendyolgo.get_meal_products", return_value=TGO_MENU)
    def test_close_everywhere(self, _menu, set_status):
        resp = self.client.post("/panel/urun-durumu", data={"_csrf_token": "test", "key": "sahlep", "action": "close"})
        self.assertEqual(resp.status_code, 302)
        set_status.assert_called_once_with("1", "2", "k", "s", 11, False)
        self.assertFalse(MenuItem.query.filter_by(name="Salep").first().is_available)

    @patch("integrations.trendyolgo.set_meal_product_status")
    @patch("integrations.trendyolgo.get_meal_products", return_value=TGO_MENU)
    def test_open_skips_already_open(self, _menu, set_status):
        self.client.post("/panel/urun-durumu", data={"_csrf_token": "test", "key": "latte", "action": "open"})
        set_status.assert_called_once_with("1", "2", "k", "s", 12, True)

    @patch("integrations.trendyolgo.get_meal_products", return_value=TGO_MENU)
    def test_merge_from_page(self, _menu):
        self.client.post("/panel/urun-durumu", data={"_csrf_token": "test", "action": "merge",
                                                     "names": ["Latte", "Sahlep"], "canonical": "Sahlep"})
        self.assertEqual(ProductAlias.query.filter_by(user_id=self.uid, alias_key="latte").first().canonical_name, "Sahlep")
        self.client.post("/panel/urun-durumu", data={"_csrf_token": "test", "action": "split", "key": "sahlep"})
        self.assertEqual(ProductAlias.query.filter_by(user_id=self.uid).count(), 0)


if __name__ == "__main__":
    unittest.main()

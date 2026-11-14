import io
import json
import re
import unittest
from unittest import mock

from PIL import Image

from app import create_app
from extensions import db
import menu
from models import Integration, MenuCategory, MenuItem, User
from tests.test_posentegra import TestConfig

SECTIONS = [
    {"name": "Bu Restoranın En Sevilenleri", "products": [{"id": 1, "name": "Browni", "price": {"salePrice": 300},
                                                          "imageUrl": "https://cdn.tgoapps.com/a/1.jpg?x=1"}]},
    {"name": "Tatlılar", "products": [
        {"id": 1, "name": "Browni", "price": {"salePrice": 300}, "description": "Bitter \"çikolata\"",
         "imageUrl": "https://cdn.tgoapps.com/a/1.jpg?x=1", "active": True},
        {"id": 2, "name": "Nata", "price": {"salePrice": 120}, "imageUrl": "https://evil.example.com/x.jpg"}]},
    {"name": "Kahveler", "products": [{"id": 3, "name": "Latte", "price": {"salePrice": 220},
                                       "imageUrl": "https://cdn.tgoapps.com/a/3.jpg"}]},
]


def _page():
    flight = '2f:["$","$L32",null,{"sections":' + json.dumps(SECTIONS, ensure_ascii=False) + '}]\n'
    half = len(flight) // 2
    parts = [flight[:half], flight[half:]]
    return "<html><script>" + "".join(
        f"self.__next_f.push([1,{json.dumps(p, ensure_ascii=False)}])" for p in parts) + "</script></html>"


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "brown").save(buf, "PNG")
    return buf.getvalue()


def _get(url, **kw):
    r = mock.Mock()
    if "tgoyemek.com" in url:
        r.status_code, r.text = 200, _page()
    else:
        r.status_code, r.content = 200, _png()
    return r


class TgoMenuImportTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        u = User(email="pion@kafe.com", name="Pion", is_trial=True)
        u.set_password("sifre12345")
        db.session.add(u)
        db.session.flush()
        self.uid = u.id
        db.session.add(Integration(user_id=u.id, platform="trendyolgo", is_active=True, tgo_store_id="446617"))
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_parse(self):
        data = menu.parse_tgo_menu(_page())
        self.assertEqual([c["name"] for c in data], ["Tatlılar", "Kahveler"])
        self.assertEqual(data[0]["items"][0]["description"], 'Bitter "çikolata"')
        self.assertEqual(data[0]["items"][0]["image"], "https://cdn.tgoapps.com/a/1.jpg")

    def test_import_route_twice_no_duplicates(self):
        html = self.client.get("/giris").get_data(as_text=True)
        tok = re.search(r'name="_csrf_token" value="([^"]+)"', html).group(1)
        self.client.post("/giris", data={"_csrf_token": tok, "email": "pion@kafe.com", "password": "sifre12345"})
        page = self.client.get("/panel/menu/urunler").get_data(as_text=True)
        self.assertIn("Trendyol Go menüsünü çek", page)
        form = re.search(r'action="/panel/menu/trendyol-aktar".*?</form>', page, re.S).group(0)
        tok = re.search(r'name="_csrf_token" value="([^"]+)"', form).group(1)
        with mock.patch("requests.get", side_effect=_get) as get:
            self.client.post("/panel/menu/trendyol-aktar", data={"_csrf_token": tok, "mode": "full"})
            self.client.post("/panel/menu/trendyol-aktar", data={"_csrf_token": tok, "mode": "full"})
        self.assertFalse(any("evil.example.com" in c.args[0] for c in get.call_args_list))
        self.assertEqual(MenuCategory.query.filter_by(user_id=self.uid).count(), 2)
        items = {i.name: i for i in MenuItem.query.filter_by(user_id=self.uid)}
        self.assertEqual(set(items), {"Browni", "Nata", "Latte"})
        self.assertIsNotNone(items["Browni"].image_id)
        self.assertIsNone(items["Nata"].image_id)
        self.assertEqual(float(items["Latte"].price), 220.0)


class TgoMediaModeTest(TgoMenuImportTest):
    def test_match_key(self):
        self.assertEqual(menu.match_key("Americano Büyük"), menu.match_key("Americano"))
        self.assertEqual(menu.match_key("Türk Kahvesi (Küçük)"), menu.match_key("Türk kahvesi"))
        self.assertEqual(menu.match_key("Ezine & Hindi Füme Sandviç"), menu.match_key("Ezine Hindi Füme"))
        self.assertEqual(menu.match_key("Iced Salted Karamel Latte"), menu.match_key("Ice Salted Karamel Latte"))
        self.assertNotEqual(menu.match_key("Ice Latte"), menu.match_key("Latte"))

    def test_media_only(self):
        cat = MenuCategory(user_id=self.uid, name="Tatlı")
        db.session.add(cat); db.session.flush()
        b = MenuItem(user_id=self.uid, category_id=cat.id, name="Browni", price=150, adisyo_product_id=7)
        lb = MenuItem(user_id=self.uid, category_id=cat.id, name="Latte Büyük", price=180)
        db.session.add_all([b, lb]); db.session.commit()
        with mock.patch("requests.get", side_effect=_get):
            n, images, unmatched = menu.import_menu_media(db.session.get(User, self.uid), menu.fetch_tgo_menu("446617"))
            menu.attach_images(self.uid, images)
        self.assertEqual(n, 2)
        self.assertEqual(unmatched, ["Nata"])
        db.session.expire_all()
        b = db.session.get(MenuItem, b.id)
        self.assertEqual(float(b.price), 150.0)
        self.assertEqual(b.adisyo_product_id, 7)
        self.assertIsNotNone(b.image_id)
        self.assertEqual(b.description, 'Bitter "çikolata"')
        self.assertIsNotNone(db.session.get(MenuItem, lb.id).image_id)
        self.assertEqual(MenuItem.query.filter_by(user_id=self.uid).count(), 2)

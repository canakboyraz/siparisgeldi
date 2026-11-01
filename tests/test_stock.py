import io
import re
import unittest
from datetime import date, timedelta

import openpyxl

from app import create_app
from extensions import db
import stock
from models import StockCategory, StockCount, StockCountLine, StockItem, StockSetting, User


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False
    TRIAL_DAYS = 0


class StockTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        from flask import g
        self.app.before_request(lambda: g.pop("_login_user", None) and None)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.owner = self._user("pion@kafe.com", "Pion Coffee")
        self._user("baska@kafe.com", "Başka")
        self.staff = self.app.test_client()
        self._login(self.staff, "pion@kafe.com")
        self.barista = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _user(self, email, name):
        u = User(name=name, email=email)
        u.set_password("sifre12345")
        db.session.add(u)
        db.session.commit()
        return u

    @staticmethod
    def _csrf(client, path):
        html = client.get(path).get_data(as_text=True)
        return re.search(r'name="_csrf_token" value="([^"]+)"', html).group(1)

    def _login(self, client, email):
        token = self._csrf(client, "/giris")
        client.post("/giris", data={"_csrf_token": token, "email": email, "password": "sifre12345"})

    def _post(self, client, path, data, page="/panel/sayim", **kw):
        data = dict(data, _csrf_token=self._csrf(client, page))
        return client.post(path, data=data, **kw)

    def _setup_list(self):
        self.assertEqual(self.staff.get("/panel/sayim").status_code, 200)   # bağlantı oluşur
        self._post(self.staff, "/panel/sayim/ornek-liste", {})
        return StockSetting.query.filter_by(user_id=self.owner.id).one()

    def test_parse_and_format(self):
        self.assertEqual(stock.parse_qty("2,5"), 2.5)
        self.assertEqual(stock.parse_qty(" 3 "), 3)
        self.assertEqual(stock.parse_qty("1.250,5"), 1250.5)
        self.assertIsNone(stock.parse_qty(""))
        with self.assertRaises(ValueError):
            stock.parse_qty("abc")
        with self.assertRaises(ValueError):
            stock.parse_qty("-1")
        self.assertEqual(stock.fmt(2.5), "2,5")
        self.assertEqual(stock.fmt(3.0), "3")

    def test_seed_and_manage_items(self):
        setting = self._setup_list()
        self.assertEqual(StockCategory.query.count(), 13)
        n = StockItem.query.count()
        self.assertGreater(n, 90)
        self._post(self.staff, "/panel/sayim/ornek-liste", {})          # tekrar eklemez
        self.assertEqual(StockItem.query.count(), n)
        syrup = StockCategory.query.filter_by(name="Şuruplar").one()
        first = syrup.items.first()
        page = self.staff.get("/panel/sayim/urunler").get_data(as_text=True)
        self.assertIn("Vanilya şurubu", page)
        # toplu düzenle + yeni ürün
        r = self._post(self.staff, f"/panel/sayim/kategori/{syrup.id}/urunler",
                       {f"i{first.id}_name": "Vanilya", f"i{first.id}_unit": "şişe", f"i{first.id}_min": "2,5",
                        f"i{first.id}_active": "1", "new_name": "Fındık şurubu", "new_unit": "şişe", "new_min": "1"},
                       page="/panel/sayim/urunler")
        self.assertEqual(r.status_code, 302)
        db.session.expire_all()
        self.assertEqual((first.name, first.min_stock), ("Vanilya", 2.5))
        self.assertTrue(StockItem.query.filter_by(name="Fındık şurubu").first())
        # gizle: aktif kutusu işaretsiz gelirse sayımdan düşer
        self._post(self.staff, f"/panel/sayim/kategori/{syrup.id}/urunler",
                   {f"i{first.id}_name": "Vanilya", f"i{first.id}_unit": "şişe", f"i{first.id}_min": "2,5"},
                   page="/panel/sayim/urunler")
        db.session.expire_all()
        self.assertFalse(first.is_active)
        self.assertNotIn("Vanilya</b>", self.barista.get(f"/s/{setting.token}").get_data(as_text=True))
        # yeni kategori, taşıma, sıralama, silme
        self._post(self.staff, "/panel/sayim/kategori", {"name": "Meyveler"}, page="/panel/sayim/urunler")
        fruit = StockCategory.query.filter_by(name="Meyveler").one()
        item = StockItem.query.filter_by(name="Fındık şurubu").one()
        self._post(self.staff, f"/panel/sayim/urun/{item.id}/kategori", {f"mv_{item.id}": str(fruit.id)},
                   page="/panel/sayim/urunler")
        db.session.expire_all()
        self.assertEqual(item.category_id, fruit.id)
        self._post(self.staff, f"/panel/sayim/kategori/{fruit.id}/tasi", {"yon": "yukari"}, page="/panel/sayim/urunler")
        self._post(self.staff, f"/panel/sayim/kategori/{fruit.id}/ad", {"name": "Meyve"}, page="/panel/sayim/urunler")
        db.session.expire_all()
        self.assertEqual(fruit.name, "Meyve")
        self._post(self.staff, f"/panel/sayim/urun/{item.id}/sil", {}, page="/panel/sayim/urunler")
        self.assertIsNone(StockItem.query.filter_by(name="Fındık şurubu").first())
        self._post(self.staff, f"/panel/sayim/kategori/{fruit.id}/sil", {}, page="/panel/sayim/urunler")
        self.assertIsNone(db.session.get(StockCategory, fruit.id))
        # başka işletme bu kategoriye dokunamaz
        other = self.app.test_client()
        self._login(other, "baska@kafe.com")
        r = self._post(other, f"/panel/sayim/kategori/{syrup.id}/sil", {}, page="/panel/sayim/urunler")
        self.assertEqual(r.status_code, 404)

    def test_barista_count_flow(self):
        setting = self._setup_list()
        milk = StockItem.query.filter_by(name="Yağlı süt").one()     # min 12
        espresso = StockItem.query.filter_by(name="Espresso").one()  # min 3
        page = self.barista.get(f"/s/{setting.token}").get_data(as_text=True)
        self.assertIn("Sayımı gönder", page)
        self.assertIn("Yağlı süt", page)
        self.assertIn('inputmode="decimal"', page)
        # eksik ad + hatalı sayı
        token = self._csrf(self.barista, f"/s/{setting.token}")
        r = self.barista.post(f"/s/{setting.token}", data={"_csrf_token": token, "count_date": date.today().isoformat(),
                                                           "counted_by": "", f"c_{milk.id}": "abc"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Adını yaz", r.get_data(as_text=True))
        self.assertEqual(StockCount.query.count(), 0)
        # 1. gün
        day1 = date.today() - timedelta(days=1)
        r = self.barista.post(f"/s/{setting.token}", data={
            "_csrf_token": token, "count_date": day1.isoformat(), "counted_by": "Doğa",
            f"c_{milk.id}": "20", f"c_{espresso.id}": "4,5"})
        self.assertEqual(r.status_code, 302)
        done = self.barista.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("Sayım kaydedildi", done)
        # 2. gün: süt 20 + gelen 12 → 10 sayıldı (kullanılan 22), espresso 4,5 → 5 (eksi: kontrol), min altı
        r = self.barista.post(f"/s/{setting.token}", data={
            "_csrf_token": token, "count_date": date.today().isoformat(), "counted_by": "Sümeyye",
            f"c_{milk.id}": "10", f"r_{milk.id}": "12", f"c_{espresso.id}": "5", f"n_{espresso.id}": "Yeni paket açıldı"})
        self.assertEqual(r.status_code, 302)
        done2 = self.barista.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("Sipariş verilecekler", done2)
        self.assertIn("Azalanlar", done2)
        self.assertIn("20 → 10 litre", done2)
        count = StockCount.query.order_by(StockCount.id.desc()).first()
        lines = {l.item_name: l for l in count.lines}
        self.assertEqual((lines["Yağlı süt"].prev_qty, lines["Yağlı süt"].used), (20, 22))
        self.assertTrue(lines["Yağlı süt"].needs_order)                  # 10 ≤ 12
        self.assertEqual(lines["Espresso"].used, -0.5)
        self.assertFalse(lines["Espresso"].needs_order)
        s = stock.summarize(count)
        self.assertEqual((len(s["order"]), len(s["check"]), len(s["notes"])), (1, 1, 1))
        self.assertEqual(s["counted"], 2)
        self.assertEqual([(l.item_name, l.diff) for l in s["down"]], [("Yağlı süt", -10)])
        self.assertEqual([(l.item_name, l.diff) for l in s["up"]], [("Espresso", 0.5)])
        self.assertEqual(stock.signed(-10), "−10")
        self.assertEqual(stock.signed(0.5), "+0,5")
        # panel
        page = self.staff.get("/panel/sayim").get_data(as_text=True)
        self.assertIn("Sümeyye", page)
        self.assertIn("Sipariş verilecekler", page)
        changed = self.staff.get(f"/panel/sayim/{count.id}?goster=degisen").get_data(as_text=True)
        self.assertIn("Artanlar", changed)
        self.assertIn("+0,5", changed)
        self.assertIn("Önceki sayıma göre", page)
        detail = self.staff.get(f"/panel/sayim/{count.id}?goster=siparis").get_data(as_text=True)
        self.assertIn("Yağlı süt", detail)
        self.assertNotIn("Espresso", detail)
        csv_body = self.staff.get(f"/panel/sayim/{count.id}.csv").get_data(as_text=True)
        self.assertIn("SİPARİŞ VER", csv_body)
        self.assertIn("Yağlı süt;litre;12;20;12;10;−10;22", csv_body)
        # ürün silinse de eski sayım bozulmaz
        self._post(self.staff, f"/panel/sayim/urun/{milk.id}/sil", {}, page="/panel/sayim/urunler")
        self.assertIn("Yağlı süt", self.staff.get(f"/panel/sayim/{count.id}").get_data(as_text=True))
        # ileri tarih reddedilir
        r = self.barista.post(f"/s/{setting.token}", data={
            "_csrf_token": token, "count_date": (date.today() + timedelta(days=2)).isoformat(),
            "counted_by": "Doğa", f"c_{espresso.id}": "3"})
        self.assertEqual(r.status_code, 400)
        # başka işletme bu sayımı göremez
        other = self.app.test_client()
        self._login(other, "baska@kafe.com")
        self.assertEqual(other.get(f"/panel/sayim/{count.id}").status_code, 404)
        self.assertEqual(self.app.test_client().get("/s/yokboyle").status_code, 404)

    def test_pin_and_new_link(self):
        setting = self._setup_list()
        self._post(self.staff, "/panel/sayim/ayarlar", {"action": "pin", "pin": "4321"})
        page = self.barista.get(f"/s/{setting.token}").get_data(as_text=True)
        self.assertIn("Sayım PIN", page)
        self.assertNotIn("Sayımı gönder", page)
        token = self._csrf(self.barista, f"/s/{setting.token}")
        r = self.barista.post(f"/s/{setting.token}/pin", data={"_csrf_token": token, "pin": "1111"})
        self.assertEqual(r.status_code, 400)
        r = self.barista.post(f"/s/{setting.token}/pin", data={"_csrf_token": token, "pin": "4321"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("Sayımı gönder", self.barista.get(f"/s/{setting.token}").get_data(as_text=True))
        old = setting.token
        self._post(self.staff, "/panel/sayim/ayarlar", {"action": "new_link"})
        db.session.expire_all()
        self.assertNotEqual(setting.token, old)
        self.assertEqual(self.barista.get(f"/s/{old}").status_code, 404)

    def test_import_xlsx(self):
        self.staff.get("/panel/sayim")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["☕ GÜNLÜK STOK SAYIM FORMU"])
        ws.append(["Kategori", "Ürün", "Birim", "Min. Stok", "Dünden Kalan"])
        ws.append(["ŞURUPLAR", None, None, None])
        ws.append(["Şuruplar", "Vanilya şurubu", "şişe", 1])
        ws.append([None, "Karamel şurubu", "şişe", "2"])
        ws.append(["PAKET", None, None, None])
        ws.append(["Paket", "Kraft poşet", "adet", 100])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        r = self._post(self.staff, "/panel/sayim/ice-aktar", {"file": (buf, "liste.xlsx")},
                       content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(StockItem.query.count(), 3)
        self.assertEqual(StockItem.query.filter_by(name="Karamel şurubu").one().min_stock, 2)
        self.assertEqual({c.name for c in StockCategory.query}, {"Şuruplar", "Paket"})


if __name__ == "__main__":
    unittest.main()

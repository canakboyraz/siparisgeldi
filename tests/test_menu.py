import io
import json
import re
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest import mock

from PIL import Image

from app import create_app
from extensions import db
import menu
from models import MenuCategory, MenuImage, MenuItem, MenuSetting, MenuTable, TableCall, TableOrder, User


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False
    TRIAL_DAYS = 0
    ENCRYPTION_KEY = "M0dkZ3VvQ1ZqZ0x2b3pXVmJ6a1FwR3hJb1N5c3h6Zkk="


class MenuTest(unittest.TestCase):
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
        self.guest = self.app.test_client()

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
        return re.search(r'(?:name="_csrf_token" value|data-csrf)="([^"]+)"', html).group(1)

    def _login(self, client, email):
        token = self._csrf(client, "/giris")
        client.post("/giris", data={"_csrf_token": token, "email": email, "password": "sifre12345"})

    def _post(self, path, data, page="/panel/menu/urunler", **kw):
        return self.staff.post(path, data=dict(data, _csrf_token=self._csrf(self.staff, page)), **kw)

    def _png(self, size=(1600, 1200)):
        buf = io.BytesIO()
        Image.new("RGB", size, (200, 120, 60)).save(buf, "PNG")
        buf.seek(0)
        return buf

    def _build_menu(self):
        self.assertEqual(self.staff.get("/panel/menu").status_code, 200)
        self._post("/panel/menu/kategori", {"name": "Sıcak kahveler"})
        cat = MenuCategory.query.one()
        r = self._post("/panel/menu/urun/yeni", {"name": "Latte", "price": "95", "category_id": str(cat.id),
                                                "description": "Çift shot", "is_active": "1", "is_available": "1",
                                                "photo": (self._png(), "latte.png")},
                       page=f"/panel/menu/urun/yeni?kategori={cat.id}", content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        self._post("/panel/menu/urun/yeni", {"name": "Cheesecake", "price": "120,50", "category_id": str(cat.id),
                                            "is_active": "1", "is_available": "1"}, page=f"/panel/menu/urun/yeni?kategori={cat.id}")
        self._post("/panel/menu/masalar", {"prefix": "Masa", "start": "1", "end": "4"}, page="/panel/menu/masalar")
        return cat

    def test_money_and_format(self):
        self.assertEqual(menu.money("85,5"), Decimal("85.50"))
        self.assertEqual(menu.tl(Decimal("85")), "85 TL")
        self.assertEqual(menu.tl(Decimal("85.5")), "85,50 TL")
        self.assertEqual(menu.tl(Decimal("1250")), "1.250 TL")
        with self.assertRaises(ValueError):
            menu.money("abc")

    def test_build_menu_tables_and_photo(self):
        self._build_menu()
        latte = MenuItem.query.filter_by(name="Latte").one()
        self.assertEqual(latte.price, Decimal("95.00"))
        img = db.session.get(MenuImage, latte.image_id)
        self.assertEqual(img.mime, "image/webp")
        self.assertEqual(Image.open(io.BytesIO(img.data)).size, (1000, 750))       # küçültüldü
        r = self.guest.get(f"/m/img/{latte.image_id}.webp")
        self.assertEqual((r.status_code, r.mimetype), (200, "image/webp"))
        self.assertIn("immutable", r.headers["Cache-Control"])
        self.assertEqual(MenuTable.query.count(), 4)
        self._post("/panel/menu/masalar", {"prefix": "Masa", "start": "3", "end": "5"}, page="/panel/menu/masalar")
        self.assertEqual(MenuTable.query.count(), 5)      # 3, 4 atlandı
        page = self.staff.get("/panel/menu/masalar").get_data(as_text=True)
        self.assertIn("Masa 5", page)
        printed = self.staff.get("/panel/menu/masalar/yazdir").get_data(as_text=True)
        self.assertIn("Okut, menüyü gör, sipariş ver", printed)
        self.assertEqual(printed.count('class="card"'), 5)
        items_page = self.staff.get("/panel/menu/urunler").get_data(as_text=True)
        self.assertIn("Cheesecake", items_page)
        self.assertIn("120,50", items_page)

    def test_customer_orders_from_table(self):
        self._build_menu()
        table = MenuTable.query.filter_by(name="Masa 3").one()
        latte = MenuItem.query.filter_by(name="Latte").one()
        cake = MenuItem.query.filter_by(name="Cheesecake").one()
        page = self.guest.get(f"/m/{table.code}")
        html = page.get_data(as_text=True)
        self.assertIn("Masa 3", html)
        self.assertIn("Latte", html)
        self.assertIn("Sipariş notu", html)
        self.assertIn("sg_menu_cihaz", page.headers.get("Set-Cookie", ""))
        token = self._csrf(self.guest, f"/m/{table.code}")
        send = lambda body: self.guest.post(f"/m/{table.code}/siparis", data=json.dumps(body),   # noqa: E731
                                            headers={"X-CSRF-Token": token, "Content-Type": "application/json"})
        # telefondan gelen fiyat yok sayılır, menü fiyatı kullanılır
        r = send({"items": [{"id": latte.id, "qty": 2, "price": 1}, {"id": cake.id, "qty": 1}],
                  "note": "Latte laktozsuz olsun", "name": "Ayşe"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        data = r.get_json()
        order = db.session.get(TableOrder, data["order"])
        self.assertEqual((order.table_name, order.total, order.note, order.status),
                         ("Masa 3", Decimal("310.50"), "Latte laktozsuz olsun", "new"))
        self.assertEqual([(l.name, l.quantity) for l in order.lines], [("Latte", 2), ("Cheesecake", 1)])
        status = self.guest.get(data["url"]).get_data(as_text=True)
        self.assertIn("Siparişin alındı", status)
        self.assertIn("Birazdan hazırlanmaya", status)
        self.assertIn("310,50 TL", status)
        # aynı telefondan hemen ikinci sipariş engellenir
        r = send({"items": [{"id": latte.id, "qty": 1}]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("az önce", r.get_json()["message"])
        # panelde uyarı + liste
        alert = self.staff.get("/panel/menu/yeni.json").get_json()["items"]
        self.assertEqual((alert[0]["table"], alert[0]["note"]), ("Masa 3", "Latte laktozsuz olsun"))
        self.assertIn("qo-alert", self.staff.get("/panel/aktif-siparisler").get_data(as_text=True))
        listing = self.staff.get("/panel/menu").get_data(as_text=True)
        self.assertIn("Masa 3", listing)
        self.assertIn("Latte laktozsuz olsun", listing)
        # durum değişir, müşteri görür
        tok = self._csrf(self.staff, "/panel/menu")
        r = self.staff.post(f"/panel/menu/siparis/{order.id}/preparing",
                            headers={"X-CSRF-Token": tok, "X-Requested-With": "fetch"})
        self.assertEqual(r.get_json()["status"], "preparing")
        self.assertEqual(self.guest.get(data["url"] + "?json=1").get_json()["status"], "preparing")
        self.assertEqual(self.staff.get("/panel/menu/yeni.json").get_json()["items"], [])
        # başka işletme bu siparişe dokunamaz
        other = self.app.test_client()
        self._login(other, "baska@kafe.com")
        tok2 = self._csrf(other, "/panel/menu")
        self.assertEqual(other.post(f"/panel/menu/siparis/{order.id}/served",
                                    headers={"X-CSRF-Token": tok2, "X-Requested-With": "fetch"}).status_code, 404)

    def test_order_rules(self):
        self._build_menu()
        table = MenuTable.query.first()
        latte = MenuItem.query.filter_by(name="Latte").one()
        with self.assertRaises(menu.OrderError):
            menu.create_order(table, {"items": []}, "d1")
        latte.is_available = False
        db.session.commit()
        with self.assertRaisesRegex(menu.OrderError, "Latte şu an yok"):
            menu.create_order(table, {"items": [{"id": latte.id, "qty": 1}]}, "d1")
        latte.is_available = True
        db.session.commit()
        o = menu.create_order(table, {"items": [{"id": latte.id, "qty": 99}]}, "d1")
        self.assertEqual(o.lines[0].quantity, 20)                        # üst sınır
        x = self._user("x@x.com", "X")
        other_cat = MenuCategory(user_id=x.id, name="Diğer")
        db.session.add(other_cat)
        db.session.flush()
        other_item = MenuItem(user_id=x.id, category_id=other_cat.id, name="Başka", price=1)
        db.session.add(other_item)
        db.session.commit()
        with self.assertRaises(menu.OrderError):
            menu.create_order(table, {"items": [{"id": other_item.id, "qty": 1}]}, "d2")
        setting = MenuSetting.query.filter_by(user_id=self.owner.id).one()
        setting.ordering_open = False
        db.session.commit()
        with self.assertRaisesRegex(menu.OrderError, "sipariş alınmıyor"):
            menu.create_order(table, {"items": [{"id": latte.id, "qty": 1}]}, "d3")
        # görüntüleme bağlantısında sepet yok
        html = self.guest.get(f"/m/{setting.token}").get_data(as_text=True)
        self.assertIn("masandaki QR", html)
        self.assertNotIn('id="qm-send"', html)
        self.assertNotIn("Başka", html)
        self.assertEqual(self.guest.get("/m/yokboyle").status_code, 404)

    def test_call_waiter(self):
        self._build_menu()
        table = MenuTable.query.filter_by(name="Masa 3").one()
        html = self.guest.get(f"/m/{table.code}").get_data(as_text=True)
        self.assertIn("Garson çağır", html)
        setting = MenuSetting.query.filter_by(user_id=self.owner.id).one()
        self.assertNotIn('id="qm-call-btn"', self.guest.get(f"/m/{setting.token}").get_data(as_text=True))  # masasız bağlantıda yok
        token = self._csrf(self.guest, f"/m/{table.code}")
        call = lambda: self.guest.post(f"/m/{table.code}/garson", headers={"X-CSRF-Token": token})   # noqa: E731
        r = call()
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        status_url = r.get_json()["url"]
        self.assertEqual(self.guest.get(status_url).get_json()["status"], "open")
        self.assertEqual(call().get_json()["url"], status_url)          # açık çağrı varken ikincisi açılmaz
        self.assertEqual(TableCall.query.count(), 1)
        # panelde uyarı ve liste
        calls = self.staff.get("/panel/menu/yeni.json").get_json()["calls"]
        self.assertEqual((calls[0]["table"], calls[0]["text"]), ("Masa 3", "Masa 3 garson çağırıyor"))
        self.assertIn("Garson bekleyen masalar", self.staff.get("/panel/menu").get_data(as_text=True))
        # başka işletme kapatamaz
        other = self.app.test_client()
        self._login(other, "baska@kafe.com")
        tok2 = self._csrf(other, "/panel/menu")
        self.assertEqual(other.post(f"/panel/menu/cagri/{calls[0]['id']}/tamam",
                                    headers={"X-CSRF-Token": tok2, "X-Requested-With": "fetch"}).status_code, 404)
        tok = self._csrf(self.staff, "/panel/menu")
        r = self.staff.post(f"/panel/menu/cagri/{calls[0]['id']}/tamam", headers={"X-CSRF-Token": tok, "X-Requested-With": "fetch"})
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(self.guest.get(status_url).get_json()["status"], "done")
        self.assertEqual(self.staff.get("/panel/menu/yeni.json").get_json()["calls"], [])
        # aynı telefondan hemen yeniden çağrı: kısa bekleme
        r = call()
        self.assertEqual(r.status_code, 400)
        self.assertIn("Az önce", r.get_json()["message"])
        # vazgeç
        TableCall.query.update({"created_at": datetime.utcnow() - timedelta(minutes=1)})
        db.session.commit()
        url2 = call().get_json()["url"]
        self.assertTrue(self.guest.post(url2 + "/iptal", headers={"X-CSRF-Token": token}).get_json()["ok"])
        self.assertEqual(self.guest.get(url2).get_json()["status"], "cancelled")
        # kapatılınca düğme görünmez, çağrı reddedilir
        self._post("/panel/menu/ayarlar", {"action": "calls"}, page="/panel/menu")
        self.assertNotIn('id="qm-call-btn"', self.guest.get(f"/m/{table.code}").get_data(as_text=True))
        TableCall.query.update({"created_at": datetime.utcnow() - timedelta(minutes=1)})
        db.session.commit()
        self.assertEqual(call().status_code, 400)
        self.assertEqual(self.guest.post(f"/m/{setting.token}/garson", headers={"X-CSRF-Token": token}).status_code, 404)

    def test_adisyo_import(self):
        self.staff.get("/panel/menu")
        data = [{"categoryName": "Sıcak İçecekler", "categoryId": 11, "products": [
            {"productName": "Latte", "productId": 501, "productUnits": [
                {"unitName": "Tam", "productUnitId": 9001, "isDefault": True,
                 "prices": [{"price": 110, "orderType": 3, "isActive": True},
                            {"price": 95, "orderType": 1, "isActive": True}]}]},
            {"productName": "Eski ürün", "productId": 502, "productUnits": [
                {"unitName": "Tam", "productUnitId": 9002, "isDefault": True,
                 "prices": [{"price": 50, "orderType": 1, "isActive": False}]}]}]}]
        added, updated, skipped = menu.import_adisyo(self.owner, data)
        self.assertEqual((added, updated, skipped), (1, 0, 1))
        item = MenuItem.query.one()
        self.assertEqual((item.name, item.price, item.adisyo_unit_id), ("Latte", Decimal("95.00"), 9001))   # masa fiyatı
        item.description = "Benim açıklamam"
        db.session.commit()
        data[0]["products"][0]["productUnits"][0]["prices"][1]["price"] = 100
        self.assertEqual(menu.import_adisyo(self.owner, data), (0, 1, 1))
        db.session.expire_all()
        self.assertEqual((item.price, item.description), (Decimal("100.00"), "Benim açıklamam"))
        self.assertEqual(MenuCategory.query.count(), 1)
        # panel düğmesi: bağlantı yoksa uyarır
        r = self._post("/panel/menu/adisyo-aktar", {})
        self.assertEqual(r.status_code, 302)

    def _adisyo(self):
        from models import AdisyoConnection, Integration
        intg = Integration(user_id=self.owner.id, platform="adisyo", is_active=True)
        db.session.add(intg)
        conn = AdisyoConnection(integration=intg, restaurant_name="Pion", consumer="SG")
        conn.api_key, conn.api_secret = "k", "s"
        db.session.add(conn)
        db.session.commit()

    @staticmethod
    def _resp(payload):
        r = mock.Mock(status_code=200)
        r.json.return_value = payload
        return r

    def test_send_order_to_adisyo_table(self):
        self._build_menu()
        self._adisyo()
        latte = MenuItem.query.filter_by(name="Latte").one()
        cake = MenuItem.query.filter_by(name="Cheesecake").one()
        latte.adisyo_unit_id = 9001
        db.session.commit()
        tables = {"status": 100, "data": [{"id": 1, "name": "Salon", "tables": [
            {"id": 101, "name": "MASA 3"}, {"id": 102, "name": "Masa-1"}, {"id": 103, "name": "Bahçe 1"}]}]}
        with mock.patch("requests.request", return_value=self._resp(tables)):
            r = self._post("/panel/menu/adisyo-masalar", {}, page="/panel/menu/masalar")
        self.assertEqual(r.status_code, 302)
        t3 = MenuTable.query.filter_by(name="Masa 3").one()
        self.assertEqual((t3.adisyo_table_id, MenuTable.query.filter_by(name="Masa 1").one().adisyo_table_id), (101, 102))
        self.assertIsNone(MenuTable.query.filter_by(name="Masa 2").one().adisyo_table_id)
        page = self.staff.get("/panel/menu/masalar").get_data(as_text=True)
        self.assertIn("Adisyo: Salon · Bahçe 1", page)
        with mock.patch("requests.request", return_value=self._resp(tables)):
            self._post("/panel/menu/adisyo-masalar", {"action": "create"}, page="/panel/menu/masalar")
        self.assertEqual(MenuTable.query.filter_by(name="Bahçe 1").one().adisyo_table_id, 103)
        # elle eşleştirme: listede olmayan id kabul edilmez
        t2 = MenuTable.query.filter_by(name="Masa 2").one()
        self._post(f"/panel/menu/masa/{t2.id}/adisyo", {"adisyo_table_id": "999"}, page="/panel/menu/masalar")
        self.assertIsNone(db.session.get(MenuTable, t2.id).adisyo_table_id)

        # Adisyo karşılığı olmayan ürün varsa gönderilmez
        o = menu.create_order(t3, {"items": [{"id": latte.id, "qty": 2}, {"id": cake.id, "qty": 1}]}, "d1")
        with mock.patch("requests.request") as call:
            ok, msg = menu.send_to_adisyo(o)
        self.assertFalse(ok)
        self.assertIn("Cheesecake", msg)
        call.assert_not_called()
        self.assertEqual(o.adisyo_state, "error")

        # artık Hazırlanıyor'a basınca yazılmaz; masa hesabı "Ödeme alındı" ile kapanınca tek sipariş yazılır
        TableOrder.query.filter_by(id=o.id).update({"status": "cancelled"})
        db.session.commit()
        self._post("/panel/menu/ayarlar", {"action": "adisyo_send", "value": "accept"}, page="/panel/menu")
        o2 = menu.create_order(t3, {"items": [{"id": latte.id, "qty": 2}], "note": "az köpük"}, "d2")
        tok = self._csrf(self.staff, "/panel/menu")
        with mock.patch("requests.request") as call:
            self.staff.post(f"/panel/menu/siparis/{o2.id}/preparing",
                            headers={"X-CSRF-Token": tok, "X-Requested-With": "fetch"})
        call.assert_not_called()
        o3 = menu.create_order(t3, {"items": [{"id": latte.id, "qty": 1}]}, "d3")
        page = self.staff.get("/panel/menu").get_data(as_text=True)
        self.assertIn("Açık masa hesapları (1)", page)
        self.assertIn("2 sipariş", page)
        self.assertIn("<b>3×</b> Latte", page)
        # Adisyo hata: hesap açık kalır
        with mock.patch("requests.request", return_value=self._resp({"status": 715, "message": "Hatalı"})):
            self._post(f"/panel/menu/hesap/{t3.id}/kapat", {"adisyo": "1"}, page="/panel/menu")
        db.session.expire_all()
        self.assertIsNone(db.session.get(TableOrder, o2.id).paid_at)
        self.assertIn("Adisyo'suz kapat", self.staff.get("/panel/menu").get_data(as_text=True))
        # başarılı: tek SaveOrder, ürünler birleşik, masa sıfırlanır
        with mock.patch("requests.request", return_value=self._resp({"status": 100, "orderId": 55501})) as call:
            self._post(f"/panel/menu/hesap/{t3.id}/kapat", {"adisyo": "1"}, page="/panel/menu")
        self.assertEqual(call.call_count, 1)
        body = call.call_args.kwargs["json"]
        self.assertEqual((body["TableId"], body["OrderTotal"], body["WebOrderId"]), (101, 285.0, f"sg-qr-hesap-{o2.id}"))
        self.assertEqual(body["OrderDetails"], [{"ProductUnitId": 9001, "Quantity": 3, "Name": "Latte", "IsMenu": False}])
        self.assertIn("az köpük", body["OrderNote"])
        db.session.expire_all()
        for oid in (o2.id, o3.id):
            row = db.session.get(TableOrder, oid)
            self.assertEqual((row.adisyo_state, row.adisyo_order_id, row.status), ("sent", "55501", "served"))
            self.assertIsNotNone(row.paid_at)
        self.assertNotIn("Açık masa hesapları", self.staff.get("/panel/menu").get_data(as_text=True))
        # yeni sipariş yeni hesap açar
        o5 = menu.create_order(t3, {"items": [{"id": latte.id, "qty": 1}]}, "d5")
        self.assertIn("1 sipariş", self.staff.get("/panel/menu").get_data(as_text=True))
        # Adisyo'da eşleşmemiş masa: masasız (gel-al) sipariş olarak yazılır
        t2 = db.session.get(MenuTable, t2.id)
        menu.create_order(t2, {"items": [{"id": latte.id, "qty": 1}]}, "d4")
        with mock.patch("requests.request", return_value=self._resp({"status": 100, "orderId": 7})) as call:
            self._post(f"/panel/menu/hesap/{t2.id}/kapat", {"adisyo": "1"}, page="/panel/menu")
        body = call.call_args.kwargs["json"]
        self.assertNotIn("TableId", body)
        self.assertEqual(body["OrderType"], 3)
        self.assertEqual(body["CustomerName"], "Masa 2")
        # Adisyo kapalıyken sadece kapatır
        with mock.patch("requests.request") as call:
            self._post(f"/panel/menu/hesap/{t3.id}/kapat", {"adisyo": "0"}, page="/panel/menu")
        call.assert_not_called()
        db.session.expire_all()
        self.assertIsNotNone(db.session.get(TableOrder, o5.id).paid_at)

if __name__ == "__main__":
    unittest.main()

import copy
import json
import re
import unittest
from unittest import mock

from app import create_app
from extensions import db
from integrations import posentegra as pe
from integrations import yemeksepeti as ys
from models import Integration, Order, User


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False
    TRIAL_DAYS = 0
    ENCRYPTION_KEY = "M0dkZ3VvQ1ZqZ0x2b3pXVmJ6a1FwR3hJb1N5c3h6Zkk="
    POSENTEGRA_API_KEY = "pe-shared-key"


REST_ID = "9b40e297-aaaa-bbbb-cccc-000000000001"

# PosEntegra'nın Yemeksepeti entegrasyon sayfasındaki örnek sipariş (kişisel veriler değiştirildi)
SAMPLE = {
    "createdAt": {"$date": "2026-08-11T06:14:49.043Z"},
    "isConfirm": None,
    "paymentMethodText": {"en": "Online Kredi/Banka Kartı", "tr": "Online Kredi/Banka Kartı"},
    "shortCode": "zi5k-2633-qfpa",
    "courier": None,
    "statusCode": 500,
    "paymentMethod": 0,
    "isScheduled": False,
    "verify": None,
    "cancelNote": "",
    "providerSlug": "ys",
    "posPaymentMethod": "Online Kredi/Banka Kartı",
    "totalPrice": 440,
    "restaurantId": REST_ID,
    "pid": "zi5k-2633-qfpa",
    "totalDiscount": 0,
    "doNotKnock": False,
    "providerOrderId": "zi5k-2633-qfpa",
    "isEcoFriendly": True,
    "callbackUrls": {"orderAcceptedUrl": "https://vendor-api-tr.me.restaurant-partners.com/api/1/pos/orders/x/status"},
    "status": 500,
    "deliveryType": 2,
    "totalDiscountedPrice": 440,
    "client": {
        "deliveryAddress": {"city": "Sakarya", "description": "Papatya sitesi; ÇATAL-BIÇAK GÖNDERMEYİN",
                            "floor": "Giriş kat", "street": "6588. Sokak", "district": "Rasimpaşa Sakarya",
                            "building": "Papatya sitesi", "doorNo": "3", "address": "6588. Sokak No:12 D:3"},
        "name": "Test Müşteri",
        "clientPhoneNumber": "+905000000000",
        "location": {"lat": "40.80", "lon": "30.73"},
    },
    "id": "zi5k-2633-qfpa",
    "restaurant": {"id": REST_ID, "name": "Tostland (Hendek)"},
    "created_at": "2026-08-11T06:14:47.846Z",
    "clientNote": "ÇATAL-BIÇAK GÖNDERMEYİN",
    "is_payment_online": True,
    "cancelReason": None,
    "products": [
        {"name": {"tr": "Ayvalık Tost"}, "priceWithOption": 240, "optionCategories": [], "product": "81237912",
         "totalPrice": 240, "extraIngredients": [], "id": "81237912", "removedIngredients": [],
         "totalPriceWithOption": 240, "price": 240, "count": 1, "note": None},
        {"name": {"tr": "Karışık Patso Sandviç"}, "priceWithOption": 100, "optionCategories": [
            {"name": {"tr": "Sos"}, "options": [{"name": {"tr": "Ketçap"}, "price": 0}]}],
         "product": "75857284", "totalPrice": 200, "extraIngredients": [], "id": "75857284",
         "removedIngredients": [{"name": {"tr": "Turşu"}}], "totalPriceWithOption": 200, "price": 100, "count": 2,
         "note": "Bol soslu"},
    ],
    "providerId": "60cdef4f0000",
    "provider": {"slug": "ys"},
}


def _resp(data, status=200, success=True):
    r = mock.Mock(status_code=status)
    r.json.return_value = {"success": success, "data": data} if success else {"success": False, "message": data}
    return r


class PosEntegraTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        from flask import g
        self.app.before_request(lambda: g.pop("_login_user", None) and None)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        user = User(email="pion@kafe.com", name="Pion Coffee", is_trial=True)
        user.set_password("sifre12345")
        db.session.add(user)
        db.session.flush()
        self.user_id = user.id
        self.intg = Integration(user_id=user.id, platform=ys.PLATFORM, is_active=True, notify_new_order=False,
                                ys_mode="posentegra", pe_restaurant_id=REST_ID)
        db.session.add(self.intg)
        db.session.commit()
        self.client = self.app.test_client()
        self.auth = {"Authorization": "Bearer pe-shared-key"}

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _hook(self, body, headers=None):
        return self.client.post("/webhooks/posentegra", data=json.dumps(body),
                                headers=headers if headers is not None else self.auth, content_type="application/json")

    def _login(self):
        html = self.client.get("/giris").get_data(as_text=True)
        token = re.search(r'name="_csrf_token" value="([^"]+)"', html).group(1)
        self.client.post("/giris", data={"_csrf_token": token, "email": "pion@kafe.com", "password": "sifre12345"})

    def _csrf(self, path):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="_csrf_token" value="([^"]+)"', html).group(1)

    def test_normalize_sample(self):
        n = pe.normalize(SAMPLE)
        f = ys.extract_order_fields(n)
        self.assertEqual((f["external_id"], f["order_number"], f["total_price"], f["status"]),
                         ("zi5k-2633-qfpa", "zi5k-2633-qfpa", 440.0, ys.STATUS_RECEIVED))
        self.assertEqual(f["payment_type"], "Online Kredi/Banka Kartı")
        self.assertEqual(f["customer_note"], "ÇATAL-BIÇAK GÖNDERMEYİN")
        self.assertEqual([(ys.item_name(i), ys.item_quantity(i), ys.item_price(i)) for i in ys.items(n)],
                         [("Ayvalık Tost", 1, 240.0), ("Karışık Patso Sandviç", 2, 200.0)])
        opts = ys.item_options(ys.items(n)[1])
        self.assertEqual([(o["name"], o["header"], o["excluded"]) for o in opts],
                         [("Ketçap", "Sos", False), ("Turşu", "Çıkarılan", True)])
        self.assertIn("Not: Bol soslu", ys.item_details(ys.items(n)[1]))
        self.assertEqual(ys.customer_name(n), "Test Müşteri")
        self.assertIn("6588. Sokak No:12 D:3", ys.address_text(n))
        self.assertNotIn("callbackUrls", n)                       # Delivery Hero aksiyonları tetiklenmesin
        self.assertTrue(pe.is_posentegra(n))
        self.assertEqual(pe.status_from({**SAMPLE, "statusCode": 1600}), ys.STATUS_CANCELLED)
        self.assertEqual(pe.status_from({**SAMPLE, "isConfirm": True}), ys.STATUS_ACCEPTED)

    def test_webhook_auth_create_idempotent_and_cancel(self):
        self.assertEqual(self._hook({"olay": pe.EVENT_CREATED, "veri": SAMPLE}, headers={}).status_code, 401)
        self.assertEqual(self._hook({"olay": pe.EVENT_CREATED, "veri": SAMPLE},
                                    headers={"Authorization": "Bearer yanlis"}).status_code, 401)
        r = self._hook({"olay": pe.EVENT_CREATED, "veri": SAMPLE})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(self._hook({"olay": pe.EVENT_CREATED, "veri": SAMPLE}).status_code, 200)
        orders = Order.query.all()
        self.assertEqual(len(orders), 1)
        self.assertEqual((orders[0].platform, orders[0].status, orders[0].total_price),
                         (ys.PLATFORM, ys.STATUS_RECEIVED, 440.0))
        # tanımsız restoran
        other = copy.deepcopy(SAMPLE)
        other["restaurantId"] = "baska"
        other["restaurant"]["id"] = "baska"
        self.assertEqual(self._hook({"olay": pe.EVENT_CREATED, "veri": other}).status_code, 404)
        # iptal olayı (sadece kimlikler)
        r = self._hook({"olay": pe.EVENT_CANCELLED, "veri": {"id": "wo_1", "providerOrderId": "zi5k-2633-qfpa",
                                                             "restaurantId": REST_ID}})
        self.assertEqual(r.status_code, 200)
        db.session.expire_all()
        self.assertEqual(Order.query.one().status, ys.STATUS_CANCELLED)

    def test_minimal_webhook_fetches_detail_and_retries_on_failure(self):
        minimal = {"olay": pe.EVENT_CREATED, "veri": {"id": "wo_9", "providerOrderId": "zi5k-2633-qfpa",
                                                      "restaurantId": REST_ID}}
        with mock.patch("requests.request", return_value=_resp("çok istek", 429, success=False)), \
                mock.patch("time.sleep"):
            self.assertEqual(self._hook(minimal).status_code, 503)        # PosEntegra tekrar dener
        self.assertEqual(Order.query.count(), 0)
        with mock.patch("requests.request", return_value=_resp(SAMPLE)) as call:
            self.assertEqual(self._hook(minimal).status_code, 200)
        method, url = call.call_args.args
        self.assertEqual((method, url), ("GET", "https://api.v1.fastsiparis.com/web-api/v1/orders/zi5k-2633-qfpa"))
        self.assertEqual(call.call_args.kwargs["headers"]["Authorization"], "Bearer pe-shared-key")
        order = Order.query.one()
        self.assertEqual(json.loads(order.raw_json)["_pe"]["webhookId"], "wo_9")

    def test_panel_actions_and_setup(self):
        self._hook({"olay": pe.EVENT_CREATED, "veri": SAMPLE})
        order = Order.query.one()
        self._login()
        reasons = _resp({"reasons": [{"id": "TOO_BUSY", "name": "Restoran yoğun"}]})
        with mock.patch("requests.request", return_value=reasons):
            page = self.client.get(f"/panel/siparis/{order.id}").get_data(as_text=True)
        self.assertIn("Yemeksepeti · PosEntegra", page)
        self.assertIn("Restoran yoğun", page)
        self.assertIn("Çatal-bıçak", page)
        tok = self._csrf(f"/panel/siparis/{order.id}")
        with mock.patch("requests.request", return_value=_resp({"message": "Verify completed successfully"})) as call:
            self.client.post(f"/panel/siparis/{order.id}/yemeksepeti-aksiyon", data={"_csrf_token": tok, "action": "accept"})
        self.assertTrue(call.call_args.args[1].endswith("/orders/verify/zi5k-2633-qfpa"))
        db.session.expire_all()
        order = db.session.get(Order, order.id)
        self.assertEqual(order.status, ys.STATUS_ACCEPTED)
        with mock.patch("requests.request", return_value=_resp({"orderId": "x", "oldStatus": 500, "newStatus": 600})) as call:
            self.client.post(f"/panel/siparis/{order.id}/yemeksepeti-aksiyon", data={"_csrf_token": tok, "action": "advance"})
        self.assertTrue(call.call_args.args[1].endswith("/orders/change-status/zi5k-2633-qfpa"))
        db.session.expire_all()
        order = db.session.get(Order, order.id)
        self.assertEqual((order.status, json.loads(order.raw_json)["_pe"]["statusCode"]), (ys.STATUS_PREPARED, 600))
        with mock.patch("requests.request", return_value=_resp({"orderId": "x", "status": 1600})) as call:
            self.client.post(f"/panel/siparis/{order.id}/yemeksepeti-aksiyon",
                             data={"_csrf_token": tok, "action": "cancel", "rejection_reason": "TOO_BUSY"})
        self.assertEqual(call.call_args.kwargs["json"], {"reason": "TOO_BUSY"})
        db.session.expire_all()
        self.assertEqual(db.session.get(Order, order.id).status, ys.STATUS_CANCELLED)
        # hata: durum değişmez, mesaj görünür
        self._hook({"olay": pe.EVENT_CREATED, "veri": {**SAMPLE, "providerOrderId": "o2", "pid": "o2", "id": "o2", "shortCode": "o2"}})
        o2 = Order.query.filter_by(external_id="o2").one()
        with mock.patch("requests.request", return_value=_resp("Kayıt bulunamadı", 404, success=False)):
            r = self.client.post(f"/panel/siparis/{o2.id}/yemeksepeti-aksiyon", data={"_csrf_token": tok, "action": "accept"},
                                 follow_redirects=True)
        self.assertIn("gönderilemedi", r.get_data(as_text=True))
        db.session.expire_all()
        self.assertEqual(db.session.get(Order, o2.id).status, ys.STATUS_RECEIVED)
        # kurulum sayfası
        page = self.client.get("/panel/yemeksepeti").get_data(as_text=True)
        self.assertIn("PosEntegra ile bağlan", page)
        self.assertIn("/webhooks/posentegra", page)
        tok = self._csrf("/panel/yemeksepeti")
        self.client.post("/panel/yemeksepeti", data={"_csrf_token": tok, "mode": "posentegra",
                                                    "pe_restaurant_id": "yeni-rest", "pe_api_key": "kendi-anahtar"})
        db.session.expire_all()
        intg = Integration.query.one()
        self.assertEqual((intg.ys_mode, intg.pe_restaurant_id, intg.pe_api_key), ("posentegra", "yeni-rest", "kendi-anahtar"))
        # restoranın kendi anahtarı webhook'ta da geçerli
        other = {**SAMPLE, "restaurantId": "yeni-rest", "providerOrderId": "o3", "pid": "o3", "id": "o3", "shortCode": "o3"}
        self.assertEqual(self._hook({"olay": pe.EVENT_CREATED, "veri": other},
                                    headers={"Authorization": "kendi-anahtar"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()

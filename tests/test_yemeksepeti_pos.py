import base64
import hashlib
import hmac
import json
import time
import unittest

from app import create_app
from extensions import db
from integrations import yemeksepeti as ys
from models import Integration, Order, User


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False
    YEMEKSEPETI_POS_JWT_SECRET = "middleware-test-secret"


def _part(value):
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _jwt(secret, expires=300):
    header = _part({"alg": "HS256", "typ": "JWT"})
    payload = _part({"exp": int(time.time()) + expires})
    signature = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{header}.{payload}.{encoded}"


class YemeksepetiPosTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        user = User(email="ys@example.invalid", name="YS Test", password_hash="unused")
        db.session.add(user)
        db.session.flush()
        self.user_id = user.id
        db.session.add(Integration(
            user_id=user.id,
            platform=ys.PLATFORM,
            ys_store_id="REST-1",
            ys_vendor_id="REST-1",
            is_active=True,
            notify_new_order=False,
        ))
        db.session.commit()
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer " + _jwt(TestConfig.YEMEKSEPETI_POS_JWT_SECRET)}

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_dispatch_is_authenticated_and_idempotent(self):
        payload = {
            "token": "order-token-1",
            "code": "YS-1001",
            "comments": {"customerComment": "Zili calmayin"},
            "createdAt": "2026-09-11T10:00:00Z",
            "customer": {"firstName": "Test", "lastName": "Musteri"},
            "delivery": {"riderPickupTime": None, "address": {"street": "Test Sokak"}},
            "expeditionType": "delivery",
            "payment": {"status": "paid", "type": "paid"},
            "platformRestaurant": {"id": "YS-VENDOR"},
            "price": {"grandTotal": "125.50"},
            "products": [{"name": "Burger", "quantity": "2", "paidPrice": "125.50"}],
            "callbackUrls": {
                "orderAcceptedUrl": "https://integration-middleware.stg.restaurant-partners.com/v2/order/status/order-token-1"
            },
            "test": True,
        }
        first = self.client.post("/webhooks/yemeksepeti/order/REST-1", json=payload, headers=self.headers)
        second = self.client.post("/webhooks/yemeksepeti/order/REST-1", json=payload, headers=self.headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(Order.query.count(), 1)
        self.assertEqual(first.get_json(), second.get_json())
        order = Order.query.one()
        self.assertEqual(order.order_number, "YS-1001")
        self.assertEqual(order.total_price, 125.50)

    def test_dispatch_rejects_invalid_jwt(self):
        response = self.client.post(
            "/webhooks/yemeksepeti/order/REST-1",
            json={"token": "1", "code": "2"},
            headers={"Authorization": "Bearer " + _jwt("wrong-secret")},
        )
        self.assertEqual(response.status_code, 401)

    def test_callback_url_rejects_untrusted_host(self):
        with self.assertRaises(ValueError):
            ys._trusted_callback_url("https://example.com/order", ys.POS_SANDBOX_BASE)

    def test_setup_page_renders(self):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(self.user_id)
            session["_fresh"] = True
        response = self.client.get("/panel/yemeksepeti")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Remote ID", response.data)




class YemeksepetiPluginRootTest(unittest.TestCase):
    def test_base_url_returns_200(self):
        app = create_app(TestConfig, start_scheduler=False)
        with app.app_context():
            db.create_all()
            client = app.test_client()
            for path in ("/webhooks/yemeksepeti", "/webhooks/yemeksepeti/"):
                r = client.get(path)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.get_json()["status"], "ok")
            self.assertEqual(client.head("/webhooks/yemeksepeti").status_code, 200)
            self.assertEqual(client.post("/webhooks/yemeksepeti").status_code, 200)
            db.drop_all()


class YemeksepetiPosHelpersTest(unittest.TestCase):
    def test_conflict_and_expiry(self):
        from unittest import mock
        ok_login = mock.Mock(status_code=200)
        ok_login.json.return_value = {"access_token": "t", "expires_in": 1800}
        ok_login.raise_for_status = lambda: None
        conflict = mock.Mock(status_code=409, content=b"{}")
        conflict.json.return_value = {"currentState": "WAITING_FOR_ACKNOWLEDGEMENT"}
        ys._POS_TOKEN_CACHE.clear()
        with mock.patch("requests.post", return_value=ok_login), mock.patch("requests.request", return_value=conflict):
            with self.assertRaises(ys.PosConflict) as ctx:
                ys.send_pos_callback("POST", "https://integration-middleware.stg.restaurant-partners.com/v2/order/status/x",
                                     {}, "u", "p", "sandbox")
        self.assertTrue(ctx.exception.retryable)
        self.assertFalse(ys.PosConflict("CANCELLED").retryable)
        ok = mock.Mock(status_code=200, content=b'{"message": "ok"}')
        ok.json.return_value = {"message": "ok"}
        ok.raise_for_status = lambda: None
        with mock.patch("requests.post", return_value=ok_login), mock.patch("requests.request", return_value=ok):
            self.assertEqual(ys.send_pos_callback("POST", "https://integration-middleware.stg.restaurant-partners.com/v2/x",
                                                  {}, "u", "p", "sandbox"), {"message": "ok"})
        self.assertEqual(ys.expiry_text({"expiryDate": "2026-11-12T14:15:00.000Z"}), "17:15")
        self.assertEqual(ys.expiry_text({}), "")


if __name__ == "__main__":
    unittest.main()

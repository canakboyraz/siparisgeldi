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


if __name__ == "__main__":
    unittest.main()

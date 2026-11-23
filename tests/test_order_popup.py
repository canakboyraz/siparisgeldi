import unittest

from app import create_app
from extensions import db
from models import Order, User


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False


class OrderPopupTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.context = self.app.app_context()
        self.context.push()
        user = User(email="pop@example.invalid", name="Pop", password_hash="x")
        db.session.add(user)
        db.session.flush()
        self.uid = user.id
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def add(self, ext, status):
        o = Order(user_id=self.uid, platform="trendyolgo", external_id=ext, status=status, total_price=100)
        db.session.add(o)
        db.session.commit()
        return o

    def poll(self, **params):
        return self.client.get("/panel/aktif-siparisler/yeni-kontrol", query_string=params).get_json()

    def test_only_unaccepted_orders_pop_up(self):
        self.add("a", "Created")
        self.add("b", "Picking")      # Trendyol arayüzünden kabul edilmiş
        self.add("c", "Prepared")
        data = self.poll(since_id=0)
        self.assertEqual([o["order_number"] for o in data["orders"]], ["a"])

    def test_unknown_since_id_does_not_replay_history(self):
        self.add("a", "Created")
        data = self.poll(since_id=-1)
        self.assertEqual(data["orders"], [])
        self.assertGreater(data["latest_id"], 0)

    def test_shown_order_accepted_elsewhere_reports_not_pending(self):
        o = self.add("a", "Created")
        o.status = "Picking"
        db.session.commit()
        data = self.poll(since_id=o.id, watch_id=o.id)
        self.assertIs(data["watch_pending"], False)


if __name__ == "__main__":
    unittest.main()

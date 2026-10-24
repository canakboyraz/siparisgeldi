import json
import re
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from app import create_app
from extensions import db
from integrations import adisyo
import adisyo_reports
from models import AdisyoConnection, AdisyoReport, Integration, User


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False
    TRIAL_DAYS = 0
    ENCRYPTION_KEY = "M0dkZ3VvQ1ZqZ0x2b3pXVmJ6a1FwR3hJb1N5c3h6Zkk="


def order(oid, stamp, total, status="Kapandı"):
    return {"id": oid, "insertDate": stamp, "status": status, "statusId": 7, "currency": "TRY",
            "orderTotal": total, "discountAmount": 0, "taxAmount": 0,
            "products": [{"productId": 1, "productName": "Lahmacun", "quantity": 1, "totalAmount": total}],
            "payments": [{"paymentName": "Nakit", "amount": total, "currency": "TRY"}]}


class AdisyoLiveTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()
        u = User(name="Usta", email="usta@restoran.com")
        u.set_password("sifre12345")
        db.session.add(u)
        db.session.commit()
        self.user = u
        intg = Integration(user_id=u.id, platform="adisyo", is_active=True, notify_daily_report=True)
        db.session.add(intg)
        self.conn = AdisyoConnection(integration=intg, restaurant_name="Pion", consumer="SG")
        self.conn.api_key, self.conn.api_secret = "k", "s"
        db.session.add(self.conn)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_hourly_summary(self):
        day = date(2026, 10, 24)
        rows = [adisyo.normalize(order(1, "2026-10-24T12:10:00", 100), day),
                adisyo.normalize(order(2, "2026-10-24T12:50:00", 50), day),
                adisyo.normalize(order(3, "2026-10-24T19:05:00", 80), day),
                adisyo.normalize(order(4, "2026-10-24T19:30:00", 40, status="İptal"), day)]
        summary = adisyo.summarize(rows)
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["hours"], [{"hour": 12, "count": 2, "amount": "150.00"},
                                            {"hour": 19, "count": 1, "amount": "80.00"}])

    def _schedule_at(self, local, utc):
        with patch("adisyo_reports.datetime") as fake:
            fake.utcnow.return_value = utc
            fake.combine = datetime.combine
            fake.min = datetime.min
            adisyo_reports.schedule(self.conn, adisyo.TURKEY_TZ.localize(local))

    def test_schedule_live_and_final(self):
        today = date(2026, 10, 24)
        self._schedule_at(datetime(2026, 10, 24, 15, 0), datetime(2026, 10, 24, 12, 0))
        live = AdisyoReport.query.filter_by(day=today).one()
        self.assertEqual(live.state, "queued")
        self.assertFalse(live.send_requested)
        # Ready with a summary: not refreshed within 15 minutes, refreshed after; summary kept meanwhile.
        live.state, live.summary_json = "ready", json.dumps({"count": 1})
        db.session.commit()
        self._schedule_at(datetime(2026, 10, 24, 15, 10), datetime(2026, 10, 24, 12, 10))
        self.assertEqual(live.state, "ready")
        self._schedule_at(datetime(2026, 10, 24, 15, 20), datetime(2026, 10, 24, 12, 20))
        self.assertEqual(live.state, "queued")
        self.assertIsNotNone(live.summary_json)
        # Next night: yesterday's live report is not final, so it is re-read once and sent.
        live.state = "ready"
        db.session.commit()
        self.assertFalse(adisyo_reports.is_final(live))
        self._schedule_at(datetime(2026, 10, 25, 0, 20), datetime(2026, 10, 24, 21, 20))
        self.assertEqual(live.state, "queued")
        self.assertTrue(live.send_requested)
        self.assertTrue(adisyo_reports.is_final(live))
        live.state = "ready"
        db.session.commit()
        self._schedule_at(datetime(2026, 10, 25, 1, 0), datetime(2026, 10, 24, 22, 0))
        self.assertEqual(live.state, "ready")  # not re-read again

    def test_analytics_uses_real_hours(self):
        from routes.dashboard import _analytics_adisyo_orders, _build_analytics_summary
        day = date(2026, 10, 24)
        db.session.add(AdisyoReport(connection_id=self.conn.id, day=day, state="queued",
                                    summary_json=json.dumps({"count": 3, "cancelled": 1, "amount": "230.00",
                                                             "hours": [{"hour": 12, "count": 2, "amount": "150.00"},
                                                                       {"hour": 19, "count": 1, "amount": "80.00"}]})))
        db.session.commit()
        orders = _analytics_adisyo_orders(self.user.id, day, day)
        self.assertEqual(len(orders), 3)
        summary = _build_analytics_summary(orders, day, day)
        self.assertEqual(summary["best_hour"]["hour"], 12)
        self.assertEqual(summary["hour_rows"][19]["count"], 1)

    def test_panel_shows_hours(self):
        db.session.add(AdisyoReport(connection_id=self.conn.id, day=date.today(), state="ready",
                                    summary_json=json.dumps(adisyo.summarize([
                                        adisyo.normalize(order(1, f"{date.today()}T13:15:00", 90), date.today())]))))
        db.session.commit()
        html = self.client.get("/giris").get_data(as_text=True)
        token = re.search(r'name="_csrf_token" value="([^"]+)"', html).group(1)
        self.client.post("/giris", data={"_csrf_token": token, "email": "usta@restoran.com", "password": "sifre12345"})
        page = self.client.get("/panel/adisyo").get_data(as_text=True)
        self.assertIn("Saatlik satış", page)
        self.assertIn("13:00", page)


if __name__ == "__main__":
    unittest.main()

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

    def test_request_today_has_end_and_error_text(self):
        from unittest.mock import MagicMock
        self.conn.api_key = "sirr-123456"
        resp = MagicMock(status_code=400)
        resp.json.return_value = {"message": "endDate gerekli sirr-123456"}
        with self.app.test_request_context(), patch("integrations.adisyo.requests.get", return_value=resp) as get:
            with self.assertRaises(adisyo.AdisyoError) as err:
                adisyo.completed_page(self.conn, datetime.now(adisyo.TURKEY_TZ).date(), 1)
            self.assertIn("endDate", get.call_args.kwargs["params"])
            self.assertIn("endDate gerekli ***", str(err.exception))
            with self.assertRaises(adisyo.AdisyoError):
                adisyo.completed_page(self.conn, date(2026, 1, 5), 1)
            self.assertNotIn("endDate", get.call_args.kwargs["params"])

    def test_orders_are_stored_and_used_everywhere(self):
        from models import Order
        from routes.dashboard import _build_analytics_summary, _cost_product_lines, _parse_raw_json
        day = date(2026, 10, 24)
        rows = [adisyo.normalize(order(1, "2026-10-24T12:10:00", 100), day),
                adisyo.normalize(order(2, "2026-10-24T19:05:00", 80), day),
                adisyo.normalize(order(3, "2026-10-24T19:30:00", 40, status="İptal"), day)]
        adisyo_reports.save_orders(self.conn, rows)
        adisyo_reports.save_orders(self.conn, rows)  # tekrar okuma kopya üretmez
        db.session.commit()
        orders = Order.query.filter_by(platform="adisyo").order_by(Order.created_at).all()
        self.assertEqual(len(orders), 3)
        self.assertEqual(orders[0].created_at, datetime(2026, 10, 24, 9, 10))  # 12:10 yerel = 09:10 UTC
        self.assertEqual([o.status for o in orders], ["Completed", "Completed", "Cancelled"])
        summary = _build_analytics_summary(orders, day, day)
        self.assertEqual(summary["best_hour"]["hour"] in (12, 19), True)
        self.assertEqual(summary["hour_rows"][19]["count"], 1)
        lines = _cost_product_lines("adisyo", _parse_raw_json(orders[0].raw_json))
        self.assertEqual(lines, [{"key": "lahmacun", "name": "Lahmacun", "quantity": 1.0, "revenue": 100.0}])

    def test_process_page_stores_orders_and_backfills_old(self):
        from models import Order
        self.conn.integration.notify_daily_report = False
        old = AdisyoReport(connection_id=self.conn.id, day=date(2026, 10, 20), state="ready",
                           summary_json=json.dumps({"count": 1}))
        db.session.add(old)
        db.session.commit()
        self._schedule_at(datetime(2026, 10, 24, 15, 0), datetime(2026, 10, 24, 12, 0))
        self.assertEqual(old.state, "queued")  # eski rapor bir kez yeniden okunur
        with patch("integrations.adisyo.completed_page",
                   return_value=([order(9, "2026-10-20T13:00:00", 70)], 1)):
            adisyo_reports.process_page(self.conn.id)
        self.assertEqual(old.state, "ready")
        self.assertEqual(Order.query.filter_by(platform="adisyo", external_id="9").count(), 1)

    def test_panel_shows_hours(self):
        db.session.add(AdisyoReport(connection_id=self.conn.id, day=date.today(), state="ready",
                                    summary_json=json.dumps(adisyo.summarize([
                                        adisyo.normalize(order(1, f"{date.today()}T13:15:00", 90), date.today())]))))
        db.session.commit()
        html = self.client.get("/giris").get_data(as_text=True)
        token = re.search(r'name="_csrf_token" value="([^"]+)"', html).group(1)
        self.client.post("/giris", data={"_csrf_token": token, "email": "usta@restoran.com", "password": "sifre12345"})
        from models import Order
        db.session.add(Order(user_id=self.user.id, platform="adisyo", external_id="z", status="Completed",
                             total_price=10, created_at=datetime(2026, 10, 24, 10, 5)))
        db.session.commit()
        self.assertIn("24.10 13:05", self.client.get("/panel/siparisler").get_data(as_text=True))
        page = self.client.get("/panel/adisyo").get_data(as_text=True)
        self.assertIn("Saatlik satış", page)
        self.assertIn("13:00", page)


if __name__ == "__main__":
    unittest.main()

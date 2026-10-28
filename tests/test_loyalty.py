import re
import unittest
from datetime import datetime, timedelta

from app import create_app
from extensions import db
import loyalty
from models import LoyaltyCustomer, LoyaltyProgram, LoyaltyRequest, User


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False
    TRIAL_DAYS = 0


class LoyaltyTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        from flask import g
        # Testte app bağlamı tüm istemcilerde paylaşılıyor; her istekte giriş yapan kullanıcıyı yeniden okut.
        self.app.before_request(lambda: g.pop("_login_user", None) and None)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.owner = self._user("pion@kafe.com", "Pion Coffee Shop")
        self.other = self._user("baska@kafe.com", "Başka Kafe")
        self.staff = self.app.test_client()
        self._login(self.staff, "pion@kafe.com")
        self.phone = self.app.test_client()   # müşterinin telefonu

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

    def _start_program(self):
        token = self._csrf(self.staff, "/panel/sadakat")
        r = self.staff.post("/panel/sadakat", data={"_csrf_token": token, "name": "Pion Coffee Shop",
                                                    "reward": "1 kahve bedava", "stamps_required": "6",
                                                    "welcome_stamps": "2", "stamps_per_visit": "1",
                                                    "cooldown_minutes": "30"})
        self.assertEqual(r.status_code, 302)
        return LoyaltyProgram.query.filter_by(user_id=self.owner.id).one()

    def _join(self, program, name="Ayşe", phone="0532 123 45 67"):
        token = self._csrf(self.phone, f"/k/{program.token}")
        return self.phone.post(f"/k/{program.token}", data={"_csrf_token": token, "name": name,
                                                            "phone": phone, "consent": "1"})

    def _decide(self, req_id, action, client=None):
        client = client or self.staff
        token = self._csrf(client, "/panel/sadakat")
        return client.post(f"/panel/sadakat/istek/{req_id}/{action}",
                           headers={"X-CSRF-Token": token, "X-Requested-With": "fetch"})

    def test_phone_normalization(self):
        self.assertEqual(loyalty.normalize_phone("0532 123 45 67"), "5321234567")
        self.assertEqual(loyalty.normalize_phone("+90 (532) 123-4567"), "5321234567")
        self.assertIsNone(loyalty.normalize_phone("212 123 45 67"))
        self.assertIsNone(loyalty.normalize_phone("123"))

    def test_full_flow_welcome_visit_cooldown_reward(self):
        program = self._start_program()
        page = self.phone.get(f"/k/{program.token}").get_data(as_text=True)
        self.assertIn("Kartımı aç", page)
        self.assertIn("2 damga", page)

        r = self._join(program)
        self.assertEqual(r.status_code, 302)
        self.assertIn(f"sg_kart_{program.id}", r.headers.get("Set-Cookie", ""))
        customer = LoyaltyCustomer.query.one()
        self.assertEqual(customer.phone, "5321234567")
        req = LoyaltyRequest.query.one()
        self.assertEqual((req.kind, req.stamps, req.status), ("welcome", 2, "pending"))

        card = self.phone.get(f"/k/{program.token}/kart").get_data(as_text=True)
        self.assertIn("Kasada onay bekleniyor", card)
        self.assertIn(req.code, card)

        pending = self.staff.get("/panel/sadakat/bekleyen").get_json()["items"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["name"], "Ayşe")
        self.assertEqual(pending[0]["phone"], "0532 *** ** 67")
        self.assertIn("loyalty-alert", self.staff.get("/panel/aktif-siparisler").get_data(as_text=True))

        self.assertTrue(self._decide(req.id, "onay").get_json()["ok"])
        db.session.expire_all()
        self.assertEqual(customer.stamps, 2)
        status = self.phone.get(f"/k/{program.token}/durum").get_json()
        self.assertEqual((status["stamps"], status["pending"], status["last_status"]), (2, False, "approved"))

        # Bekleme süresinde tekrar okutmak yeni istek oluşturmaz.
        self.phone.get(f"/k/{program.token}")
        self.assertEqual(LoyaltyRequest.query.count(), 1)
        self.assertIn("dk sonra", self.phone.get(f"/k/{program.token}/kart").get_data(as_text=True))

        # Süre dolunca her okutma 1 damga isteği açar.
        for _ in range(4):
            customer.last_visit_at = datetime.utcnow() - timedelta(minutes=31)
            db.session.commit()
            self.phone.get(f"/k/{program.token}")
            self.phone.get(f"/k/{program.token}")   # çift okutma aynı isteği kullanır
            visit = LoyaltyRequest.query.filter_by(status="pending").one()
            self.assertEqual((visit.kind, visit.stamps), ("visit", 1))
            self._decide(visit.id, "onay")
        db.session.expire_all()
        self.assertEqual(customer.stamps, 6)
        self.assertTrue(self.phone.get(f"/k/{program.token}/durum").get_json()["reward_ready"])

        token = self._csrf(self.staff, "/panel/sadakat")
        r = self.staff.post(f"/panel/sadakat/musteri/{customer.id}/odul",
                            headers={"X-CSRF-Token": token, "X-Requested-With": "fetch"})
        self.assertEqual(r.get_json(), {"ok": True, "current": 0})
        db.session.expire_all()
        self.assertEqual((customer.stamps, customer.rewards_redeemed, customer.lifetime_stamps), (0, 1, 6))

    def test_reject_and_returning_phone_gets_no_welcome(self):
        program = self._start_program()
        self._join(program)
        req = LoyaltyRequest.query.one()
        self._decide(req.id, "red")
        db.session.expire_all()
        self.assertEqual(LoyaltyCustomer.query.one().stamps, 0)
        # Aynı numara başka cihazdan katılırsa yeni kart açılmaz, hoş geldin damgası verilmez.
        self.phone = self.app.test_client()
        self._join(program, name="Ayşe Y.", phone="05321234567")
        self.assertEqual(LoyaltyCustomer.query.count(), 1)
        latest = LoyaltyRequest.query.order_by(LoyaltyRequest.id.desc()).first()
        self.assertEqual((latest.kind, latest.stamps), ("visit", 1))

    def test_validation_and_other_merchant_cannot_approve(self):
        program = self._start_program()
        token = self._csrf(self.phone, f"/k/{program.token}")
        r = self.phone.post(f"/k/{program.token}", data={"_csrf_token": token, "name": "A",
                                                         "phone": "123", "consent": "1"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(LoyaltyCustomer.query.count(), 0)
        self._join(program)
        req = LoyaltyRequest.query.one()
        intruder = self.app.test_client()
        self._login(intruder, "baska@kafe.com")
        self.assertEqual(self._decide(req.id, "onay", intruder).status_code, 404)
        self.assertEqual(LoyaltyRequest.query.one().status, "pending")

    def test_pending_never_expires_and_history_screen(self):
        program = self._start_program()
        self._join(program)
        req = LoyaltyRequest.query.one()
        req.created_at = datetime.utcnow() - timedelta(hours=5)
        db.session.commit()
        self.phone.get(f"/k/{program.token}")
        self.assertEqual(self.staff.get("/panel/sadakat/bekleyen").get_json()["items"][0]["id"], req.id)
        self.assertEqual(LoyaltyRequest.query.one().status, "pending")
        page = self.staff.get("/panel/sadakat/hareketler?durum=bekleyen").get_data(as_text=True)
        self.assertIn("Bekliyor", page)
        self.assertIn("Ayşe", page)
        token = self._csrf(self.staff, "/panel/sadakat/hareketler")
        r = self.staff.post(f"/panel/sadakat/istek/{req.id}/red",
                            data={"_csrf_token": token, "next": "/panel/sadakat/hareketler?durum=red"})
        self.assertTrue(r.headers["Location"].endswith("/panel/sadakat/hareketler?durum=red"))
        page = self.staff.get("/panel/sadakat/hareketler?durum=red").get_data(as_text=True)
        self.assertIn("Reddedildi", page)
        self.assertIn("Reddedilen <b>1</b>", page)
        r = self.staff.post(f"/panel/sadakat/istek/{req.id}/onay",
                            data={"_csrf_token": token, "next": "//kotu.site"})
        self.assertTrue(r.headers["Location"].endswith("/panel/sadakat"))

    def test_personal_link_shows_card_without_request(self):
        program = self._start_program()
        r = self._join(program)
        self.assertIn("/kartim/", r.headers["Location"])
        link = r.headers["Location"]
        req = LoyaltyRequest.query.one()
        self._decide(req.id, "onay")
        # Çerezi tutmayan tarayıcı (ör. kod okuyucu içi): kişisel link yine kartı gösterir, istek açmaz.
        fresh = self.app.test_client()
        page = fresh.get(link).get_data(as_text=True)
        self.assertIn("2</b>/6 damga", page)
        self.assertIn("Kartını telefonuna kaydet", page)
        self.assertIn("manifest.webmanifest", page)
        customer = LoyaltyCustomer.query.one()
        customer.last_visit_at = datetime.utcnow() - timedelta(hours=2)
        db.session.commit()
        fresh.get(link)
        self.assertEqual(LoyaltyRequest.query.count(), 1)
        key = link.rsplit("/", 1)[1]
        status = self.app.test_client().get(f"/k/{program.token}/durum?a={key}").get_json()
        self.assertEqual(status["stamps"], 2)
        manifest = fresh.get(link + "/manifest.webmanifest").get_json()
        self.assertTrue(manifest["start_url"].endswith(key))
        self.assertEqual(self.app.test_client().get(f"/k/{program.token}/kartim/sahte").status_code, 302)
        # Link sonrası çerez yazıldı: aynı tarayıcıda QR okutmak damga ister.
        fresh.get(f"/k/{program.token}")
        self.assertEqual(LoyaltyRequest.query.filter_by(status="pending").count(), 1)

    def test_returning_customer_needs_only_phone(self):
        program = self._start_program()
        self._join(program)
        self._decide(LoyaltyRequest.query.one().id, "onay")
        customer = LoyaltyCustomer.query.one()
        customer.last_visit_at = datetime.utcnow() - timedelta(hours=1)
        db.session.commit()
        self.phone = self.app.test_client()   # tanımayan tarayıcı
        token = self._csrf(self.phone, f"/k/{program.token}")
        r = self.phone.post(f"/k/{program.token}", data={"_csrf_token": token, "phone": "0532 123 45 67"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(LoyaltyCustomer.query.count(), 1)
        self.assertEqual(LoyaltyRequest.query.order_by(LoyaltyRequest.id.desc()).first().kind, "visit")
        r = self.phone.post(f"/k/{program.token}", data={"_csrf_token": token, "phone": "0555 000 00 00"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("adını da yaz", r.get_data(as_text=True))

    def test_panel_pages_and_closed_program(self):
        self.assertIn("Damga kartını başlat", self.staff.get("/panel/sadakat").get_data(as_text=True))
        program = self._start_program()
        self._join(program)
        page = self.staff.get("/panel/sadakat").get_data(as_text=True)
        self.assertIn(f"/k/{program.token}", page)
        self.assertIn("Onay bekleyen (1)", page)
        self.assertIn("Ayşe", page)
        self.assertIn("qrcode", self.staff.get("/panel/sadakat/afis").get_data(as_text=True))
        program.is_active = False
        db.session.commit()
        self.assertIn("şu an kapalı", self.app.test_client().get(f"/k/{program.token}").get_data(as_text=True))
        self.assertEqual(self.app.test_client().get("/k/yokboyle").status_code, 404)


if __name__ == "__main__":
    unittest.main()

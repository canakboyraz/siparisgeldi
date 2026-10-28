import base64
import hashlib
import io
import json
import re
import unittest
import zipfile
from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID

from app import create_app
from extensions import db
import wallet
from models import LoyaltyCustomer, LoyaltyProgram, LoyaltyRequest, User, WalletRegistration


def _self_signed(cn):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(datetime.utcnow() - timedelta(days=1))
            .not_valid_after(datetime.utcnow() + timedelta(days=30)).sign(key, hashes.SHA256()))
    return cert, key


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False
    TRIAL_DAYS = 0


class WalletTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cert, key = _self_signed("Pass Type ID: pass.test")
        wwdr, _ = _self_signed("Apple WWDR test")
        cls.cert = cert
        cls.env = {
            "APPLE_TEAM_ID": "ABCDE12345",
            "APPLE_PASS_TYPE_ID": "pass.net.siparisgeldi.damga",
            # Railway'e girilecek biçim: DER sertifika ve PEM anahtarın base64'ü
            "APPLE_PASS_CERT": base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode(),
            "APPLE_PASS_KEY": base64.b64encode(key.private_bytes(serialization.Encoding.PEM,
                                                                  serialization.PrivateFormat.TraditionalOpenSSL,
                                                                  serialization.NoEncryption())).decode(),
            "APPLE_WWDR_CERT": wwdr.public_bytes(serialization.Encoding.PEM).decode(),
        }

    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        from flask import g
        self.app.before_request(lambda: g.pop("_login_user", None) and None)
        self.app.config.update(self.env)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.owner = self._user("pion@kafe.com", "Pion")
        self._user("baska@kafe.com", "Başka")
        self.staff = self.app.test_client()
        self._login(self.staff, "pion@kafe.com")
        self.program = LoyaltyProgram(user_id=self.owner.id, token="pionTEST1", name="Pion Coffee Shop")
        db.session.add(self.program)
        db.session.commit()
        self.customer = LoyaltyCustomer(program_id=self.program.id, name="Ayşe", phone="5321234567", stamps=4)
        db.session.add(self.customer)
        db.session.commit()
        with self.app.test_request_context():
            from routes.loyalty import card_key
            self.key = card_key(self.program, self.customer)
        self.link = f"/k/{self.program.token}/kartim/{self.key}"
        self.serial = wallet.serial_for(self.customer)
        self.auth = {"Authorization": f"ApplePass {wallet.auth_token(self.serial)}"}

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

    def _scan(self, client=None, **payload):
        client = client or self.staff
        token = self._csrf(client, "/panel/sadakat")
        return client.post("/panel/sadakat/okut", json=payload,
                           headers={"X-CSRF-Token": token, "X-Requested-With": "fetch"})

    def test_pkpass_is_signed_and_complete(self):
        r = self.app.test_client().get(self.link + "/cuzdan.pkpass")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/vnd.apple.pkpass")
        z = zipfile.ZipFile(io.BytesIO(r.data))
        names = set(z.namelist())
        for need in ("pass.json", "manifest.json", "signature", "icon.png", "icon@2x.png", "logo.png", "strip@2x.png"):
            self.assertIn(need, names)
        manifest = json.loads(z.read("manifest.json"))
        for name, digest in manifest.items():
            self.assertEqual(hashlib.sha1(z.read(name)).hexdigest(), digest)
        self.assertEqual(set(manifest), names - {"manifest.json", "signature"})
        certs = pkcs7.load_der_pkcs7_certificates(z.read("signature"))
        self.assertEqual(len(certs), 2)   # imzalayan + WWDR
        data = json.loads(z.read("pass.json"))
        self.assertEqual(data["serialNumber"], self.serial)
        self.assertEqual(data["teamIdentifier"], "ABCDE12345")
        self.assertEqual(data["storeCard"]["headerFields"][0]["value"], "4/6")
        self.assertEqual(data["storeCard"]["secondaryFields"][1]["value"], "2 damga")
        self.assertTrue(data["barcodes"][0]["message"].endswith(self.link))
        self.assertTrue(data["webServiceURL"].endswith("/wallet"))
        from PIL import Image
        self.assertEqual(Image.open(io.BytesIO(z.read("strip@2x.png"))).size, (750, 246))
        self.assertEqual(self.app.test_client().get(f"/k/{self.program.token}/kartim/sahte/cuzdan.pkpass").status_code, 404)

    def test_card_page_shows_wallet_button_only_when_configured(self):
        self.assertIn("Apple Cüzdan'a Ekle", self.app.test_client().get(self.link).get_data(as_text=True))
        self.app.config["APPLE_PASS_KEY"] = ""
        self.assertNotIn("Apple Cüzdan'a Ekle", self.app.test_client().get(self.link).get_data(as_text=True))

    def test_passkit_web_service(self):
        c = self.app.test_client()
        base = f"/wallet/v1/devices/dev1/registrations/pass.net.siparisgeldi.damga"
        self.assertEqual(c.post(f"{base}/{self.serial}", json={"pushToken": "abc"},
                                headers={"Authorization": "ApplePass yanlis"}).status_code, 401)
        self.assertEqual(c.post(f"{base}/{self.serial}", json={"pushToken": "abc"}, headers=self.auth).status_code, 201)
        self.assertEqual(c.post(f"{base}/{self.serial}", json={"pushToken": "abc2"}, headers=self.auth).status_code, 200)
        self.assertEqual(WalletRegistration.query.one().push_token, "abc2")
        r = c.get(base)
        self.assertEqual(r.get_json()["serialNumbers"], [self.serial])
        since = r.get_json()["lastUpdated"]
        self.assertEqual(c.get(f"{base}?passesUpdatedSince={since}").status_code, 204)
        p = c.get(f"/wallet/v1/passes/pass.net.siparisgeldi.damga/{self.serial}", headers=self.auth)
        self.assertEqual(p.status_code, 200)
        later = {"If-Modified-Since": "Sun, 01 Jan 2040 00:00:00 GMT", **self.auth}
        self.assertEqual(c.get(f"/wallet/v1/passes/pass.net.siparisgeldi.damga/{self.serial}", headers=later).status_code, 304)
        self.assertEqual(c.get(f"/wallet/v1/passes/pass.net.siparisgeldi.damga/{self.serial}").status_code, 401)
        self.assertEqual(c.post("/wallet/v1/log", json={"logs": ["test"]}).status_code, 200)
        # Damga değişince kart "güncellendi" listesine geri girer.
        self._scan(code="https://siparisgeldi.net" + self.link)
        db.session.expire_all()
        r = c.get(f"{base}?passesUpdatedSince={int(since) - 1}")
        self.assertEqual(r.get_json()["serialNumbers"], [self.serial])
        self.assertEqual(c.delete(f"{base}/{self.serial}", headers=self.auth).status_code, 200)
        self.assertEqual(WalletRegistration.query.count(), 0)

    def test_cashier_scan(self):
        page = self.staff.get("/panel/sadakat/okut")
        self.assertEqual(page.status_code, 200)
        self.assertIn("camera=(self)", page.headers["Permissions-Policy"])
        self.assertIn("camera=()", self.staff.get("/panel/sadakat").headers["Permissions-Policy"])
        r = self._scan(code="https://siparisgeldi.net" + self.link).get_json()
        self.assertEqual((r["ok"], r["added"], r["current"]), (True, 1, 5))
        r = self._scan(code="https://siparisgeldi.net" + self.link).get_json()
        self.assertEqual(r["status"], "cooldown")
        self.assertGreater(r["cooldown"], 0)
        r = self._scan(code="https://siparisgeldi.net" + self.link, force=True).get_json()
        self.assertEqual((r["ok"], r["current"], r["reward_ready"]), (True, 6, True))
        self.assertEqual(LoyaltyRequest.query.filter_by(status="approved").count(), 2)
        # Bekleyen isteği varsa kasada okutmak onu onaylar (çift damga olmaz).
        self.customer.last_visit_at = datetime.utcnow() - timedelta(hours=2)
        db.session.add(LoyaltyRequest(program_id=self.program.id, customer_id=self.customer.id, kind="visit",
                                      stamps=1, code="123"))
        db.session.commit()
        r = self._scan(phone="0532 123 45 67").get_json()
        self.assertEqual((r["ok"], r["current"]), (True, 7))
        self.assertEqual(LoyaltyRequest.query.filter_by(status="pending").count(), 0)
        self.assertEqual(self._scan(phone="0555 000 00 00").status_code, 404)
        self.assertEqual(self._scan(code="https://siparisgeldi.net/k/baskaTOKEN/kartim/" + self.key).status_code, 404)
        other = self.app.test_client()
        self._login(other, "baska@kafe.com")
        token = self._csrf(other, "/panel/sadakat")
        r = other.post("/panel/sadakat/okut", json={"code": self.link},
                       headers={"X-CSRF-Token": token, "X-Requested-With": "fetch"})
        self.assertEqual(r.status_code, 404)

    def test_images(self):
        from PIL import Image
        for required, shown in ((6, 0), (6, 6), (12, 5)):
            img = Image.open(io.BytesIO(wallet.strip_png(required, shown, 375, 123)))
            self.assertEqual(img.size, (375, 123))
        self.assertEqual(Image.open(io.BytesIO(wallet.icon_png(87))).size, (87, 87))


if __name__ == "__main__":
    unittest.main()

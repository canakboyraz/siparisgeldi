"""Apple Cüzdan (Wallet) damga kartı.

- .pkpass üretimi: pass.json + görseller + manifest.json + PKCS#7 imza (Pass Type ID sertifikası).
- PassKit web servisi (routes/wallet.py): iPhone kartı kaydeder, damga değişince güncel kartı çeker.
- APNs bildirimi: damga onaylanınca kayıtlı iPhone'lara "kartın güncellendi" sinyali.

Ortam değişkenleri:
  APPLE_TEAM_ID        10 haneli takım kodu
  APPLE_PASS_TYPE_ID   pass.net.siparisgeldi.damga
  APPLE_PASS_CERT      pass.cer (DER) ya da PEM içeriğinin base64'ü
  APPLE_PASS_KEY       pass.key (PEM, şifresiz) içeriğinin base64'ü
  APPLE_WWDR_CERT      (isteğe bağlı) Apple WWDR G4 sertifikası; yoksa Apple'dan indirilir
"""
import base64
import hashlib
import hmac
import io
import json
import logging
import os
import tempfile
import threading
import zipfile
from datetime import datetime
from functools import lru_cache

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7
from flask import current_app

log = logging.getLogger("wallet")

WWDR_URL = "https://www.apple.com/certificateauthority/AppleWWDRCAG4.cer"
APNS_URL = "https://api.push.apple.com/3/device/"

BG = (21, 48, 40)          # koyu yeşil (kart zemini)
ACCENT = (255, 138, 101)   # turuncu (dolu damga)
FG = (255, 255, 255)

_wwdr_cache = {}
_cred_cache = {}
_lock = threading.Lock()


# ── Ayarlar ve sertifikalar ─────────────────────────────────────────────────

def _cfg(key: str) -> str:
    return (current_app.config.get(key) or os.environ.get(key) or "").strip()


def is_configured() -> bool:
    return all(_cfg(k) for k in ("APPLE_TEAM_ID", "APPLE_PASS_TYPE_ID", "APPLE_PASS_CERT", "APPLE_PASS_KEY"))


def _decode(value: str) -> bytes:
    """PEM metni ya da (PEM/DER dosyasının) base64'ü -> ham bayt."""
    value = value.strip()
    if "-----BEGIN" in value:
        return value.replace("\\n", "\n").encode()
    return base64.b64decode("".join(value.split()))


def _load_cert(raw: bytes):
    return x509.load_pem_x509_certificate(raw) if b"-----BEGIN" in raw else x509.load_der_x509_certificate(raw)


def _wwdr():
    value = _cfg("APPLE_WWDR_CERT")
    if value:
        return _load_cert(_decode(value))
    with _lock:
        if "cert" not in _wwdr_cache:
            resp = requests.get(WWDR_URL, timeout=15)
            resp.raise_for_status()
            _wwdr_cache["cert"] = _load_cert(resp.content)
    return _wwdr_cache["cert"]


def credentials():
    """(pass sertifikası, özel anahtar) — ortam değişkenlerinden bir kez okunur."""
    key = (_cfg("APPLE_PASS_CERT"), _cfg("APPLE_PASS_KEY"))
    if key not in _cred_cache:
        cert = _load_cert(_decode(key[0]))
        private = serialization.load_pem_private_key(_decode(key[1]), password=None)
        _cred_cache.clear()
        _cred_cache[key] = (cert, private)
    return _cred_cache[key]


# ── Kart kimliği ────────────────────────────────────────────────────────────

def serial_for(customer) -> str:
    return f"sg-{customer.program_id}-{customer.id}"


def parse_serial(serial: str):
    try:
        prefix, program_id, customer_id = serial.split("-")
        return (int(program_id), int(customer_id)) if prefix == "sg" else None
    except (ValueError, AttributeError):
        return None


def auth_token(serial: str) -> str:
    secret = current_app.config["SECRET_KEY"].encode()
    return hmac.new(secret, f"wallet:{serial}".encode(), hashlib.sha256).hexdigest()[:40]


def check_auth(serial: str, header: str) -> bool:
    sent = (header or "").removeprefix("ApplePass ").strip()
    return bool(sent) and hmac.compare_digest(sent, auth_token(serial))


def updated_at(customer) -> datetime:
    """Kartın son değiştiği an (oluşturma ya da son onay/ödül)."""
    from extensions import db
    from models import LoyaltyRequest
    last = (db.session.query(db.func.max(LoyaltyRequest.decided_at))
            .filter(LoyaltyRequest.customer_id == customer.id).scalar())
    created = customer.created_at or datetime(2026, 1, 1)
    return max(created, last) if last else created


# ── Görseller (Pillow) ──────────────────────────────────────────────────────

def _png(img) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def _render(size, draw_fn, scale=4):
    from PIL import Image, ImageDraw
    w, h = size
    big = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(big), w * scale, h * scale)
    return big.resize((w, h), Image.LANCZOS)


def _stamp(d, cx, cy, r, filled):
    if filled:
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ACCENT + (255,))
        inner = r * 0.42
        d.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), outline=FG + (235,), width=max(2, int(r * 0.13)))
    else:
        muted = tuple(int(b + (f - b) * 0.38) for f, b in zip(FG, BG)) + (255,)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=muted, width=max(2, int(r * 0.09)))


@lru_cache(maxsize=256)
def strip_png(required: int, shown: int, width: int, height: int) -> bytes:
    rows = 1 if required <= 8 else 2
    per_row = -(-required // rows)

    def draw(d, w, h):
        d.rectangle((0, 0, w, h), fill=BG + (255,))
        gap_x = w / (per_row + 0.6)
        r = min(gap_x * 0.36, h / (rows * 2) * 0.62)
        for i in range(required):
            row, col = divmod(i, per_row)
            in_row = min(per_row, required - row * per_row)
            start = (w - gap_x * (in_row - 1)) / 2
            cx = start + col * gap_x
            cy = h * (row + 0.5) / rows
            _stamp(d, cx, cy, r, i < shown)

    return _png(_render((width, height), draw))


@lru_cache(maxsize=8)
def icon_png(px: int) -> bytes:
    def draw(d, w, h):
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=w * 0.22, fill=BG + (255,))
        _stamp(d, w / 2, h / 2, w * 0.3, True)
    return _png(_render((px, px), draw))


@lru_cache(maxsize=8)
def logo_png(px: int) -> bytes:
    def draw(d, w, h):
        _stamp(d, w / 2, h / 2, w * 0.46, True)
    return _png(_render((px, px), draw))


# ── .pkpass ─────────────────────────────────────────────────────────────────

def pass_json(program, customer, card_url: str, web_service_url: str) -> dict:
    required = program.stamps_required
    shown = min(customer.stamps, required)
    ready = customer.stamps >= required
    left = max(0, required - customer.stamps)
    serial = serial_for(customer)
    data = {
        "formatVersion": 1,
        "passTypeIdentifier": _cfg("APPLE_PASS_TYPE_ID"),
        "teamIdentifier": _cfg("APPLE_TEAM_ID"),
        "serialNumber": serial,
        "authenticationToken": auth_token(serial),
        "webServiceURL": web_service_url,
        "organizationName": program.name,
        "description": f"{program.name} damga kartı",
        "logoText": program.name[:24],
        "foregroundColor": "rgb(255, 255, 255)",
        "backgroundColor": f"rgb({BG[0]}, {BG[1]}, {BG[2]})",
        "labelColor": f"rgb({ACCENT[0]}, {ACCENT[1]}, {ACCENT[2]})",
        "sharingProhibited": True,
        "storeCard": {
            "headerFields": [{"key": "stamps", "label": "DAMGA", "value": f"{shown}/{required}",
                              "changeMessage": "Damga kartın güncellendi: %@"}],
            "secondaryFields": [
                {"key": "reward", "label": "ÖDÜL", "value": program.reward},
                {"key": "left", "label": "KALAN", "value": "Ödülün hazır!" if ready else f"{left} damga",
                 "changeMessage": "%@"},
            ],
            "auxiliaryFields": [{"key": "name", "label": "KART SAHİBİ", "value": customer.name}],
            "backFields": [
                {"key": "how", "label": "Nasıl çalışır?",
                 "value": (f"Her ziyaretinde kasadaki kodu okut ya da bu kartın QR kodunu kasaya göster. "
                           f"{required} damgada {program.reward}.")},
                {"key": "link", "label": "Kartım", "value": card_url,
                 "attributedValue": f"<a href='{card_url}'>Kartımı aç</a>"},
                {"key": "by", "label": "", "value": "SiparişGeldi ile çalışır"},
            ],
        },
        "barcodes": [{"format": "PKBarcodeFormatQR", "message": card_url,
                      "messageEncoding": "iso-8859-1", "altText": "Kasada okutun"}],
    }
    data["barcode"] = data["barcodes"][0]   # iOS 8 öncesi uyumluluk
    lat, lng = getattr(program, "latitude", None), getattr(program, "longitude", None)
    if lat and lng:
        data["locations"] = [{"latitude": float(lat), "longitude": float(lng),
                              "relevantText": f"{program.name} yakınında · {shown}/{required} damga"}]
    return data


def _sign(manifest: bytes) -> bytes:
    cert, key = credentials()
    return (pkcs7.PKCS7SignatureBuilder()
            .set_data(manifest)
            .add_signer(cert, key, hashes.SHA256())
            .add_certificate(_wwdr())
            .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary]))


def build_pkpass(program, customer, card_url: str, web_service_url: str) -> bytes:
    required = program.stamps_required
    shown = min(customer.stamps, required)
    files = {
        "pass.json": json.dumps(pass_json(program, customer, card_url, web_service_url), ensure_ascii=False).encode(),
        "icon.png": icon_png(29), "icon@2x.png": icon_png(58), "icon@3x.png": icon_png(87),
        "logo.png": logo_png(50), "logo@2x.png": logo_png(100), "logo@3x.png": logo_png(150),
        "strip.png": strip_png(required, shown, 375, 123),
        "strip@2x.png": strip_png(required, shown, 750, 246),
        "strip@3x.png": strip_png(required, shown, 1125, 369),
    }
    manifest = json.dumps({name: hashlib.sha1(body).hexdigest() for name, body in files.items()}).encode()
    files["manifest.json"] = manifest
    files["signature"] = _sign(manifest)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            z.writestr(name, body)
    return out.getvalue()


# ── APNs: kart güncellendi bildirimi ────────────────────────────────────────

def _client_cert_files():
    cert, key = credentials()
    folder = tempfile.gettempdir()
    paths = (os.path.join(folder, "sg_wallet_cert.pem"), os.path.join(folder, "sg_wallet_key.pem"))
    blobs = (cert.public_bytes(serialization.Encoding.PEM),
             key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption()))
    for path, blob in zip(paths, blobs):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob)
    return paths


def _push(app, customer_id: int):
    from extensions import db
    from models import WalletRegistration
    with app.app_context():
        regs = WalletRegistration.query.filter_by(customer_id=customer_id).all()
        if not regs:
            return
        try:
            import httpx
        except ImportError:
            log.warning("[WALLET] httpx[http2] kurulu değil; bildirim gönderilmedi")
            return
        topic = _cfg("APPLE_PASS_TYPE_ID")
        try:
            with httpx.Client(http2=True, cert=_client_cert_files(), timeout=10) as client:
                for reg in regs:
                    resp = client.post(APNS_URL + reg.push_token, headers={"apns-topic": topic}, content=b"{}")
                    if resp.status_code == 410 or (resp.status_code == 400 and "BadDeviceToken" in resp.text):
                        db.session.delete(reg)
                    elif resp.status_code != 200:
                        log.warning("[WALLET] APNs %s: %s", resp.status_code, resp.text[:200])
            db.session.commit()
        except Exception:  # noqa: BLE001 — bildirim hatası damga işlemini bozmasın
            db.session.rollback()
            log.exception("[WALLET] APNs bildirimi gönderilemedi customer=%s", customer_id)


def notify(customer) -> None:
    """Damga değişti: Cüzdan'da bu kart kayıtlıysa iPhone'a güncelleme sinyali gönder (arka planda)."""
    try:
        if not is_configured() or current_app.config.get("TESTING"):
            return
        from models import WalletRegistration
        if not WalletRegistration.query.filter_by(customer_id=customer.id).first():
            return
        app = current_app._get_current_object()
        threading.Thread(target=_push, args=(app, customer.id), daemon=True).start()
    except Exception:  # noqa: BLE001
        log.exception("[WALLET] bildirim başlatılamadı")

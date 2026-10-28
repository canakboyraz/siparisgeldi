"""Damga kartı (sadakat) programı: kurallar ve yardımcılar.

Akış: müşteri kasadaki QR/NFC'yi okutur -> ilk seferde kısa kayıt (ad + telefon),
hoş geldin damgası isteği; sonrakilerde ziyaret damgası isteği oluşur. İstek kasada
SiparişGeldi panelinde onaylanınca damga karta işlenir.
"""
import re
import secrets
from datetime import datetime, timedelta

from extensions import db
from models import LoyaltyCustomer, LoyaltyProgram, LoyaltyRequest

COOKIE_PREFIX = "sg_kart_"
COOKIE_MAX_AGE = 2 * 365 * 24 * 3600


def normalize_phone(raw: str):
    """'0532 123 45 67', '+90 532...' -> '5321234567'; geçersizse None."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("90") and len(digits) == 12:
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    return digits if re.fullmatch(r"5\d{9}", digits) else None


def mask_phone(phone: str) -> str:
    return f"0{phone[:3]} *** ** {phone[-2:]}" if phone and len(phone) == 10 else "-"


def new_token() -> str:
    while True:
        token = secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:10]
        if len(token) >= 8 and not LoyaltyProgram.query.filter_by(token=token).first():
            return token


def get_program(user):
    return LoyaltyProgram.query.filter_by(user_id=user.id).first()


def pending_for(customer):
    """Onay bekleyen istek; süre aşımı yok, kasada onaylanana ya da reddedilene kadar bekler."""
    return (LoyaltyRequest.query.filter(LoyaltyRequest.customer_id == customer.id, LoyaltyRequest.status == "pending")
            .order_by(LoyaltyRequest.id.desc()).first())


def cooldown_left(program, customer) -> int:
    """Son onaylı ziyaretten sonra yeni damga için kalan dakika (0 = istenebilir)."""
    if not customer.last_visit_at or not program.cooldown_minutes:
        return 0
    left = customer.last_visit_at + timedelta(minutes=program.cooldown_minutes) - datetime.utcnow()
    return max(0, int(left.total_seconds() // 60) + (1 if left.total_seconds() % 60 else 0))


def request_stamp(program, customer, kind="visit"):
    """Onay bekleyen bir damga isteği döndürür (varsa mevcut olanı). Bekleme süresindeyse None."""
    existing = pending_for(customer)
    if existing:
        return existing
    if kind == "visit" and cooldown_left(program, customer):
        return None
    stamps = program.welcome_stamps if kind == "welcome" else program.stamps_per_visit
    req = LoyaltyRequest(program_id=program.id, customer_id=customer.id, kind=kind, stamps=max(1, stamps),
                         code=f"{secrets.randbelow(1000):03d}")
    db.session.add(req)
    db.session.commit()
    return req


def approve(req):
    if req.status != "pending":
        return False
    customer = req.customer
    customer.stamps += req.stamps
    customer.lifetime_stamps += req.stamps
    customer.last_visit_at = datetime.utcnow()
    customer.reminders_since_visit = 0
    req.status, req.decided_at = "approved", datetime.utcnow()
    db.session.commit()
    _changed(customer)
    return True


def reject(req):
    if req.status != "pending":
        return False
    req.status, req.decided_at = "rejected", datetime.utcnow()
    db.session.commit()
    return True


def redeem(program, customer):
    if customer.stamps < program.stamps_required:
        return False
    customer.stamps -= program.stamps_required
    customer.rewards_redeemed += 1
    db.session.add(LoyaltyRequest(program_id=program.id, customer_id=customer.id, kind="reward",
                                  stamps=-program.stamps_required, status="approved", code="---",
                                  decided_at=datetime.utcnow()))
    db.session.commit()
    _changed(customer)
    return True


def _changed(customer):
    """Damga değişti: Apple Cüzdan'daki kartı güncelle."""
    import wallet
    wallet.notify(customer)


def stamp_now(program, customer, force=False):
    """Kasada müşterinin kartı okutuldu: damgayı onay beklemeden işler.

    Bekleyen isteği varsa onu onaylar. Bekleme süresi içindeyse (force değilse)
    işlem yapmadan kalan dakikayı döndürür. Dönüş: (durum, istek, kalan_dk)."""
    req = pending_for(customer)
    if not req:
        left = cooldown_left(program, customer)
        if left and not force:
            return "cooldown", None, left
        req = LoyaltyRequest(program_id=program.id, customer_id=customer.id, kind="visit",
                             stamps=max(1, program.stamps_per_visit), code=f"{secrets.randbelow(1000):03d}")
        db.session.add(req)
        db.session.commit()
    approve(req)
    return "ok", req, 0


def card_state(program, customer) -> dict:
    req = pending_for(customer)
    last = (LoyaltyRequest.query.filter(LoyaltyRequest.customer_id == customer.id,
                                        LoyaltyRequest.status.in_(("approved", "rejected")),
                                        LoyaltyRequest.kind != "reward")
            .order_by(LoyaltyRequest.id.desc()).first())
    required = program.stamps_required
    return {
        "stamps": customer.stamps,
        "required": required,
        "shown": min(customer.stamps, required),
        "left": max(0, required - customer.stamps),
        "reward_ready": customer.stamps >= required,
        "rewards_ready_count": customer.stamps // required if required else 0,
        "pending": bool(req),
        "pending_stamps": req.stamps if req else 0,
        "code": req.code if req else "",
        "last_status": last.status if last else "",
        "last_id": last.id if last else 0,
        "last_stamps": last.stamps if last else 0,
        "cooldown": cooldown_left(program, customer),
    }


def find_customer(program, customer_id):
    return LoyaltyCustomer.query.filter_by(id=customer_id, program_id=program.id).first()

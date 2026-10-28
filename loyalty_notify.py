"""Apple Cüzdan damga kartı bildirimleri: hatırlatma ve işletme duyurusu.

Bildirim, Cüzdan kartının arkasındaki "Mesaj" alanının değişmesiyle gider (changeMessage).
Kişi başı iki bildirim arasında en az `notify_min_hours` saat olur; damga eklendi /
ödül hazır bildirimleri bu sınıra dahil değildir (onlar kasadaki işlemle anında gider).
"""
import logging
from datetime import datetime, timedelta

from extensions import db
from models import LoyaltyCustomer, LoyaltyProgram, WalletRegistration

log = logging.getLogger("loyalty_notify")

REMINDERS = (
    "{first}, {reward} için {left} damga kaldı. Seni bekliyoruz ☕",
    "{program}'da kahven seni bekliyor. {left} damga sonra {reward}!",
    "Uzun zamandır görüşemedik {first}! Kartında {stamps} damga var, {reward} çok yakın.",
)
READY = "{first}, {reward} hazır! Kasada söylemen yeterli ☕"


def wallet_customers(program):
    """Kartını Apple Cüzdan'a eklemiş müşteriler."""
    ids = db.session.query(WalletRegistration.customer_id).distinct()
    return LoyaltyCustomer.query.filter(LoyaltyCustomer.program_id == program.id, LoyaltyCustomer.id.in_(ids))


def can_notify(program, customer, now=None) -> bool:
    now = now or datetime.utcnow()
    hours = max(1, program.notify_min_hours or 24)
    # Günlük işin birkaç dakika kayması bir günü atlatmasın diye küçük pay.
    return not customer.wallet_message_at or now - customer.wallet_message_at >= timedelta(hours=hours) - timedelta(minutes=30)


def set_message(customer, text: str, now=None):
    """Kart mesajını değiştir. Aynı metin bildirim üretmez; tekrar ise küçük bir fark ekle."""
    text = " ".join((text or "").split())[:180]
    if text == (customer.wallet_message or ""):
        text = text[:-2] if text.endswith(" ☕") else text + " ☕"
    customer.wallet_message = text
    customer.wallet_message_at = now or datetime.utcnow()


def _fill(template, program, customer):
    left = max(0, program.stamps_required - customer.stamps)
    return template.format(first=(customer.name or "").split(" ")[0] or "Merhaba", program=program.name,
                           reward=program.reward, left=left, stamps=customer.stamps)


def reminder_text(program, customer) -> str:
    if customer.stamps >= program.stamps_required:
        return _fill(READY, program, customer)
    step = (customer.reminders_since_visit or 0) % len(REMINDERS)
    return _fill(REMINDERS[step], program, customer)


def due_reminders(program, now=None):
    """Bugün hatırlatma gidecek müşteriler: Cüzdan'da kartı var, X gündür gelmedi, sınırlar dolmadı."""
    now = now or datetime.utcnow()
    if not program.notify_enabled or not program.is_active or not (program.notify_inactive_days or 0):
        return []
    cutoff = now - timedelta(days=program.notify_inactive_days)
    out = []
    for customer in wallet_customers(program).all():
        last_seen = customer.last_visit_at or customer.created_at or now
        if last_seen > cutoff:
            continue
        if (customer.reminders_since_visit or 0) >= max(1, program.notify_max_reminders or 3):
            continue
        if can_notify(program, customer, now):
            out.append(customer)
    return out


def send_reminders(app):
    """Günlük iş: gelmeyen Cüzdan kartı sahiplerine hatırlatma."""
    import wallet
    with app.app_context():
        if not wallet.is_configured():
            return 0
        now, sent = datetime.utcnow(), []
        for program in LoyaltyProgram.query.filter_by(notify_enabled=True, is_active=True).all():
            try:
                for customer in due_reminders(program, now):
                    set_message(customer, reminder_text(program, customer), now)
                    customer.reminders_since_visit = (customer.reminders_since_visit or 0) + 1
                    sent.append(customer.id)
                db.session.commit()
            except Exception:  # noqa: BLE001 — bir işletmedeki hata diğerlerini durdurmasın
                db.session.rollback()
                log.exception("[LOYALTY] hatırlatma hazırlanamadı program=%s", program.id)
        if sent:
            wallet.push_customers(app, sent)
            log.info("[LOYALTY] %s Cüzdan hatırlatması gönderildi", len(sent))
        return len(sent)


def broadcast(program, text: str, now=None):
    """İşletme duyurusu: Cüzdan'da kartı olanlara (kişi başı sıklık sınırına uyarak). Dönüş: (gönderilen, atlanan)."""
    import wallet
    now = now or datetime.utcnow()
    sent, skipped = [], 0
    for customer in wallet_customers(program).all():
        if not can_notify(program, customer, now):
            skipped += 1
            continue
        set_message(customer, text, now)
        sent.append(customer.id)
    db.session.commit()
    if sent:
        from flask import current_app
        wallet.push_customers(current_app._get_current_object(), sent)
    return len(sent), skipped

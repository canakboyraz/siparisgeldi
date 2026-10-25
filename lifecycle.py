"""Deneme süreci: kullanım özeti ve kurulum/deneme bitiş e-postaları.

Mesajlar kullanıcının kendi gerçek verisini kullanır (kaç sipariş, ne kadar ciro,
hangi platformlar). Uydurma aciliyet veya sosyal kanıt yoktur.
"""
import logging
from datetime import datetime, timedelta

import pytz
from flask import current_app

from extensions import db

log = logging.getLogger("lifecycle")
TURKEY_TZ = pytz.timezone("Europe/Istanbul")
CANCEL_WORDS = ("cancel", "iptal", "reject", "refund", "iade", "return", "unsupplied")


def _valid(order) -> bool:
    status = (order.status or "").replace("_", "").replace(" ", "").lower()
    return not any(word in status for word in CANCEL_WORDS)


def usage_summary(user, since=None) -> dict:
    """Kullanıcının (deneme başından beri) SiparişGeldi'deki kullanımı."""
    from models import Integration, Order, ProductCost
    import utils
    since = since or user.pro_started_at or user.created_at or (datetime.utcnow() - timedelta(days=30))
    orders = Order.query.filter(Order.user_id == user.id, Order.created_at >= since).all()
    valid = [o for o in orders if _valid(o)]
    active = (Integration.query.filter_by(user_id=user.id, is_active=True)
              .order_by(Integration.created_at.asc(), Integration.id.asc()).all())
    return {
        "orders": len(valid),
        "revenue": sum(float(o.total_price or 0) for o in valid),
        "platforms": [utils.platform_label(i.platform) for i in active],
        "keep_platform": utils.platform_label(active[0].platform) if active else None,
        "paused_platforms": [utils.platform_label(i.platform) for i in active[1:]],
        "has_costs": db.session.query(ProductCost.id).filter_by(user_id=user.id).first() is not None,
        "whatsapp": (user.notification_channel or "telegram") in ("whatsapp", "both"),
    }


def _domain() -> str:
    domain = (current_app.config.get("APP_DOMAIN") or "siparisgeldi.net").strip()
    return domain.removeprefix("https://").removeprefix("http://").rstrip("/")


def _tl(value: float) -> str:
    import profit_report
    return profit_report.tl(value)


def _contact_line() -> str:
    phone = current_app.config.get("COMPANY_PHONE", "")
    reach = f"https://{_domain()}/iletisim" + (f" ya da {phone}" if phone else "")
    return f"Takılırsan bize yaz ({reach}); kurulumu birlikte yapalım."


def trial_end_lines(summary: dict) -> list:
    """Deneme bitince neyin açık kalıp neyin duracağını kullanıcının kendi kurulumuyla anlatır."""
    lines = []
    if summary["orders"]:
        lines.append(f"Deneme boyunca {summary['orders']} sipariş ve {_tl(summary['revenue'])} ciro takip edildi.")
    if summary["keep_platform"]:
        lines.append(f"Açık kalır: Telegram bildirimi ve {summary['keep_platform']}.")
    stops = list(summary["paused_platforms"])
    if summary["whatsapp"]:
        stops.append("WhatsApp bildirimi")
    if stops:
        lines.append("Durur: " + ", ".join(stops) + ".")
    return lines


# ── E-postalar ───────────────────────────────────────────────────────────────

def _email_setup(user, summary):
    url = f"https://{_domain()}/panel/"
    subject = "Kurulumun bir adım uzakta"
    text = (f"Merhaba {user.name},\n\nSiparişGeldi hesabın hazır, ama henüz bir platform bağlanmadı. "
            "Trendyol Go, Migros Yemek veya Adisyo'yu bağladığın an yeni siparişler telefonuna düşmeye, "
            "kârın gün gün hesaplanmaya başlar. API bilgilerini girmek birkaç dakika sürüyor.\n\n"
            f"Platformunu bağla: {url}\n\n{_contact_line()}")
    body = (f"<p>Merhaba {user.name},</p><p>Hesabın hazır, ama henüz bir platform bağlanmadı. "
            "Trendyol Go, Migros Yemek veya Adisyo'yu bağladığın an yeni siparişler telefonuna düşmeye, "
            "kârın gün gün hesaplanmaya başlar. API bilgilerini girmek birkaç dakika sürüyor.</p>"
            f"<p>{_contact_line()}</p>")
    return subject, text, body, "Platformumu bağla", url


def _email_costs(user, summary):
    url = f"https://{_domain()}/panel/maliyet-girisi"
    subject = "Gerçek kârını görmene 5 ürün kaldı"
    got = (f"Şu ana kadar {summary['orders']} sipariş ve {_tl(summary['revenue'])} ciro takip edildi. "
           if summary["orders"] else "")
    text = (f"Merhaba {user.name},\n\n{got}Bu cironun ne kadarının sana kaldığını görmek için en çok satan "
            "5 ürününün maliyetini girmen yeterli; komisyon ve paket giderini de girersen kâr raporun her gün hazır olur.\n\n"
            f"Maliyetleri gir: {url}\n\n{_contact_line()}")
    body = (f"<p>Merhaba {user.name},</p><p>{got}Bu cironun ne kadarının sana kaldığını görmek için en çok satan "
            "<b>5 ürününün maliyetini</b> girmen yeterli; komisyon ve paket giderini de girersen kâr raporun her gün hazır olur.</p>"
            f"<p>{_contact_line()}</p>")
    return subject, text, body, "Maliyetleri gir", url


def _email_trial_end(user, summary, days_left, end_day):
    url = f"https://{_domain()}/panel/abonelik"
    cfg = current_app.config
    monthly = float(cfg.get("PRO_MONTHLY_PRICE", 250) or 250)
    yearly = float(cfg.get("PRO_YEARLY_PRICE", 2500) or 2500)
    when = "yarın" if days_left == 1 else f"{days_left} gün sonra"
    subject = f"Pro denemen {when} bitiyor"
    facts = trial_end_lines(summary)
    price = f"Pro aylık {_tl(monthly)}, yıllık {_tl(yearly)}. Otomatik çekim yok; her dönemi sen başlatırsın."
    text = (f"Merhaba {user.name},\n\nPro denemen {end_day:%d.%m.%Y} tarihinde bitiyor.\n\n"
            + "\n".join(facts) + ("\n\n" if facts else "") + price
            + f"\n\nKesintisiz devam et: {url}\n\nDevam etmezsen hiçbir ücret alınmaz, ücretsiz planda kalırsın.")
    body = (f"<p>Merhaba {user.name},</p><p>Pro denemen <b>{end_day:%d.%m.%Y}</b> tarihinde bitiyor.</p>"
            + "".join(f"<p>{line}</p>" for line in facts)
            + f"<p>{price}</p><p style='color:#6b7280'>Devam etmezsen hiçbir ücret alınmaz, ücretsiz planda kalırsın.</p>")
    return subject, text, body, "Pro'ya geç", url


def _send(user, key, builder, *args) -> bool:
    from models import AppState
    from notifications import email
    if AppState.get(key):
        return False
    subject, text, body, button, url = builder(user, *args)
    if email.send_email(user.email, subject, text, email._layout(subject, body, button, url)):
        AppState.set(key, datetime.utcnow().date().isoformat())
        return True
    return False


def send_lifecycle_emails(app):
    """Günde bir: kurulumu yarım kalanlara ve denemesi bitecek olanlara e-posta.

    - 1. gün: hiç platform bağlamadıysa kurulum hatırlatması (bir kez)
    - 3. gün: platformu var ama ürün maliyeti yoksa maliyet hatırlatması (bir kez)
    - Denemenin bitmesine 3 ve 1 gün kala: Telegram'ı bağlı olmayanlara e-posta
      (Telegram'ı bağlı olanlar aynı hatırlatmayı Telegram'dan alıyor)
    """
    from models import Integration, User
    from notifications import email
    with app.app_context():
        if not email.is_configured():
            return
        now = datetime.utcnow()
        today = datetime.now(TURKEY_TZ).date()
        users = User.query.filter(User.is_trial.is_(True), User.pro_expires_at.isnot(None),
                                  User.pro_expires_at > now).all()
        for user in users:
            if getattr(user, "is_demo", False) or not user.email:
                continue
            try:
                started = user.pro_started_at or user.created_at or now
                age_days = (now - started).days
                has_platform = db.session.query(Integration.id).filter_by(user_id=user.id).first() is not None
                summary = usage_summary(user)
                if 1 <= age_days <= 4 and not has_platform:
                    _send(user, f"lc:{user.id}:setup", _email_setup, summary)
                elif 3 <= age_days <= 7 and has_platform and not summary["has_costs"]:
                    _send(user, f"lc:{user.id}:costs", _email_costs, summary)
                end_day = pytz.utc.localize(user.pro_expires_at).astimezone(TURKEY_TZ).date()
                days_left = (end_day - today).days
                if days_left in (3, 1) and not user.telegram_chat_id:
                    _send(user, f"lc:{user.id}:end{days_left}:{end_day:%m%d}", _email_trial_end,
                          summary, days_left, end_day)
            except Exception:  # noqa: BLE001 — bir kullanıcıdaki hata diğerlerini durdurmasın
                db.session.rollback()
                log.exception("[LIFECYCLE] e-posta gönderilemedi user=%s", user.id)

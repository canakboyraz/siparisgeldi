"""İzleme ve plan yönetimi işleri.

- configure_logging / init_sentry: uygulama açılışında çağrılır.
- heartbeat: worker'ın yaşadığını DB'ye yazar (/healthz okur).
- check_stale_syncs: polling yapılan entegrasyon uzun süredir senkron
  olmadıysa yöneticiye Telegram alarmı gönderir.
- enforce_plan_limits: Pro/deneme süresi biten hesaplarda ücretsiz plan
  limitini (1 aktif platform) uygular.
- send_trial_reminders: deneme bitmeden Telegram hatırlatması gönderir.
"""
import logging
import os
from datetime import datetime, timedelta

import pytz
from flask import current_app

from extensions import db

log = logging.getLogger("monitoring")
TURKEY_TZ = pytz.timezone("Europe/Istanbul")

HEARTBEAT_KEY = "worker_heartbeat"
POLLED_PLATFORMS = ("trendyolgo", "trendyolgo_market", "trendyol_marketplace", "hepsiburada")
STALE_ALERT_REPEAT_MINUTES = 60


# ── Açılış ──────────────────────────────────────────────────────────────────

def configure_logging():
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=getattr(logging, level, logging.INFO),
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
    else:
        root.setLevel(getattr(logging, level, logging.INFO))


def init_sentry(app):
    dsn = app.config.get("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
    except ImportError:
        log.warning("SENTRY_DSN tanımlı ama sentry-sdk kurulu değil (pip install sentry-sdk[flask]).")
        return False
    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0") or 0),
        send_default_pii=False,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
    )
    log.info("Sentry etkin.")
    return True


# ── Yönetici alarmı ─────────────────────────────────────────────────────────

def admin_chat_ids() -> list:
    ids = list(current_app.config.get("ADMIN_ALERT_TELEGRAM_CHAT_IDS") or [])
    if ids:
        return ids
    from models import User
    emails = current_app.config.get("ADMIN_EMAILS") or []
    if not emails:
        return []
    users = User.query.filter(User.email.in_(emails), User.telegram_chat_id.isnot(None)).all()
    return [u.telegram_chat_id for u in users]


def send_admin_alert(text: str) -> bool:
    from notifications import telegram
    token = current_app.config.get("TELEGRAM_BOT_TOKEN", "")
    sent = False
    for chat_id in admin_chat_ids():
        sent = telegram.send_message(token, chat_id, text) or sent
    if not sent:
        log.warning("[ADMIN ALARM] gönderilemedi (chat id yok?): %s", text.replace("\n", " | ")[:300])
    return sent


# ── Heartbeat ───────────────────────────────────────────────────────────────

def heartbeat(app):
    from models import AppState
    with app.app_context():
        AppState.set(HEARTBEAT_KEY, datetime.utcnow().isoformat(timespec="seconds"))


def heartbeat_age_seconds():
    """Son heartbeat'ten bu yana geçen saniye; hiç yoksa None."""
    from models import AppState
    raw = AppState.get(HEARTBEAT_KEY)
    if not raw:
        return None
    try:
        return (datetime.utcnow() - datetime.fromisoformat(raw)).total_seconds()
    except ValueError:
        return None


# ── Senkron gecikme alarmı ──────────────────────────────────────────────────

def _has_credentials(intg) -> bool:
    if intg.platform in ("trendyolgo", "trendyolgo_market"):
        return bool(intg.tgo_supplier_id and intg._tgo_api_key)
    if intg.platform == "trendyol_marketplace":
        return bool(intg.tmp_supplier_id and intg._tmp_api_key)
    if intg.platform == "hepsiburada":
        return bool(intg.hb_merchant_id and intg.hb_username and intg._hb_service_key)
    return False


def find_stale_integrations(now: datetime = None, stale_minutes: int = None) -> list:
    from models import Integration
    now = now or datetime.utcnow()
    stale_minutes = stale_minutes or int(current_app.config.get("SYNC_STALE_ALERT_MINUTES", 10))
    limit = now - timedelta(minutes=stale_minutes)
    stale = []
    for intg in Integration.query.filter(
        Integration.platform.in_(POLLED_PLATFORMS), Integration.is_active.is_(True)
    ).all():
        if not _has_credentials(intg):
            continue
        reference = intg.last_sync_at or intg.updated_at or intg.created_at
        if reference and reference < limit:
            stale.append(intg)
    return stale


def check_stale_syncs(app):
    from models import AppState, User
    import utils
    with app.app_context():
        now = datetime.utcnow()
        to_alert = []
        for intg in find_stale_integrations(now):
            key = f"stale_alert:{intg.id}"
            last = AppState.get(key)
            if last:
                try:
                    if now - datetime.fromisoformat(last) < timedelta(minutes=STALE_ALERT_REPEAT_MINUTES):
                        continue
                except ValueError:
                    pass
            to_alert.append(intg)
            AppState.set(key, now.isoformat(timespec="seconds"))
        if not to_alert:
            return
        lines = []
        for intg in to_alert[:20]:
            user = db.session.get(User, intg.user_id)
            minutes = int((now - (intg.last_sync_at or intg.created_at)).total_seconds() // 60)
            err = f" — {intg.last_error[:120]}" if intg.last_error else ""
            lines.append(f"• {utils.platform_label(intg.platform)} · {user.email if user else intg.user_id} · {minutes} dk{err}")
        more = f"\n… ve {len(to_alert) - 20} entegrasyon daha" if len(to_alert) > 20 else ""
        send_admin_alert("⚠️ <b>Senkron gecikmesi</b>\n\n" + "\n".join(lines) + more)


# ── Plan limitleri ──────────────────────────────────────────────────────────

def _limit_scope_applies(user) -> bool:
    scope = (current_app.config.get("PLAN_LIMIT_SCOPE") or "trial").lower()
    if scope == "off":
        return False
    if scope == "all":
        return True
    return bool(user.is_trial)  # varsayılan: yalnızca denemesi biten hesaplar


def enforce_plan_limits(app):
    """Çoklu platform hakkı bitmiş hesaplarda en eski aktif entegrasyon açık
    kalır, diğerleri duraklatılır ve kullanıcıya bilgi verilir."""
    from models import Integration, User
    from notifications.dispatcher import send_to_user
    import utils
    with app.app_context():
        users = (User.query.join(Integration, Integration.user_id == User.id)
                 .filter(Integration.is_active.is_(True))
                 .group_by(User.id)
                 .having(db.func.count(Integration.id) > 1)
                 .all())
        domain = (current_app.config.get("APP_DOMAIN") or "siparisgeldi.net").strip()
        domain = domain.removeprefix("https://").removeprefix("http://").rstrip("/")
        for user in users:
            if user.has_multi_platform_access or not _limit_scope_applies(user):
                continue
            active = (Integration.query.filter_by(user_id=user.id, is_active=True)
                      .order_by(Integration.created_at.asc(), Integration.id.asc()).all())
            keep, paused = active[0], active[1:]
            for intg in paused:
                intg.is_active = False
            if (user.notification_channel or "telegram") != "telegram" and not user.has_whatsapp_access:
                user.notification_channel = "telegram"
            db.session.commit()
            paused_names = ", ".join(utils.platform_label(i.platform) for i in paused)
            reason = "Deneme süren sona erdi" if user.is_trial else "Pro süren sona erdi"
            log.info("[PLAN] user=%s çoklu platform kapandı, duraklatılan=%s", user.id, paused_names)
            try:
                send_to_user(
                    user,
                    f"ℹ️ <b>{reason}</b>\n\nÜcretsiz planda 1 platform aktif kalır.\n"
                    f"Açık: {utils.platform_label(keep.platform)}\nDuraklatıldı: {paused_names}\n\n"
                    f"Tüm platformları tekrar açmak için Pro'ya geç: https://{domain}/panel/abonelik",
                    source="plan",
                )
            except Exception as e:  # noqa: BLE001
                log.warning("[PLAN] bildirim gönderilemedi user=%s: %s", user.id, e)


# ── Deneme hatırlatmaları ───────────────────────────────────────────────────

TRIAL_REMINDER_DAYS = (3, 1)


def send_trial_reminders(app):
    """Deneme ve ücretli Pro süresi bitmeden 3 ve 1 gün önce Telegram hatırlatması.
    (WhatsApp kanalındaki ücretli kullanıcılara ayrıca WhatsApp uyarısı gider.)"""
    from models import AppState, User
    from notifications import telegram
    with app.app_context():
        token = current_app.config.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            return
        now = datetime.utcnow()
        today = datetime.now(TURKEY_TZ).date()
        domain = (current_app.config.get("APP_DOMAIN") or "siparisgeldi.net").strip()
        domain = domain.removeprefix("https://").removeprefix("http://").rstrip("/")
        users = User.query.filter(
            User.plan == "pro",
            User.pro_expires_at.isnot(None), User.pro_expires_at > now,
            User.telegram_chat_id.isnot(None),
        ).all()
        for user in users:
            if not user.is_trial and (user.notification_channel or "telegram") == "whatsapp":
                continue  # WhatsApp uyarısı ayrı işte gönderiliyor
            end_day = pytz.utc.localize(user.pro_expires_at).astimezone(TURKEY_TZ).date()
            days_left = (end_day - today).days
            if days_left not in TRIAL_REMINDER_DAYS:
                continue
            key = f"pro_reminder:{user.id}:{end_day.isoformat()}:{days_left}"
            if AppState.get(key):
                continue
            what = "Pro denemenin" if user.is_trial else "Pro aboneliğinin"
            if _limit_scope_applies(user):
                effect = ("Süre bitince ücretsiz plana geçersin: Telegram bildirimi ve 1 platform açık kalır; "
                          "WhatsApp ve diğer platformlar duraklar.")
            else:
                effect = "Süre bitince WhatsApp bildirimleri durur, yeni platform eklenemez."
            text = (
                f"⏳ <b>{what} bitmesine {days_left} gün kaldı</b> ({end_day.strftime('%d.%m.%Y')})\n\n"
                f"{effect}\n\n"
                f"Kesintisiz devam etmek için: https://{domain}/panel/abonelik"
            )
            if telegram.send_message(token, user.telegram_chat_id, text):
                AppState.set(key, today.isoformat())

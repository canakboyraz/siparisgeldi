"""Panel: özet, Telegram bağlama, TrendyolGo kurulum, siparişler, profil."""
import json
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func, or_
import pytz

from extensions import db
from models import Integration, Order
from integrations import getir, hepsiburada as hb, migros, trendyol_marketplace as tmp, trendyolgo as tgo, yemeksepeti as ys
from utils import platform_label, status_label

dashboard_bp = Blueprint("dashboard", __name__)
TURKEY_TZ = pytz.timezone("Europe/Istanbul")
TGO_FOOD_PLATFORM = "trendyolgo"
TGO_MARKET_PLATFORM = "trendyolgo_market"

PENDING_STATUSES = {"Created", "NEW_PENDING", "Pending", "New", "Scheduled", "Awaiting", "RECEIVED"}
PREPARING_STATUSES = {"Picking", "Invoiced", "Approved", "Prepared", "ScheduledApproved", "READY_FOR_PICKUP"}
DELIVERY_STATUSES = {"Shipped", "Delivery", "OnDelivery", "On_Delivery", "AtCollectionPoint", "DISPATCHED"}
CANCELLED_STATUSES = {"Cancelled", "Canceled", "CANCELED", "CANCELLED", "UnSupplied", "Rejected", "REJECTED", "AdminCancelled", "AutoCancelled"}
REFUNDED_STATUSES = {"Refunded", "Refund", "Returned", "Return", "PartiallyRefunded", "PartialRefunded", "RETURNED", "REFUNDED"}
PROBLEM_STATUSES = CANCELLED_STATUSES | REFUNDED_STATUSES
DONE_STATUSES = {"Delivered", "DELIVERED", "Completed"}
ACTIVE_EXCLUDED_STATUSES = PROBLEM_STATUSES | DONE_STATUSES
UNACCEPTED_WARNING_SECONDS = 120
ORDER_POPUP_SOUND_OPTIONS = [
    ("classic", "Klasik üçlü"),
    ("double", "Çift uyarı"),
    ("short", "Kısa uyarı"),
    ("bell", "Zil tonu"),
]


def _is_pro_user(user=None) -> bool:
    user = user or current_user
    return (getattr(user, "plan", "free") or "free").lower() == "pro"


def _can_use_whatsapp(user=None) -> bool:
    return bool(getattr(user or current_user, "has_whatsapp_access", False))


def _can_use_multi_platform(user=None) -> bool:
    return bool(getattr(user or current_user, "has_multi_platform_access", False))


def _active_integration_count(exclude_id: int = None) -> int:
    query = Integration.query.filter_by(user_id=current_user.id, is_active=True)
    if exclude_id:
        query = query.filter(Integration.id != exclude_id)
    return query.count()


def _can_enable_platform(existing: Integration = None) -> bool:
    if _can_use_multi_platform():
        return True
    if existing and existing.is_active:
        return True
    return _active_integration_count(existing.id if existing else None) < 1


def _force_free_notification_channel():
    if not _can_use_whatsapp() and (current_user.notification_channel or "telegram") != "telegram":
        current_user.notification_channel = "telegram"


@dashboard_bp.route("/")
@login_required
def index():
    integrations = Integration.query.filter_by(user_id=current_user.id).all()
    recent = (Order.query.filter_by(user_id=current_user.id)
              .order_by(Order.created_at.desc()).limit(10).all())
    today_count = None
    return render_template("dashboard/index.html",
                           integrations=integrations, recent_orders=recent,
                           today_count=today_count)


# ── Telegram bağlama ────────────────────────────────────────────────────────

@dashboard_bp.route("/telegram")
@login_required
def connect_telegram():
    token = current_user.ensure_link_token()
    db.session.commit()
    bot_username = current_app.config.get("TELEGRAM_BOT_USERNAME", "")
    deep_link = f"https://t.me/{bot_username}?start={token}" if bot_username else ""
    return render_template("dashboard/connect_telegram.html",
                           deep_link=deep_link, bot_username=bot_username)


@dashboard_bp.route("/telegram/yenile", methods=["POST"])
@login_required
def reset_telegram():
    """Bağlantıyı sıfırla (yeni link üret, mevcut chat bağını kaldır)."""
    current_user.telegram_chat_id = None
    current_user.telegram_link_token = None
    current_user.ensure_link_token()
    db.session.commit()
    flash("Telegram bağlantısı sıfırlandı. Yeni linkle tekrar bağlanın.", "info")
    return redirect(url_for("dashboard.connect_telegram"))


# ── WhatsApp bağlama ────────────────────────────────────────────────────────

@dashboard_bp.route("/whatsapp", methods=["GET", "POST"])
@login_required
def connect_whatsapp():
    if request.method == "POST":
        number  = request.form.get("whatsapp_number", "").strip()
        channel = request.form.get("notification_channel", "").strip()
        current_user.whatsapp_number = number or None
        if not _can_use_whatsapp() and channel in ("whatsapp", "both"):
            current_user.notification_channel = "telegram"
            flash("WhatsApp bildirimleri Pro planda kullanılabilir. Ücretsiz planda Telegram açık kalır.", "warning")
        elif channel in ("telegram", "whatsapp", "both"):
            current_user.notification_channel = channel
        db.session.commit()
        flash("WhatsApp ayarların kaydedildi.", "success")
        return redirect(url_for("dashboard.connect_whatsapp"))
    _force_free_notification_channel()
    db.session.commit()
    return render_template("dashboard/connect_whatsapp.html", can_use_whatsapp=_can_use_whatsapp())


@dashboard_bp.route("/whatsapp/test", methods=["POST"])
@login_required
def test_whatsapp():
    """WhatsApp'a örnek sipariş bildirimi gönderir (şablon → serbest metin fallback)."""
    if not _can_use_whatsapp():
        flash("WhatsApp test bildirimi Pro planda kullanılabilir.", "warning")
        return redirect(url_for("dashboard.connect_whatsapp"))
    from notifications import whatsapp
    cfg = current_app.config
    num = current_user.whatsapp_number
    tok = cfg.get("WHATSAPP_ACCESS_TOKEN")
    pnid = cfg.get("WHATSAPP_PHONE_NUMBER_ID")
    if not (num and tok and pnid):
        flash("WhatsApp numarası veya sistem yapılandırması eksik.", "warning")
        return redirect(url_for("dashboard.connect_whatsapp"))
    ver = cfg.get("WHATSAPP_API_VERSION", "v21.0")
    ok, err = whatsapp.send_template(
        num, cfg.get("WHATSAPP_TEMPLATE_NAME", "siparis_bildirim"),
        cfg.get("WHATSAPP_TEMPLATE_LANG", "tr"),
        ["Test bildirimi", "TEST-001", "Örnek ürün x1", "0,00 ₺"], tok, pnid, ver)
    if not ok:
        ok, err2 = whatsapp.send_text(num, "🔔 Test — WhatsApp bildirimlerin çalışıyor! (SiparişGeldi)", tok, pnid, ver)
        err = None if ok else (err or err2)
    flash("✅ WhatsApp test mesajı gönderildi." if ok else f"⚠️ Gönderilemedi: {err}",
          "success" if ok else "warning")
    return redirect(url_for("dashboard.connect_whatsapp"))


@dashboard_bp.route("/rapor/test", methods=["POST"])
@login_required
def test_report():
    """Kullanıcının aktif entegrasyonları için günlük raporu hemen tetikler."""
    from datetime import datetime
    import pytz
    from worker import _period_orders, _send_period_report
    TZ = pytz.timezone("Europe/Istanbul")
    today = datetime.now(TZ).date()
    intgs = Integration.query.filter_by(user_id=current_user.id, is_active=True).all()
    if not intgs:
        flash("Önce bir platform (TrendyolGo/Migros) bağla.", "warning")
        return redirect(url_for("dashboard.index"))
    count = 0
    for intg in intgs:
        try:
            start = TZ.localize(datetime.combine(today, datetime.min.time()))
            orders = _period_orders(intg, start)
            _send_period_report(intg, "Günlük", today.strftime('%d.%m.%Y'), orders)
            count += 1
        except Exception as e:
            print(f"[RAPOR TEST] Hata user={current_user.id}: {e}")
    flash(f"✅ {count} platform için test raporu gönderildi — kanalını kontrol et.", "success")
    return redirect(url_for("dashboard.index"))


# ── TrendyolGo ──────────────────────────────────────────────────────────────

@dashboard_bp.route("/trendyolgo", methods=["GET", "POST"])
@login_required
def trendyolgo_setup():
    return _trendyolgo_setup(TGO_FOOD_PLATFORM, "dashboard.trendyolgo_setup", "dashboard/trendyolgo_setup.html")


@dashboard_bp.route("/trendyolgo-market", methods=["GET", "POST"])
@login_required
def trendyolgo_market_setup():
    return _trendyolgo_setup(TGO_MARKET_PLATFORM, "dashboard.trendyolgo_market_setup", "dashboard/trendyolgo_market_setup.html")


def _trendyolgo_setup(platform: str, endpoint: str, template: str):
    intg = Integration.query.filter_by(user_id=current_user.id, platform=platform).first()
    service = _tgo_service_for_platform(platform)

    if request.method == "POST":
        supplier_id = request.form.get("supplier_id", "").strip()
        store_id    = request.form.get("store_id", "").strip()
        api_key     = request.form.get("api_key", "").strip()
        api_secret  = request.form.get("api_secret", "").strip()
        has_saved_credentials = bool(intg and intg._tgo_api_key and intg._tgo_api_secret)

        if not _can_enable_platform(intg):
            flash("Ücretsiz planda 1 platform bağlayabilirsin. WhatsApp ve çoklu platform için Pro plana geç.", "warning")
            return render_template(template, intg=intg)

        if not supplier_id or (not has_saved_credentials and (not api_key or not api_secret)):
            flash("Tüm alanlar zorunludur.", "danger")
            return render_template(template, intg=intg)

        test_api_key = api_key or (intg.tgo_api_key if intg else None)
        test_api_secret = api_secret or (intg.tgo_api_secret if intg else None)
        if not test_api_key or not test_api_secret:
            flash("API anahtarları kayıtlı değil, lütfen giriniz.", "danger")
            return render_template(template, intg=intg)

        ok, msg, _ = tgo.test_connection(supplier_id, test_api_key, test_api_secret, service=service)
        if not ok:
            flash(f"API bağlantısı başarısız: {msg}", "danger")
            return render_template(template, intg=intg)

        if not intg:
            intg = Integration(user_id=current_user.id, platform=platform)
            db.session.add(intg)

        intg.tgo_supplier_id = supplier_id
        intg.tgo_store_id    = store_id
        if api_key:
            intg.tgo_api_key     = api_key
        if api_secret:
            intg.tgo_api_secret  = api_secret
        intg.is_active       = True
        db.session.commit()

        flash(f"✅ TrendyolGo bağlandı! {msg}", "success")
        if not current_user.telegram_connected:
            flash("Bildirim alabilmek için Telegram'ı da bağlayın.", "warning")
        return redirect(url_for(endpoint))

    return render_template(template, intg=intg)


@dashboard_bp.route("/trendyolgo/store-status", methods=["POST"])
@login_required
def update_trendyolgo_store_status():
    platform = _tgo_platform_from_form()
    intg = Integration.query.filter_by(user_id=current_user.id, platform=platform, is_active=True).first_or_404()
    action = request.form.get("action", "").strip()
    status = "OPEN" if action == "open" else "CLOSED" if action == "close" else ""
    if not status:
        flash("Gecersiz Trendyol Go restoran islemi.", "warning")
        return redirect(_tgo_setup_url(platform))
    if not intg.tgo_supplier_id or not intg.tgo_store_id or not intg.tgo_api_key or not intg.tgo_api_secret:
        flash("Trendyol Go Supplier ID, Store ID ve API bilgileri eksik.", "danger")
        return redirect(_tgo_setup_url(platform))
    try:
        tgo.set_store_working_status(
            intg.tgo_supplier_id,
            intg.tgo_store_id,
            intg.tgo_api_key,
            intg.tgo_api_secret,
            status,
            service=_tgo_service_for_platform(platform),
        )
        intg.last_sync_at = datetime.utcnow()
        intg.last_error = None
        db.session.commit()
        flash("Trendyol Go restoran satisa acildi." if status == "OPEN" else "Trendyol Go restoran satisa kapatildi.", "success")
    except Exception as e:
        intg.last_error = f"Trendyol Go restoran islemi: {e}"[:300]
        db.session.commit()
        flash(f"Trendyol Go restoran islemi gonderilemedi: {e}", "danger")
    return redirect(_tgo_setup_url(platform))


@dashboard_bp.route("/trendyolgo/check-now", methods=["POST"])
@login_required
def check_trendyolgo_now():
    platform = _tgo_platform_from_form()
    intg = Integration.query.filter_by(user_id=current_user.id, platform=platform, is_active=True).first_or_404()
    if not intg.tgo_supplier_id or not intg.tgo_api_key or not intg.tgo_api_secret:
        flash("Trendyol Go API bilgileri eksik.", "danger")
        return redirect(_tgo_setup_url(platform))
    try:
        from worker import _process_tgo
        processed = _process_tgo(intg) or 0
        intg.last_sync_at = datetime.utcnow()
        intg.last_error = None
        db.session.commit()
        flash(f"Trendyol Go siparis kontrolu calisti. {processed} siparis bulundu/islendi.", "success")
    except Exception as e:
        db.session.rollback()
        intg.last_error = f"Trendyol Go manuel kontrol: {e}"[:300]
        db.session.commit()
        flash(f"Trendyol Go kontrolu basarisiz: {e}", "danger")
    return redirect(_tgo_setup_url(platform))


def _tgo_platform_from_form() -> str:
    return TGO_MARKET_PLATFORM if request.form.get("platform") == TGO_MARKET_PLATFORM else TGO_FOOD_PLATFORM


def _tgo_service_for_platform(platform: str) -> str:
    return tgo.SERVICE_GROCERY if platform == TGO_MARKET_PLATFORM else tgo.SERVICE_MEAL


def _tgo_setup_url(platform: str) -> str:
    endpoint = "dashboard.trendyolgo_market_setup" if platform == TGO_MARKET_PLATFORM else "dashboard.trendyolgo_setup"
    return url_for(endpoint)


@dashboard_bp.route("/trendyol-pazaryeri", methods=["GET", "POST"])
@login_required
def trendyol_marketplace_setup():
    intg = Integration.query.filter_by(user_id=current_user.id, platform=tmp.PLATFORM).first()

    if request.method == "POST":
        supplier_id = request.form.get("supplier_id", "").strip()
        integration_ref = request.form.get("integration_ref", "").strip()
        api_key = request.form.get("api_key", "").strip()
        api_secret = request.form.get("api_secret", "").strip()
        has_saved_credentials = bool(intg and intg._tmp_api_key and intg._tmp_api_secret)

        if not _can_enable_platform(intg):
            flash("Ücretsiz planda 1 platform bağlayabilirsin. WhatsApp ve çoklu platform için Pro plana geç.", "warning")
            return render_template("dashboard/trendyol_marketplace_setup.html", intg=intg, **_tmp_setup_context())

        if not supplier_id or (not has_saved_credentials and (not api_key or not api_secret)):
            flash("Satıcı ID, API Key ve API Secret zorunludur.", "danger")
            return render_template("dashboard/trendyol_marketplace_setup.html", intg=intg, **_tmp_setup_context())

        test_key = api_key or intg.tmp_api_key
        test_secret = api_secret or intg.tmp_api_secret
        ok, msg, _ = tmp.test_connection(
            supplier_id,
            test_key,
            test_secret,
            current_app.config.get("TRENDYOL_MARKETPLACE_API_BASE"),
        )
        if not ok:
            flash(f"API bağlantısı başarısız: {msg}", "danger")
            return render_template("dashboard/trendyol_marketplace_setup.html", intg=intg, **_tmp_setup_context())

        if not intg:
            intg = Integration(user_id=current_user.id, platform=tmp.PLATFORM)
            db.session.add(intg)

        intg.tmp_supplier_id = supplier_id
        intg.tmp_integration_ref = integration_ref or None
        if api_key:
            intg.tmp_api_key = api_key
        if api_secret:
            intg.tmp_api_secret = api_secret
        intg.is_active = True
        intg.last_error = None
        db.session.commit()

        flash(f"Trendyol Pazaryeri bağlandı! {msg}", "success")
        if not current_user.telegram_connected:
            flash("Bildirim alabilmek için Telegram'ı da bağlayın.", "warning")
        return redirect(url_for("dashboard.trendyol_marketplace_setup"))

    return render_template("dashboard/trendyol_marketplace_setup.html", intg=intg, **_tmp_setup_context())


def _tmp_setup_context() -> dict:
    return {
        "tmp_api_base": current_app.config.get("TRENDYOL_MARKETPLACE_API_BASE"),
        "tmp_webhook_url": url_for("webhooks.trendyol_marketplace_order", _external=True),
        "tmp_webhook_key_ready": bool(current_app.config.get("TRENDYOL_MARKETPLACE_WEBHOOK_API_KEY")),
    }


# ── Migros Yemek ────────────────────────────────────────────────────────────

@dashboard_bp.route("/yemeksepeti", methods=["GET", "POST"])
@login_required
def yemeksepeti_setup():
    intg = Integration.query.filter_by(user_id=current_user.id, platform=ys.PLATFORM).first()

    if request.method == "POST":
        chain_id = request.form.get("chain_id", "").strip()
        store_id = request.form.get("store_id", "").strip()
        vendor_id = request.form.get("vendor_id", "").strip()
        environment = request.form.get("environment", "live").strip().lower()
        client_id = request.form.get("client_id", "").strip()
        client_secret = request.form.get("client_secret", "").strip()

        if not _can_enable_platform(intg):
            flash("Ücretsiz planda 1 platform bağlayabilirsin. WhatsApp ve çoklu platform için Pro plana geç.", "warning")
            return render_template("dashboard/yemeksepeti_setup.html", intg=intg, **_ys_setup_context(intg))
        if not store_id:
            flash("Mağaza/Store ID zorunludur.", "danger")
            return render_template("dashboard/yemeksepeti_setup.html", intg=intg, **_ys_setup_context(intg))
        if environment not in ("sandbox", "live"):
            environment = "live"

        if not intg:
            intg = Integration(user_id=current_user.id, platform=ys.PLATFORM)
            db.session.add(intg)
        intg.ys_chain_id = chain_id or None
        intg.ys_store_id = store_id
        intg.ys_vendor_id = vendor_id or store_id
        intg.ys_environment = environment
        if client_id:
            intg.ys_client_id = client_id
        if client_secret:
            intg.ys_client_secret = client_secret
        intg.is_active = True
        intg.last_error = None
        db.session.commit()

        flash("Yemeksepeti bağlantısı kaydedildi. Webhook artık bu Store ID için bekleniyor.", "success")
        return redirect(url_for("dashboard.yemeksepeti_setup"))

    return render_template("dashboard/yemeksepeti_setup.html", intg=intg, **_ys_setup_context(intg))


@dashboard_bp.route("/yemeksepeti/test-connection", methods=["POST"])
@login_required
def test_yemeksepeti_connection():
    intg = Integration.query.filter_by(
        user_id=current_user.id, platform=ys.PLATFORM, is_active=True
    ).first()
    if not intg:
        flash("Önce Yemeksepeti mağaza bilgilerini kaydetmelisin.", "warning")
        return redirect(url_for("dashboard.yemeksepeti_setup"))
    if not intg.ys_chain_id or not (intg.ys_vendor_id or intg.ys_store_id):
        flash("Chain ID ve Vendor/Store ID bilgileri eksik.", "warning")
        return redirect(url_for("dashboard.yemeksepeti_setup"))
    if not intg.ys_client_id or not intg.ys_client_secret:
        flash("OAuth client_id ve client_secret bilgileri henüz kaydedilmemiş.", "warning")
        return redirect(url_for("dashboard.yemeksepeti_setup"))

    ok, message, data = ys.test_connection(
        intg.ys_chain_id,
        intg.ys_vendor_id or intg.ys_store_id,
        intg.ys_client_id,
        intg.ys_client_secret,
        intg.ys_environment or "live",
    )
    if ok:
        intg.last_error = None
        intg.last_sync_at = datetime.utcnow()
        db.session.commit()
        flash(message, "success")
    else:
        intg.last_error = message[:300]
        db.session.commit()
        flash(message, "danger")
    return redirect(url_for("dashboard.yemeksepeti_setup"))


@dashboard_bp.route("/yemeksepeti/restoran-durum", methods=["POST"])
@login_required
def update_yemeksepeti_vendor_status():
    intg = Integration.query.filter_by(
        user_id=current_user.id, platform=ys.PLATFORM, is_active=True
    ).first()
    if not intg:
        flash("Önce Yemeksepeti bağlantısını kaydetmelisin.", "warning")
        return redirect(url_for("dashboard.yemeksepeti_setup"))
    if not intg.ys_chain_id or not (intg.ys_vendor_id or intg.ys_store_id):
        flash("Chain ID ve Vendor/Store ID bilgileri eksik.", "warning")
        return redirect(url_for("dashboard.yemeksepeti_setup"))
    if not intg.ys_client_id or not intg.ys_client_secret:
        flash("Yemeksepeti OAuth bilgileri henüz kaydedilmemiş.", "warning")
        return redirect(url_for("dashboard.yemeksepeti_setup"))

    status = request.form.get("status", "").strip().upper()
    body = {"status": status}
    if status == "CLOSED_UNTIL":
        closed_until = request.form.get("closed_until", "").strip()
        if not closed_until:
            flash("Belirli saate kadar kapatma için tarih/saat seçmelisin.", "warning")
            return redirect(url_for("dashboard.yemeksepeti_setup"))
        try:
            local_until = datetime.fromisoformat(closed_until)
            closed_until = TURKEY_TZ.localize(local_until).astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            flash("Kapatma zamanı geçerli değil.", "warning")
            return redirect(url_for("dashboard.yemeksepeti_setup"))
        body["closed_until"] = closed_until
        body["closed_reason"] = request.form.get("closed_reason", "TOO_BUSY_KITCHEN").strip().upper()
    elif status == "CLOSED_TODAY":
        body["closed_reason"] = request.form.get("closed_reason", "TOO_BUSY_KITCHEN").strip().upper()
    elif status not in {"OPEN", "CHECKIN"}:
        flash("Geçersiz restoran durumu.", "warning")
        return redirect(url_for("dashboard.yemeksepeti_setup"))

    try:
        result = ys.update_vendor_status(
            intg.ys_chain_id,
            intg.ys_vendor_id or intg.ys_store_id,
            body,
            intg.ys_client_id,
            intg.ys_client_secret,
            intg.ys_environment or "live",
        )
        intg.last_sync_at = datetime.utcnow()
        intg.last_error = None
        db.session.commit()
        flash(f"Yemeksepeti restoran durumu güncellendi: {result.get('status') or status}", "success")
    except Exception as e:
        intg.last_error = f"Yemeksepeti restoran durumu: {e}"[:300]
        db.session.commit()
        flash("Yemeksepeti restoran durumu güncellenemedi. Yetki ve bağlantı bilgilerini kontrol et.", "danger")
    return redirect(url_for("dashboard.yemeksepeti_setup"))


def _ys_setup_context(intg: Integration = None) -> dict:
    return {
        "ys_webhook_url": url_for("webhooks.yemeksepeti_order", _external=True),
        "ys_token_ready": bool(current_app.config.get("YEMEKSEPETI_WEBHOOK_TOKEN")),
        "ys_live_base": ys.api_base("live"),
        "ys_sandbox_base": ys.api_base("sandbox"),
        "ys_oauth_ready": bool(intg and intg._ys_client_id and intg._ys_client_secret),
    }


@dashboard_bp.route("/hepsiburada", methods=["GET", "POST"])
@login_required
def hepsiburada_setup():
    intg = Integration.query.filter_by(user_id=current_user.id, platform=hb.PLATFORM).first()

    if request.method == "POST":
        merchant_id = request.form.get("merchant_id", "").strip()
        username = request.form.get("username", "").strip()
        service_key = request.form.get("service_key", "").strip()
        environment = request.form.get("environment", "live").strip()
        auto_packaging = "auto_packaging" in request.form
        has_saved_service_key = bool(intg and intg._hb_service_key)

        if environment not in ("test", "live"):
            environment = "live"

        if not _can_enable_platform(intg):
            flash("Ücretsiz planda 1 platform bağlayabilirsin. WhatsApp ve çoklu platform için Pro plana geç.", "warning")
            return render_template("dashboard/hepsiburada_setup.html", intg=intg, **_hb_setup_context(intg))

        if not merchant_id or not username or (not has_saved_service_key and not service_key):
            flash("Mağaza ID, kullanıcı adı ve servis anahtarı zorunludur.", "danger")
            return render_template("dashboard/hepsiburada_setup.html", intg=intg, **_hb_setup_context(intg))

        test_service_key = service_key or intg.hb_service_key
        ok, msg, _ = hb.test_connection(
            merchant_id,
            username,
            test_service_key,
            environment,
            _hb_api_base(environment),
        )

        if not intg:
            intg = Integration(user_id=current_user.id, platform=hb.PLATFORM)
            db.session.add(intg)

        intg.hb_merchant_id = merchant_id
        intg.hb_username = username
        if service_key:
            intg.hb_service_key = service_key
        intg.hb_environment = environment
        intg.hb_auto_packaging = auto_packaging
        intg.is_active = True
        intg.last_error = None if ok else msg[:300]
        db.session.commit()

        if ok:
            flash(f"Hepsiburada bağlandı! {msg}", "success")
        else:
            flash(f"Bilgiler kaydedildi ama API doğrulanamadı: {msg}. Yetki yeni verildiyse Hepsiburada tarafında 2 saate kadar beklemek gerekebilir.", "warning")
        if not current_user.telegram_connected:
            flash("Bildirim alabilmek için Telegram'ı da bağlayın.", "warning")
        return redirect(url_for("dashboard.hepsiburada_setup"))

    return render_template("dashboard/hepsiburada_setup.html", intg=intg, **_hb_setup_context(intg))


def _hb_api_base(environment: str) -> str:
    if environment == "test":
        return current_app.config.get("HEPSIBURADA_API_BASE_TEST")
    return current_app.config.get("HEPSIBURADA_API_BASE_LIVE")


def _hb_setup_context(intg: Integration = None) -> dict:
    environment = (intg.hb_environment if intg else "live") or "live"
    return {
        "hb_api_base_test": current_app.config.get("HEPSIBURADA_API_BASE_TEST"),
        "hb_api_base_live": current_app.config.get("HEPSIBURADA_API_BASE_LIVE"),
        "hb_active_base": _hb_api_base(environment),
        "hb_stub_base": current_app.config.get("HEPSIBURADA_STUB_API_BASE"),
    }


@dashboard_bp.route("/migros", methods=["GET", "POST"])
@login_required
def migros_setup():
    intg = Integration.query.filter_by(user_id=current_user.id, platform="migros").first()

    if request.method == "POST":
        api_key  = request.form.get("api_key", "").strip()
        store_id = request.form.get("store_id", "").strip()
        group_id = request.form.get("group_id", "").strip()
        warehouse_id = request.form.get("warehouse_id", "").strip()
        has_saved_api_key = bool(intg and intg._migros_api_key)

        if not _can_enable_platform(intg):
            flash("Ücretsiz planda 1 platform bağlayabilirsin. WhatsApp ve çoklu platform için Pro plana geç.", "warning")
            return render_template("dashboard/migros_setup.html", intg=intg, **_migros_setup_context(intg))

        if (not has_saved_api_key and not api_key) or not store_id:
            flash("Restoran API Key ve Store (Restoran) ID zorunludur.", "danger")
            return render_template("dashboard/migros_setup.html", intg=intg, **_migros_setup_context(intg))

        conflict = _find_migros_store_conflict(store_id, intg.id if intg else None)
        if conflict:
            flash("Bu Store (Restoran) ID başka bir hesapta kayıtlı. Siparişlerin yanlış hesaba düşmemesi için kayıt engellendi.", "danger")
            return render_template("dashboard/migros_setup.html", intg=intg, **_migros_setup_context(intg))

        # Bağlantıyı doğrula (GetStoreGroups — şifreleme gerektirmez, sadece api key)
        secret = current_app.config.get("MIGROS_SECRET_KEY", "")
        migros_api_base = current_app.config.get("MIGROS_API_BASE")
        test_api_key = api_key or (intg.migros_api_key if intg else None)
        if not test_api_key:
            flash("API key kayıtlarda yok. Lütfen giriniz.", "danger")
            return render_template("dashboard/migros_setup.html", intg=intg, **_migros_setup_context(intg))
        ok, msg, _ = migros.test_connection(test_api_key, secret, migros_api_base)

        if not intg:
            intg = Integration(user_id=current_user.id, platform="migros")
            db.session.add(intg)

        if api_key:
            intg.migros_api_key  = api_key
        intg.migros_store_id = store_id
        intg.migros_group_id = group_id
        intg.migros_warehouse_id = warehouse_id
        intg.is_active       = True
        db.session.commit()

        if ok:
            flash(f"✅ Migros Yemek bağlandı! {msg}", "success")
        else:
            flash(f"⚠️ Bilgiler kaydedildi ama API doğrulanamadı: {msg} "
                  f"(API base URL — test/canlı ortamı kontrol et). Webhook'lar yine de çalışır.", "warning")
        if not current_user.telegram_connected:
            flash("Bildirim alabilmek için Telegram'ı da bağlayın.", "warning")
        return redirect(url_for("dashboard.migros_setup"))

    return render_template("dashboard/migros_setup.html", intg=intg, **_migros_setup_context(intg))


@dashboard_bp.route("/migros/store-status", methods=["POST"])
@login_required
def update_migros_store_status():
    intg = Integration.query.filter_by(user_id=current_user.id, platform="migros", is_active=True).first_or_404()
    action = request.form.get("action", "").strip()
    active = action == "activate"
    if action not in {"activate", "deactivate"}:
        flash("GeÃ§ersiz Migros restoran iÅŸlemi.", "warning")
        return redirect(url_for("dashboard.migros_setup"))
    secret = current_app.config.get("MIGROS_SECRET_KEY", "")
    if not secret:
        flash("MIGROS_SECRET_KEY Railway tarafÄ±nda tanÄ±mlÄ± deÄŸil.", "danger")
        return redirect(url_for("dashboard.migros_setup"))
    try:
        migros.set_store_status(
            intg.migros_store_id,
            intg.migros_api_key,
            secret,
            current_app.config.get("MIGROS_API_BASE"),
            active=active,
            warehouse_id=intg.migros_warehouse_id,
        )
        intg.last_sync_at = datetime.utcnow()
        intg.last_error = None
        db.session.commit()
        flash("Migros restoran satÄ±ÅŸa aÃ§Ä±ldÄ±." if active else "Migros restoran satÄ±ÅŸa kapatÄ±ldÄ±.", "success")
    except Exception as e:
        intg.last_error = f"Migros restoran iÅŸlemi: {e}"[:300]
        db.session.commit()
        flash(f"Migros restoran iÅŸlemi gÃ¶nderilemedi: {e}", "danger")
    return redirect(url_for("dashboard.migros_setup"))


def _find_migros_store_conflict(store_id: str, current_integration_id: int = None) -> Integration:
    query = Integration.query.filter(
        Integration.platform == "migros",
        Integration.migros_store_id == str(store_id).strip(),
    )
    if current_integration_id:
        query = query.filter(Integration.id != current_integration_id)
    return query.first()


def _migros_setup_context(intg: Integration = None) -> dict:
    migros_api_base = current_app.config.get("MIGROS_API_BASE")
    return {
        "webhook_urls": _migros_webhook_urls(),
        "migros_api_base": migros_api_base,
        "go_live_checks": _migros_go_live_checks(intg, migros_api_base),
    }


def _migros_go_live_checks(intg: Integration = None, migros_api_base: str = "") -> list:
    webhook_urls = _migros_webhook_urls()
    auth_ready = bool(current_app.config.get("MIGROS_WEBHOOK_USER") and current_app.config.get("MIGROS_WEBHOOK_PASS"))
    has_https = all(str(url).startswith("https://") for url in webhook_urls.values())
    has_store_id = bool(intg and intg.migros_store_id)
    has_api_key = bool(intg and intg._migros_api_key)
    has_sync = bool(intg and intg.last_sync_at)
    has_error = bool(intg and intg.last_error)
    duplicate = _find_migros_store_conflict(intg.migros_store_id, intg.id) if has_store_id else None

    return [
        {
            "label": "Webhook URL",
            "state": "ok" if has_https else "warn",
            "text": "HTTPS adresler hazır" if has_https else "Webhook adreslerini HTTPS olarak paylaşın",
        },
        {
            "label": "Basic Auth",
            "state": "ok" if auth_ready else "danger",
            "text": "Kullanıcı/parola tanımlı" if auth_ready else "MIGROS_WEBHOOK_USER/PASS eksik",
        },
        {
            "label": "Store ID eşleşmesi",
            "state": "ok" if has_store_id and not duplicate else ("danger" if duplicate else "warn"),
            "text": "Bu hesaba bağlı ve tekil" if has_store_id and not duplicate else ("Başka hesapta da kayıtlı" if duplicate else "Store ID henüz girilmedi"),
        },
        {
            "label": "API doğrulama",
            "state": "ok" if has_api_key else "warn",
            "text": f"Base URL: {migros_api_base}" if has_api_key else "Restoran API Key kaydedilmedi",
        },
        {
            "label": "Son webhook",
            "state": "ok" if has_sync else "warn",
            "text": intg.last_sync_at.strftime("%d.%m.%Y %H:%M") if has_sync else "Henüz webhook alınmadı",
        },
        {
            "label": "Son hata",
            "state": "danger" if has_error else "ok",
            "text": intg.last_error if has_error else "Hata yok",
        },
    ]


def _migros_webhook_urls():
    """Migros'a iletilecek FİRMA seviyesi webhook URL'leri (herkes için aynı)."""
    return {
        "order_created":  url_for("webhooks.migros_order_created", _external=True),
        "order_canceled": url_for("webhooks.migros_order_canceled", _external=True),
        "delivery_status": url_for("webhooks.migros_delivery_status", _external=True),
    }


@dashboard_bp.route("/getir", methods=["GET", "POST"])
@login_required
def getir_setup():
    intg = Integration.query.filter_by(user_id=current_user.id, platform="getir").first()

    if request.method == "POST":
        restaurant_id = request.form.get("restaurant_id", "").strip()
        restaurant_name = request.form.get("restaurant_name", "").strip()
        restaurant_secret_key = request.form.get("restaurant_secret_key", "").strip()
        has_saved_secret = bool(intg and intg._getir_restaurant_secret_key)

        if not _can_enable_platform(intg):
            flash("Ücretsiz planda 1 platform bağlayabilirsin. WhatsApp ve çoklu platform için Pro plana geç.", "warning")
            return render_template("dashboard/getir_setup.html", intg=intg, **_getir_setup_context(intg))

        if not restaurant_secret_key and not has_saved_secret:
            flash("Restaurant Secret Key zorunludur.", "danger")
            return render_template("dashboard/getir_setup.html", intg=intg, **_getir_setup_context(intg))

        conflict = _find_getir_restaurant_conflict(restaurant_id, restaurant_secret_key, intg.id if intg else None)
        if conflict:
            flash("Bu Getir restoran bilgisi başka bir hesapta kayıtlı. Siparişlerin yanlış hesaba düşmemesi için kayıt engellendi.", "danger")
            return render_template("dashboard/getir_setup.html", intg=intg, **_getir_setup_context(intg))

        if not intg:
            intg = Integration(user_id=current_user.id, platform="getir")
            db.session.add(intg)

        if restaurant_id:
            intg.getir_restaurant_id = restaurant_id
        if restaurant_name:
            intg.getir_restaurant_name = restaurant_name
        if restaurant_secret_key:
            intg.getir_restaurant_secret_key = restaurant_secret_key
        intg.is_active = True
        db.session.commit()

        if current_app.config.get("GETIR_APP_SECRET_KEY") and restaurant_secret_key:
            try:
                login_response = getir.login(
                    current_app.config.get("GETIR_APP_SECRET_KEY"),
                    restaurant_secret_key,
                    current_app.config.get("GETIR_API_BASE"),
                )
                restaurant_info = getir.restaurant_info_from_login_response(login_response)
                if restaurant_info.get("restaurant_id") and not intg.getir_restaurant_id:
                    intg.getir_restaurant_id = restaurant_info["restaurant_id"]
                if restaurant_info.get("restaurant_name") and not intg.getir_restaurant_name:
                    intg.getir_restaurant_name = restaurant_info["restaurant_name"]
                intg.last_error = None
                db.session.commit()
                flash("✅ Getir Yemek bağlandı! API bilgileri doğrulandı.", "success")
            except Exception as e:
                intg.last_error = str(e)[:300]
                db.session.commit()
                flash(f"⚠️ Bilgiler kaydedildi ama API doğrulanamadı: {e}", "warning")
        else:
            flash("✅ Getir Yemek bilgileri kaydedildi. Webhook'lar bu restoran bilgisiyle eşleşecek.", "success")

        if not current_user.telegram_connected:
            flash("Bildirim alabilmek için Telegram'ı da bağlayın.", "warning")
        return redirect(url_for("dashboard.getir_setup"))

    return render_template("dashboard/getir_setup.html", intg=intg, **_getir_setup_context(intg))


def _find_getir_restaurant_conflict(restaurant_id: str = "", restaurant_secret_key: str = "", current_integration_id: int = None) -> Integration:
    if restaurant_id:
        query = Integration.query.filter(
            Integration.platform == "getir",
            Integration.getir_restaurant_id == str(restaurant_id).strip(),
        )
        if current_integration_id:
            query = query.filter(Integration.id != current_integration_id)
        found = query.first()
        if found:
            return found

    if restaurant_secret_key:
        for intg in Integration.query.filter(Integration.platform == "getir").all():
            if current_integration_id and intg.id == current_integration_id:
                continue
            if intg.getir_restaurant_secret_key and intg.getir_restaurant_secret_key == restaurant_secret_key:
                return intg
    return None


def _getir_setup_context(intg: Integration = None) -> dict:
    return {
        "webhook_urls": _getir_webhook_urls(),
        "getir_api_base": current_app.config.get("GETIR_API_BASE"),
        "go_live_checks": _getir_go_live_checks(intg),
    }


def _getir_go_live_checks(intg: Integration = None) -> list:
    webhook_urls = _getir_webhook_urls()
    has_https = all(str(url).startswith("https://") for url in webhook_urls.values())
    has_webhook_key = bool(current_app.config.get("GETIR_WEBHOOK_API_KEY"))
    has_app_secret = bool(current_app.config.get("GETIR_APP_SECRET_KEY"))
    has_match_key = bool(intg and (intg.getir_restaurant_id or intg._getir_restaurant_secret_key))
    has_sync = bool(intg and intg.last_sync_at)
    has_error = bool(intg and intg.last_error)
    return [
        {"label": "Webhook URL", "state": "ok" if has_https else "warn", "text": "HTTPS adresler hazır" if has_https else "Webhook adreslerini HTTPS olarak paylaşın"},
        {"label": "x-api-key", "state": "ok" if has_webhook_key else "danger", "text": "GETIR_WEBHOOK_API_KEY tanımlı" if has_webhook_key else "Railway GETIR_WEBHOOK_API_KEY eksik"},
        {"label": "Restoran eşleşmesi", "state": "ok" if has_match_key else "warn", "text": "Restoran bilgisi kayıtlı" if has_match_key else "Restoran ID veya secret key henüz girilmedi"},
        {"label": "API doğrulama", "state": "ok" if has_app_secret else "warn", "text": f"Base URL: {current_app.config.get('GETIR_API_BASE')}" if has_app_secret else "GETIR_APP_SECRET_KEY gelince doğrulama açılır"},
        {"label": "Son webhook", "state": "ok" if has_sync else "warn", "text": intg.last_sync_at.strftime("%d.%m.%Y %H:%M") if has_sync else "Henüz webhook alınmadı"},
        {"label": "Son hata", "state": "danger" if has_error else "ok", "text": intg.last_error if has_error else "Hata yok"},
    ]


def _getir_webhook_urls():
    return {
        "order_created": url_for("webhooks.getir_order_created", _external=True),
        "order_canceled": url_for("webhooks.getir_order_canceled", _external=True),
        "courier_status": url_for("webhooks.getir_courier_status", _external=True),
        "restaurant_status": url_for("webhooks.getir_restaurant_status", _external=True),
    }


@dashboard_bp.route("/entegrasyon/<int:intg_id>/durum", methods=["POST"])
@login_required
def toggle_integration(intg_id):
    intg = Integration.query.filter_by(id=intg_id, user_id=current_user.id).first_or_404()
    if not intg.is_active and not _can_enable_platform(intg):
        flash("Ücretsiz planda aynı anda 1 platform aktif olabilir. Çoklu platform için Pro plana geç.", "warning")
        return redirect(url_for("dashboard.index"))
    intg.is_active = not intg.is_active
    db.session.commit()
    flash(f"Entegrasyon {'aktif' if intg.is_active else 'pasif'} edildi.", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/entegrasyon/<int:intg_id>/sil", methods=["POST"])
@login_required
def delete_integration(intg_id):
    intg = Integration.query.filter_by(id=intg_id, user_id=current_user.id).first_or_404()
    db.session.delete(intg)
    db.session.commit()
    flash("Entegrasyon silindi.", "info")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/entegrasyon/<int:intg_id>/bildirimler", methods=["POST"])
@login_required
def update_notifications(intg_id):
    intg = Integration.query.filter_by(id=intg_id, user_id=current_user.id).first_or_404()
    intg.notify_new_order      = "notify_new_order" in request.form
    intg.notify_status_change  = "notify_status_change" in request.form
    intg.notify_cancel         = "notify_cancel" in request.form
    intg.notify_daily_report   = "notify_daily_report" in request.form
    intg.notify_weekly_report  = "notify_weekly_report" in request.form
    intg.notify_monthly_report = "notify_monthly_report" in request.form
    db.session.commit()
    flash("Bildirim tercihleri güncellendi.", "success")
    return redirect(url_for("dashboard.index"))


# ── Siparişler ──────────────────────────────────────────────────────────────

@dashboard_bp.route("/siparisler")
@login_required
def orders():
    page     = request.args.get("page", 1, type=int)
    platform = request.args.get("platform", "")
    q = Order.query.filter_by(user_id=current_user.id)
    if platform:
        q = q.filter_by(platform=platform)
    orders_paged = q.order_by(Order.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template("dashboard/orders.html", orders=orders_paged, platform=platform)


@dashboard_bp.route("/raporlar")
@login_required
def reports():
    period = request.args.get("period", "daily").strip() or "daily"
    platform = request.args.get("platform", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    start_date, end_date, period_label = _report_date_range(period, date_from, date_to)
    query = Order.query.filter_by(user_id=current_user.id)
    if platform:
        query = query.filter_by(platform=platform)
    query = _apply_report_date_filter(query, start_date, end_date)
    orders = query.order_by(Order.created_at.desc()).all()
    summary = _build_report_summary(orders)

    return render_template(
        "dashboard/reports.html",
        summary=summary,
        orders=orders[:50],
        filters={
            "period": period,
            "platform": platform,
            "date_from": start_date.isoformat(),
            "date_to": end_date.isoformat(),
        },
        period_label=period_label,
    )


@dashboard_bp.route("/istatistikler")
@login_required
def analytics():
    period = request.args.get("period", "30").strip() or "30"
    platform = request.args.get("platform", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    start_date, end_date, period_label = _analytics_date_range(period, date_from, date_to)
    query = Order.query.filter_by(user_id=current_user.id)
    if platform:
        query = query.filter_by(platform=platform)
    query = _apply_report_date_filter(query, start_date, end_date)
    orders = query.order_by(Order.created_at.desc()).all()
    summary = _build_analytics_summary(orders, start_date, end_date)
    previous_start, previous_end = _previous_calendar_week(end_date)
    current_week_start = end_date - timedelta(days=end_date.weekday())
    current_week_query = Order.query.filter_by(user_id=current_user.id)
    if platform:
        current_week_query = current_week_query.filter_by(platform=platform)
    current_week_query = _apply_report_date_filter(current_week_query, current_week_start, end_date)
    current_week = _build_previous_week_summary(
        current_week_query.all(),
        current_week_start,
        week_end=end_date,
    )
    previous_query = Order.query.filter_by(user_id=current_user.id)
    if platform:
        previous_query = previous_query.filter_by(platform=platform)
    previous_query = _apply_report_date_filter(previous_query, previous_start, previous_end)
    previous_week = _build_previous_week_summary(previous_query.all(), previous_start)
    week_comparison = _build_week_comparison(current_week, previous_week)

    return render_template(
        "dashboard/analytics.html",
        summary=summary,
        current_week=current_week,
        previous_week=previous_week,
        week_comparison=week_comparison,
        filters={
            "period": period,
            "platform": platform,
            "date_from": start_date.isoformat(),
            "date_to": end_date.isoformat(),
        },
        period_label=period_label,
    )


@dashboard_bp.route("/abonelik")
@login_required
def subscription():
    integrations = Integration.query.filter_by(user_id=current_user.id).all()
    active_integrations = [i for i in integrations if i.is_active]
    return render_template(
        "dashboard/subscription.html",
        integrations=integrations,
        active_integrations=active_integrations,
    )


@dashboard_bp.route("/siparis/<int:order_id>")
@login_required
def order_detail(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    detail = _order_detail_context(order)
    migros_actions = _migros_order_actions(order, detail)
    migros_intg = Integration.query.filter_by(user_id=current_user.id, platform="migros", is_active=True).first() if order.platform == "migros" else None
    getir_actions = _getir_order_actions(order, detail)
    yemeksepeti_actions = _yemeksepeti_order_actions(order, detail)
    trendyolgo_actions = _tgo_order_actions(order, detail)
    return render_template(
        "dashboard/order_detail.html",
        order=order,
        detail=detail,
        migros_actions=migros_actions,
        migros_cancel_reasons=_migros_cancel_reasons(migros_intg) if migros_actions else [],
        getir_actions=getir_actions,
        yemeksepeti_actions=yemeksepeti_actions,
        trendyolgo_actions=trendyolgo_actions,
    )


def _order_action_redirect(order: Order):
    if request.form.get("return_to") == "active_orders":
        return_path = request.form.get("return_path", "")
        active_path = url_for("dashboard.active_orders")
        if return_path.startswith(active_path):
            return redirect(return_path)
        return redirect(active_path)
    return redirect(url_for("dashboard.order_detail", order_id=order.id))


@dashboard_bp.route("/siparis/<int:order_id>/getir-durum", methods=["POST"])
@login_required
def update_getir_order_status(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id, platform="getir").first_or_404()
    action = request.form.get("action", "").strip()
    detail = _order_detail_context(order)
    actions = {item["action"]: item for item in _getir_order_actions(order, detail)}
    selected = actions.get(action)
    if not selected:
        flash("Bu sipariş durumu için Getir işlemi kullanılamaz.", "warning")
        return _order_action_redirect(order)
    if selected.get("disabled"):
        flash(selected.get("disabled_reason") or "Bu islem icin biraz beklemek gerekiyor.", "warning")
        return _order_action_redirect(order)

    intg = Integration.query.filter_by(user_id=current_user.id, platform="getir", is_active=True).first()
    if not intg or not intg.getir_restaurant_secret_key:
        flash("Getir bağlantısı eksik. Önce Restaurant Secret Key kaydedilmeli.", "danger")
        return _order_action_redirect(order)
    if not current_app.config.get("GETIR_APP_SECRET_KEY"):
        flash("GETIR_APP_SECRET_KEY Railway tarafında tanımlı değil.", "danger")
        return _order_action_redirect(order)

    try:
        getir.update_order_status(
            order.external_id,
            action,
            current_app.config.get("GETIR_APP_SECRET_KEY"),
            intg.getir_restaurant_secret_key,
            current_app.config.get("GETIR_API_BASE"),
        )
        order.status = selected["next_status"]
        db.session.commit()
        flash(f"Getir siparişi güncellendi: {selected['label']}", "success")
    except Exception as e:
        intg.last_error = str(e)[:300]
        db.session.commit()
        flash(f"Getir işlemi başarısız: {e}", "danger")
    return _order_action_redirect(order)


@dashboard_bp.route("/siparis/<int:order_id>/trendyolgo-aksiyon", methods=["POST"])
@login_required
def update_trendyolgo_order(order_id):
    order = (
        Order.query.filter_by(id=order_id, user_id=current_user.id)
        .filter(Order.platform.in_([TGO_FOOD_PLATFORM, TGO_MARKET_PLATFORM]))
        .first_or_404()
    )
    action = request.form.get("action", "").strip()
    detail = _order_detail_context(order)
    selected = {item["action"]: item for item in _tgo_order_actions(order, detail)}.get(action)
    if not selected:
        flash("Bu Trendyol Go siparisi icin islem kullanilamaz.", "warning")
        return _order_action_redirect(order)

    intg = Integration.query.filter_by(user_id=current_user.id, platform=order.platform, is_active=True).first()
    if not intg or not intg.tgo_supplier_id or not intg.tgo_api_key or not intg.tgo_api_secret:
        flash("Trendyol Go API bilgileri eksik.", "danger")
        return _order_action_redirect(order)

    try:
        tgo.update_package_status(
            intg.tgo_supplier_id,
            intg.tgo_api_key,
            intg.tgo_api_secret,
            order.external_id,
            selected["api_action"],
            total_price=order.total_price,
            service=_tgo_service_for_platform(order.platform),
        )
        raw = detail.get("raw") or {}
        order.status = selected["next_status"]
        raw["packageStatus"] = selected["next_status"]
        raw["status"] = selected["next_status"]
        order.raw_json = json.dumps(raw, ensure_ascii=False)
        intg.last_sync_at = datetime.utcnow()
        intg.last_error = None
        db.session.commit()
        flash(f"Trendyol Go islemi gonderildi: {selected['label']}", "success")
    except Exception as e:
        intg.last_error = f"Trendyol Go siparis islemi: {e}"[:300]
        db.session.commit()
        flash(f"Trendyol Go islemi gonderilemedi: {e}", "danger")
    return _order_action_redirect(order)


@dashboard_bp.route("/siparis/<int:order_id>/migros-aksiyon", methods=["POST"])
@login_required
def update_migros_order(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id, platform="migros").first_or_404()
    action = request.form.get("action", "").strip()
    detail = _order_detail_context(order)
    actions = {item["action"]: item for item in _migros_order_actions(order, detail)}
    selected = actions.get(action)
    if not selected:
        flash("Bu Migros sipariÅŸi iÃ§in iÅŸlem kullanÄ±lamaz.", "warning")
        return _order_action_redirect(order)

    intg = Integration.query.filter_by(user_id=current_user.id, platform="migros", is_active=True).first()
    if not intg or not intg.migros_api_key or not intg.migros_store_id:
        flash("Migros API Key ve Store ID bilgileri eksik.", "danger")
        return _order_action_redirect(order)
    secret = current_app.config.get("MIGROS_SECRET_KEY", "")
    if not secret:
        flash("MIGROS_SECRET_KEY Railway tarafÄ±nda tanÄ±mlÄ± deÄŸil.", "danger")
        return _order_action_redirect(order)

    raw = detail.get("raw") or {}
    base_url = current_app.config.get("MIGROS_API_BASE")
    cancel_reason_id = request.form.get("cancel_reason_id", "").strip()
    if action in {"reject", "cancel"} and not cancel_reason_id:
        flash("Migros red/iptal iÅŸlemi iÃ§in iptal sebebi seÃ§ilmelidir.", "warning")
        return _order_action_redirect(order)

    try:
        if action == "cancel":
            user_id = _migros_user_id(raw)
            if not user_id:
                flash("Migros iptal iÅŸlemi iÃ§in sipariÅŸ payload'unda User ID bulunamadÄ±.", "danger")
                return _order_action_redirect(order)
            migros.cancel_order(
                order.external_id,
                intg.migros_store_id,
                user_id,
                cancel_reason_id,
                intg.migros_api_key,
                secret,
                base_url,
            )
            next_status = "Cancelled"
        else:
            next_status = selected["next_status"]
            migros.update_order_status(
                order.external_id,
                next_status,
                intg.migros_store_id,
                intg.migros_api_key,
                secret,
                cancel_reason_id=cancel_reason_id if action == "reject" else None,
                base_url=base_url,
            )
        order.status = next_status
        raw["status"] = next_status
        order.raw_json = json.dumps(raw, ensure_ascii=False)
        intg.last_sync_at = datetime.utcnow()
        intg.last_error = None
        db.session.commit()
        flash(f"Migros iÅŸlemi gÃ¶nderildi: {selected['label']}", "success")
    except Exception as e:
        intg.last_error = f"Migros sipariÅŸ iÅŸlemi: {e}"[:300]
        db.session.commit()
        flash(f"Migros iÅŸlemi gÃ¶nderilemedi: {e}", "danger")
    return _order_action_redirect(order)


@dashboard_bp.route("/siparis/<int:order_id>/yemeksepeti-aksiyon", methods=["POST"])
@login_required
def update_yemeksepeti_order(order_id):
    order = Order.query.filter_by(
        id=order_id, user_id=current_user.id, platform=ys.PLATFORM
    ).first_or_404()
    action = request.form.get("action", "").strip()
    selected = {item["action"]: item for item in _yemeksepeti_order_actions(order)}.get(action)
    if not selected:
        flash("Bu Yemeksepeti siparişi için işlem kullanılamaz.", "warning")
        return _order_action_redirect(order)
    if selected.get("disabled"):
        flash(selected.get("disabled_reason") or "Bu işlem şu anda kullanılamıyor.", "warning")
        return _order_action_redirect(order)

    intg = Integration.query.filter_by(
        user_id=current_user.id, platform=ys.PLATFORM, is_active=True
    ).first()
    if not intg or not intg.ys_chain_id or not (intg.ys_vendor_id or intg.ys_store_id):
        flash("Yemeksepeti Chain ID ve Vendor/Store ID bilgileri eksik.", "danger")
        return _order_action_redirect(order)
    if not intg.ys_client_id or not intg.ys_client_secret:
        flash("Yemeksepeti OAuth bilgileri henüz kaydedilmemiş.", "danger")
        return _order_action_redirect(order)

    raw = _parse_raw_json(order.raw_json)
    if action == "fulfill":
        next_status = ys.fulfillment_status(raw)
        body = ys.build_order_update_payload(raw, next_status)
    elif action == "cancel":
        reason = request.form.get("cancel_reason", "TOO_BUSY").strip().upper()
        if reason not in {"CLOSED", "ITEM_UNAVAILABLE", "TOO_BUSY"}:
            reason = "TOO_BUSY"
        next_status = ys.STATUS_CANCELLED
        body = ys.build_order_update_payload(raw, next_status, reason)
    else:
        flash("Geçersiz Yemeksepeti işlemi.", "warning")
        return _order_action_redirect(order)

    try:
        ys.update_order(
            intg.ys_chain_id,
            order.external_id,
            body,
            intg.ys_client_id,
            intg.ys_client_secret,
            intg.ys_environment or "live",
        )
        order.status = next_status
        raw["status"] = next_status
        order.raw_json = json.dumps(raw, ensure_ascii=False)
        intg.last_sync_at = datetime.utcnow()
        intg.last_error = None
        db.session.commit()
        flash("Yemeksepeti sipariş işlemi gönderildi. Son durum webhook ile güncellenecek.", "success")
    except Exception as e:
        intg.last_error = f"Yemeksepeti sipariş işlemi: {e}"[:300]
        db.session.commit()
        flash("Yemeksepeti sipariş işlemi gönderilemedi. Bağlantı ve yetkileri kontrol et.", "danger")
    return _order_action_redirect(order)


@dashboard_bp.route("/aktif-siparisler")
@login_required
def active_orders():
    page = request.args.get("page", 1, type=int)
    platform = request.args.get("platform", "").strip()
    status_group = request.args.get("durum", "aktif").strip() or "aktif"
    search = request.args.get("q", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    base_query = Order.query.filter_by(user_id=current_user.id)
    base_query = _apply_active_common_filters(base_query, platform, search, date_from, date_to)
    query = base_query

    now = datetime.utcnow()
    query = _apply_status_group_filter(query, status_group, now)

    filtered_total = query.with_entities(func.coalesce(func.sum(Order.total_price), 0)).scalar() or 0
    orders_paged = query.order_by(Order.created_at.desc()).paginate(page=page, per_page=30, error_out=False)
    rows = [_active_order_row(order, now, include_quick_action=True) for order in orders_paged.items]

    all_user_orders = base_query.with_entities(Order.status, Order.created_at).all()
    counts = _active_order_counts(all_user_orders, now)
    latest_order_id = db.session.query(func.max(Order.id)).filter_by(user_id=current_user.id).scalar() or 0

    return render_template(
        "dashboard/active_orders.html",
        orders=orders_paged,
        rows=rows,
        counts=counts,
        filtered_total=filtered_total,
        latest_order_id=latest_order_id,
        filters={
            "platform": platform,
            "durum": status_group,
            "q": search,
            "date_from": date_from,
            "date_to": date_to,
        },
        groups=_status_group_options(),
    )


@dashboard_bp.route("/aktif-siparisler/yeni-kontrol")
@login_required
def active_orders_check():
    """Aktif ekran açik kalirken kullanicinin yeni siparislerini döndürür."""
    since_id = request.args.get("since_id", 0, type=int) or 0
    latest_order_id = db.session.query(func.max(Order.id)).filter_by(user_id=current_user.id).scalar() or 0
    if latest_order_id <= since_id:
        return jsonify({"latest_id": latest_order_id, "orders": []})

    new_orders = (
        Order.query
        .filter(Order.user_id == current_user.id, Order.id > since_id)
        .filter(or_(Order.status.is_(None), ~Order.status.in_(sorted(ACTIVE_EXCLUDED_STATUSES))))
        .order_by(Order.id.asc())
        .limit(20)
        .all()
    )
    if not new_orders:
        return jsonify({"latest_id": latest_order_id, "orders": []})
    payload = []
    for order in new_orders:
        raw = _parse_raw_json(order.raw_json)
        payload.append({
            "id": order.id,
            "order_number": order.order_number or order.external_id or str(order.id),
            "platform": platform_label(order.platform),
            "status": status_label(order.status),
            "items": _active_order_items_summary(order, raw),
            "total": f"{float(order.total_price or 0):.2f} TL",
            "created_at": order.created_at.strftime("%d.%m.%Y %H:%M") if order.created_at else "",
            "url": url_for("dashboard.order_detail", order_id=order.id),
        })
    next_since_id = new_orders[-1].id if len(new_orders) >= 20 else latest_order_id
    return jsonify({"latest_id": next_since_id, "orders": payload})


def _apply_active_common_filters(query, platform: str, search: str, date_from: str, date_to: str):
    if platform:
        query = query.filter_by(platform=platform)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            Order.order_number.ilike(like),
            Order.external_id.ilike(like),
            Order.customer_note.ilike(like),
        ))

    start_dt = _parse_date_start(date_from)
    end_dt = _parse_date_end(date_to)
    if date_from and not start_dt:
        flash("Başlangıç tarihi okunamadı.", "warning")
    if date_to and not end_dt:
        flash("Bitiş tarihi okunamadı.", "warning")
    if start_dt:
        query = query.filter(Order.created_at >= start_dt)
    if end_dt:
        query = query.filter(Order.created_at < end_dt)
    return query


def _apply_status_group_filter(query, group: str, now: datetime):
    if group == "geciken":
        warning_before = now - timedelta(seconds=UNACCEPTED_WARNING_SECONDS)
        return query.filter(Order.status.in_(sorted(PENDING_STATUSES)), Order.created_at <= warning_before)

    status_filter = _status_filter(group)
    if status_filter["include"]:
        query = query.filter(Order.status.in_(sorted(status_filter["include"])))
    if status_filter["exclude"]:
        query = query.filter(or_(Order.status.is_(None), ~Order.status.in_(sorted(status_filter["exclude"]))))
    return query


def _parse_date_start(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


def _parse_date_end(value: str):
    start = _parse_date_start(value)
    return start + timedelta(days=1) if start else None


def _status_filter(group: str) -> dict:
    if group == "bekleyen":
        return {"include": PENDING_STATUSES, "exclude": set()}
    if group == "hazirlaniyor":
        return {"include": PREPARING_STATUSES, "exclude": set()}
    if group == "yolda":
        return {"include": DELIVERY_STATUSES, "exclude": set()}
    if group == "sorunlu":
        return {"include": PROBLEM_STATUSES, "exclude": set()}
    if group == "iptal":
        return {"include": CANCELLED_STATUSES, "exclude": set()}
    if group == "iade":
        return {"include": REFUNDED_STATUSES, "exclude": set()}
    if group == "tamamlanan":
        return {"include": DONE_STATUSES, "exclude": set()}
    if group == "tumu":
        return {"include": set(), "exclude": set()}
    return {"include": set(), "exclude": ACTIVE_EXCLUDED_STATUSES}


def _status_group_options() -> list:
    return [
        ("aktif", "Aktif"),
        ("bekleyen", "Kabul bekleyen"),
        ("geciken", "Kabul geciken"),
        ("hazirlaniyor", "Hazırlanıyor"),
        ("yolda", "Yolda"),
        ("sorunlu", "Sorunlu"),
        ("iptal", "İptal"),
        ("iade", "İade"),
        ("tamamlanan", "Tamamlanan"),
        ("tumu", "Tümü"),
    ]


def _active_order_row(order: Order, now: datetime, include_quick_action: bool = False) -> dict:
    age_seconds = int((now - order.created_at).total_seconds()) if order.created_at else 0
    is_pending = order.status in PENDING_STATUSES
    row = {
        "order": order,
        "age_minutes": max(0, age_seconds // 60),
        "is_unaccepted_warning": is_pending and age_seconds >= UNACCEPTED_WARNING_SECONDS,
        "group": _order_group(order.status),
    }
    if include_quick_action:
        raw = _parse_raw_json(order.raw_json)
        row["items_summary"] = _active_order_items_summary(order, raw)
        row["quick_action"] = _quick_accept_action(order, raw)
    return row


def _active_order_items_summary(order: Order, raw: dict) -> str:
    try:
        if order.platform == "migros":
            return migros.summarize_items_for_display(raw, max_items=3)
        if order.platform == "getir":
            return getir.summarize_items(raw, max_items=3)
        if order.platform in {TGO_FOOD_PLATFORM, TGO_MARKET_PLATFORM}:
            return tgo.summarize_items(raw, max_items=3)
        if order.platform == tmp.PLATFORM:
            return tmp.summarize_items(raw, max_items=3)
        if order.platform == hb.PLATFORM:
            return hb.summarize_items(raw, max_items=3)
        if order.platform == ys.PLATFORM:
            return ys.summarize_items(raw, max_items=3)
    except Exception:
        pass
    return "-"


def _quick_accept_action(order: Order, raw: dict) -> dict:
    if order.status in ACTIVE_EXCLUDED_STATUSES:
        return None

    if order.platform == "migros" and order.status in {"NEW_PENDING", "Created", "Pending", "New", ""}:
        return {
            "endpoint": "dashboard.update_migros_order",
            "action": "approve",
            "label": "Kabul et",
        }

    if order.platform == "getir":
        action = "verify_scheduled" if order.status == "Scheduled" else "verify"
        if order.status in {"Scheduled", "Created", "NEW_PENDING", "Pending", "New"}:
            return {
                "endpoint": "dashboard.update_getir_order_status",
                "action": action,
                "label": "Kabul et",
            }

    if order.platform in {TGO_FOOD_PLATFORM, TGO_MARKET_PLATFORM}:
        package_status = raw.get("packageStatus") or raw.get("status") or order.status
        if package_status in {"Created", "NEW_PENDING", "Pending", "New", ""}:
            return {
                "endpoint": "dashboard.update_trendyolgo_order",
                "action": "pick",
                "label": "Kabul et",
            }

    if order.platform == ys.PLATFORM and order.status == ys.STATUS_RECEIVED:
        return {
            "endpoint": "dashboard.update_yemeksepeti_order",
            "action": "fulfill",
            "label": "Hazırla / kabul et",
        }

    return None


def _active_order_counts(orders: list, now: datetime) -> dict:
    counts = {
        "active": 0,
        "pending": 0,
        "preparing": 0,
        "delivery": 0,
        "problem": 0,
        "cancelled": 0,
        "refunded": 0,
        "done": 0,
        "warning": 0,
    }
    for order in orders:
        group = _order_group(order.status)
        if group in counts:
            counts[group] += 1
        if order.status in CANCELLED_STATUSES:
            counts["cancelled"] += 1
        if order.status in REFUNDED_STATUSES:
            counts["refunded"] += 1
        if order.status not in ACTIVE_EXCLUDED_STATUSES:
            counts["active"] += 1
        if _active_order_row(order, now)["is_unaccepted_warning"]:
            counts["warning"] += 1
    return counts


def _getir_order_actions(order: Order, detail: dict = None) -> list:
    if order.platform != "getir" or order.status in ACTIVE_EXCLUDED_STATUSES:
        return []
    detail = detail or _order_detail_context(order)
    raw = detail.get("raw") or {}
    delivery_type = getir._as_int(getir._first(raw, "deliveryType", "deliveryProvider"))
    status = order.status or ""
    actions = []

    if status == "Scheduled":
        actions.append({"action": "verify_scheduled", "label": "İleri tarihli onayla", "next_status": "ScheduledApproved"})
    elif status in {"Created", "NEW_PENDING", "Pending", "New"}:
        actions.append({"action": "verify", "label": "Onayla", "next_status": "Approved"})
    elif status in {"Approved", "ScheduledApproved"}:
        actions.append({"action": "prepare", "label": "Hazırlanıyor yap", "next_status": "Picking"})
    elif status in {"Picking", "Prepared"}:
        if delivery_type == 1:
            actions.append({"action": "handover", "label": "Getir kuryesine teslim", "next_status": "Shipped"})
        else:
            actions.append({"action": "deliver", "label": "Teslim edildi yap", "next_status": "Delivered"})

    if actions and order.updated_at:
        elapsed = (datetime.utcnow() - order.updated_at).total_seconds()
        if status not in {"Created", "NEW_PENDING", "Pending", "New", "Scheduled"} and elapsed < 60:
            remaining = max(1, int(60 - elapsed))
            for item in actions:
                item["disabled"] = True
                item["disabled_reason"] = f"Getir kuralı gereği sonraki işlem için {remaining} sn bekle."
    return actions


def _tgo_order_actions(order: Order, detail: dict = None) -> list:
    if order.platform not in {TGO_FOOD_PLATFORM, TGO_MARKET_PLATFORM} or str(order.external_id or "").startswith("claim:"):
        return []
    status = order.status or ""
    raw = (detail or {}).get("raw") or _parse_raw_json(order.raw_json)
    package_status = raw.get("packageStatus") or raw.get("status") or status
    actions = []
    if package_status in {"Created", "NEW_PENDING", "Pending", "New", ""}:
        actions.append({
            "action": "pick",
            "api_action": "pick",
            "label": "Siparisi onayla",
            "next_status": "Picking",
        })
    elif package_status == "Picking":
        actions.append({
            "action": "invoice",
            "api_action": "invoice",
            "label": "Hazirlandi yap",
            "next_status": "Invoiced",
        })
    elif package_status == "Invoiced" and order.platform == TGO_FOOD_PLATFORM:
        actions.append({
            "action": "ship",
            "api_action": "ship",
            "label": "Yola cikti yap",
            "next_status": "Shipped",
        })
    elif package_status == "Shipped" and order.platform == TGO_FOOD_PLATFORM:
        actions.append({
            "action": "deliver",
            "api_action": "deliver",
            "label": "Teslim edildi yap",
            "next_status": "Delivered",
        })
    return actions


def _yemeksepeti_order_actions(order: Order, detail: dict = None) -> list:
    if order.platform != ys.PLATFORM or order.status in ACTIVE_EXCLUDED_STATUSES:
        return []
    detail = detail or _order_detail_context(order)
    raw = detail.get("raw") or {}
    status = order.status or ys.STATUS_RECEIVED
    actions = []

    if status == ys.STATUS_RECEIVED:
        next_status = ys.fulfillment_status(raw)
        label = "Hazır olarak işaretle" if next_status == ys.STATUS_READY else "Sevk edildi yap"
        actions.append({
            "action": "fulfill",
            "label": label,
            "next_status": next_status,
        })

    if status in {ys.STATUS_RECEIVED, ys.STATUS_READY}:
        actions.append({
            "action": "cancel",
            "label": "Siparişi iptal et",
            "next_status": ys.STATUS_CANCELLED,
        })

    intg = Integration.query.filter_by(
        user_id=order.user_id, platform=ys.PLATFORM, is_active=True
    ).first()
    disabled_reason = None
    if not intg or not intg.ys_chain_id or not (intg.ys_vendor_id or intg.ys_store_id):
        disabled_reason = "Önce Chain ID ve Vendor/Store ID bilgilerini kaydet."
    elif not intg._ys_client_id or not intg._ys_client_secret:
        disabled_reason = "Yemeksepeti OAuth bilgileri geldiğinde bu işlem açılacak."
    if disabled_reason:
        for item in actions:
            item["disabled"] = True
            item["disabled_reason"] = disabled_reason
    return actions


def _migros_order_actions(order: Order, detail: dict = None) -> list:
    if order.platform != "migros" or order.status in ACTIVE_EXCLUDED_STATUSES:
        return []
    status = order.status or ""
    actions = []
    if status in {"NEW_PENDING", "Created", "Pending", "New", ""}:
        actions.append({"action": "approve", "label": "Onayla", "next_status": migros.ORDER_STATUS_APPROVED})
        actions.append({"action": "reject", "label": "Reddet", "next_status": migros.ORDER_STATUS_REJECTED, "needs_reason": True})
    elif status in {"Approved", "Prepared"}:
        if status == "Approved":
            actions.append({"action": "prepared", "label": "HazÄ±rlandÄ± yap", "next_status": migros.ORDER_STATUS_PREPARED})
        if status == "Prepared":
            actions.append({"action": "delivery", "label": "Yola Ã§Ä±ktÄ± yap", "next_status": migros.ORDER_STATUS_DELIVERY})
        actions.append({"action": "cancel", "label": "Ä°ptal et", "next_status": "Cancelled", "needs_reason": True})
    elif status == "Delivery":
        actions.append({"action": "completed", "label": "TamamlandÄ± yap", "next_status": migros.ORDER_STATUS_COMPLETED})
        actions.append({"action": "cancel", "label": "Ä°ptal et", "next_status": "Cancelled", "needs_reason": True})
    return actions


def _migros_cancel_reasons(intg: Integration = None) -> list:
    if not intg or not intg._migros_api_key:
        return []
    try:
        reasons = migros.get_cancel_reasons(intg.migros_api_key, current_app.config.get("MIGROS_API_BASE"))
    except Exception:
        return []
    cleaned = []
    for reason in reasons:
        reason_id = reason.get("reasonId") or reason.get("ReasonId") or reason.get("id")
        description = reason.get("description") or reason.get("Description") or reason.get("name") or reason.get("Name")
        if reason_id and description and "teknik" not in str(description).lower():
            cleaned.append({"reasonId": str(reason_id), "description": str(description)})
    return cleaned


def _order_group(status: str) -> str:
    if status in PENDING_STATUSES:
        return "pending"
    if status in PREPARING_STATUSES:
        return "preparing"
    if status in DELIVERY_STATUSES:
        return "delivery"
    if status in PROBLEM_STATUSES:
        return "problem"
    if status in DONE_STATUSES:
        return "done"
    return "active"


def _report_date_range(period: str, date_from: str, date_to: str):
    today = datetime.now(TURKEY_TZ).date()
    if period == "custom":
        parsed_from = _parse_date_value(date_from)
        parsed_to = _parse_date_value(date_to)
        start = parsed_from or today
        end = parsed_to or start
        if end < start:
            flash("Bitiş tarihi başlangıçtan önce olamaz; tarih aralığı düzeltilerek gösterildi.", "warning")
            start, end = end, start
        return start, end, f"{start.strftime('%d.%m.%Y')} - {end.strftime('%d.%m.%Y')}"

    if period == "weekly":
        start = today - timedelta(days=today.weekday())
        return start, today, f"{start.strftime('%d.%m.%Y')} - {today.strftime('%d.%m.%Y')}"
    if period == "monthly":
        start = today.replace(day=1)
        return start, today, start.strftime("%m.%Y")
    return today, today, today.strftime("%d.%m.%Y")


def _analytics_date_range(period: str, date_from: str, date_to: str):
    today = datetime.now(TURKEY_TZ).date()
    if period == "custom":
        start = _parse_date_value(date_from) or (today - timedelta(days=29))
        end = _parse_date_value(date_to) or today
        if end < start:
            start, end = end, start
        return start, end, f"{start.strftime('%d.%m.%Y')} - {end.strftime('%d.%m.%Y')}"

    days = {"7": 7, "30": 30, "90": 90, "365": 365}.get(period, 30)
    start = today - timedelta(days=days - 1)
    labels = {7: "Son 7 gün", 30: "Son 30 gün", 90: "Son 90 gün", 365: "Son 1 yıl"}
    return start, today, labels[days]


def _previous_calendar_week(end_date):
    current_week_start = end_date - timedelta(days=end_date.weekday())
    previous_start = current_week_start - timedelta(days=7)
    return previous_start, current_week_start - timedelta(days=1)


def _order_local_datetime(order: Order):
    value = order.created_at
    if not value:
        return None
    if value.tzinfo is None:
        value = pytz.utc.localize(value)
    return value.astimezone(TURKEY_TZ)


def _analytics_day_label(day) -> str:
    months = [
        "", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
        "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
    ]
    days = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    return f"{day.day} {months[day.month]} {days[day.weekday()]}"


def _build_previous_week_summary(orders: list, week_start, week_end=None) -> dict:
    day_names = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    rows = []
    week_end = week_end or (week_start + timedelta(days=6))
    valid_orders = [
        order for order in orders
        if not _is_cancelled_order(order) and not _is_refunded_order(order)
    ]
    day_count = max(0, (week_end - week_start).days + 1)
    for offset in range(day_count):
        day = week_start + timedelta(days=offset)
        day_name = day_names[day.weekday()]
        day_orders = []
        platform_counts = {}
        for order in valid_orders:
            local_dt = _order_local_datetime(order)
            if not local_dt or local_dt.date() != day:
                continue
            day_orders.append(order)
            platform_counts[order.platform] = platform_counts.get(order.platform, 0) + 1
        platform_text = " · ".join(
            f"{platform_label(key)} {count}"
            for key, count in sorted(platform_counts.items(), key=lambda item: item[1], reverse=True)
        )
        rows.append({
            "date": day.strftime("%d.%m.%Y"),
            "day": day_name,
            "label": _analytics_day_label(day),
            "count": len(day_orders),
            "total": _sum_orders(day_orders),
            "platforms": platform_text or "—",
        })
    return {
        "start": week_start.strftime("%d.%m.%Y"),
        "end": (week_start + timedelta(days=6)).strftime("%d.%m.%Y"),
        "rows": rows,
        "count": len(valid_orders),
        "total": _sum_orders(valid_orders),
    }


def _build_week_comparison(current_week: dict, previous_week: dict) -> list:
    rows = []
    counts = []
    for index, previous_row in enumerate(previous_week["rows"]):
        current_row = current_week["rows"][index] if index < len(current_week["rows"]) else None
        counts.extend([
            previous_row["count"],
            current_row["count"] if current_row else 0,
        ])
    max_count = max(counts, default=0)
    for index, previous_row in enumerate(previous_week["rows"]):
        current_row = current_week["rows"][index] if index < len(current_week["rows"]) else None
        current_count = current_row["count"] if current_row else 0
        previous_count = previous_row["count"]
        difference = current_count - previous_count
        if difference > 0:
            trend = "up"
            trend_label = f"+{difference}"
        elif difference < 0:
            trend = "down"
            trend_label = str(difference)
        else:
            trend = "same"
            trend_label = "Değişmedi"
        rows.append({
            "current": current_row,
            "previous": previous_row,
            "current_count": current_count,
            "previous_count": previous_count,
            "current_bar": current_count / max_count * 100 if max_count else 0,
            "previous_bar": previous_count / max_count * 100 if max_count else 0,
            "trend": trend,
            "trend_label": trend_label,
        })
    return rows


def _build_analytics_summary(orders: list, start_date, end_date) -> dict:
    cancelled = [order for order in orders if _is_cancelled_order(order)]
    refunded = [order for order in orders if _is_refunded_order(order)]
    valid = [order for order in orders if order not in cancelled and order not in refunded]
    day_names = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    day_counts = [0] * 7
    day_totals = [0.0] * 7
    day_platforms = [dict() for _ in range(7)]
    hour_counts = [0] * 24
    hour_totals = [0.0] * 24
    platform_data = {}

    occurrences = [0] * 7
    cursor = start_date
    while cursor <= end_date:
        occurrences[cursor.weekday()] += 1
        cursor += timedelta(days=1)

    for order in valid:
        local_dt = _order_local_datetime(order)
        if not local_dt:
            continue
        weekday = local_dt.weekday()
        hour = local_dt.hour
        amount = float(order.total_price or 0)
        platform_key = order.platform or "unknown"
        day_counts[weekday] += 1
        day_totals[weekday] += amount
        hour_counts[hour] += 1
        hour_totals[hour] += amount
        day_platforms[weekday][platform_key] = day_platforms[weekday].get(platform_key, 0) + 1
        bucket = platform_data.setdefault(platform_key, {"count": 0, "total": 0.0})
        bucket["count"] += 1
        bucket["total"] += amount

    total_days = max(1, (end_date - start_date).days + 1)
    average_order_value = _sum_orders(valid) / len(valid) if valid else 0
    max_day_count = max(day_counts) if day_counts else 0
    max_hour_count = max(hour_counts) if hour_counts else 0
    weekday_rows = []
    for index, name in enumerate(day_names):
        top_platform = max(day_platforms[index], key=day_platforms[index].get) if day_platforms[index] else ""
        weekday_rows.append({
            "name": name,
            "count": day_counts[index],
            "total": day_totals[index],
            "occurrences": occurrences[index],
            "average": day_counts[index] / occurrences[index] if occurrences[index] else 0,
            "top_platform": top_platform,
            "top_platform_count": day_platforms[index].get(top_platform, 0),
            "top_platform_average": day_platforms[index].get(top_platform, 0) / occurrences[index] if occurrences[index] else 0,
            "bar": (day_counts[index] / max_day_count * 100) if max_day_count else 0,
        })

    hour_rows = []
    for hour in range(24):
        hour_rows.append({
            "hour": hour,
            "label": f"{hour:02d}:00 - {(hour + 1) % 24:02d}:00",
            "count": hour_counts[hour],
            "total": hour_totals[hour],
            "average": hour_counts[hour] / total_days,
            "bar": (hour_counts[hour] / max_hour_count * 100) if max_hour_count else 0,
        })

    platform_rows = [
        {
            "platform": key,
            "count": value["count"],
            "total": value["total"],
            "average": value["total"] / value["count"] if value["count"] else 0,
            "share": value["count"] / len(valid) * 100 if valid else 0,
        }
        for key, value in sorted(platform_data.items(), key=lambda item: item[1]["count"], reverse=True)
    ]
    best_day = max(weekday_rows, key=lambda row: row["average"], default=None) if max_day_count else None
    best_hour = max(hour_rows, key=lambda row: row["count"], default=None) if max_hour_count else None
    busiest_days = sorted(weekday_rows, key=lambda row: row["average"], reverse=True)

    return {
        "gross_count": len(orders),
        "valid_count": len(valid),
        "valid_total": _sum_orders(valid),
        "cancelled_count": len(cancelled),
        "refunded_count": len(refunded),
        "average_order_value": average_order_value,
        "average_per_day": len(valid) / total_days if total_days else 0,
        "best_day": best_day,
        "best_hour": best_hour,
        "weekday_rows": weekday_rows,
        "hour_rows": hour_rows,
        "platform_rows": platform_rows,
        "busiest_days": busiest_days[:3],
        "total_days": total_days,
    }


def _apply_report_date_filter(query, start_date, end_date):
    start_dt = TURKEY_TZ.localize(datetime.combine(start_date, datetime.min.time()))
    end_dt = TURKEY_TZ.localize(datetime.combine(end_date + timedelta(days=1), datetime.min.time()))
    return query.filter(
        Order.created_at >= start_dt.astimezone(pytz.utc).replace(tzinfo=None),
        Order.created_at < end_dt.astimezone(pytz.utc).replace(tzinfo=None),
    )


def _parse_date_value(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        flash("Tarih alanlarından biri okunamadı.", "warning")
        return None


def _build_report_summary(orders: list) -> dict:
    refunded = [order for order in orders if _is_refunded_order(order)]
    cancelled = [order for order in orders if _is_cancelled_order(order) and order not in refunded]
    valid = [order for order in orders if order not in cancelled and order not in refunded]

    return {
        "gross_count": len(orders),
        "gross_total": _sum_orders(orders),
        "valid_count": len(valid),
        "valid_total": _sum_orders(valid),
        "cancelled_count": len(cancelled),
        "cancelled_total": _sum_orders(cancelled),
        "refunded_count": len(refunded),
        "refunded_total": _sum_orders(refunded),
        "products": _report_products(valid),
        "platforms": _report_platforms(valid, cancelled, refunded),
    }


def _sum_orders(orders: list) -> float:
    return sum((order.total_price or 0) for order in orders)


def _normalized_status(status: str) -> str:
    return (status or "").replace("_", "").replace("-", "").replace(" ", "").lower()


def _is_cancelled_order(order: Order) -> bool:
    status = order.status or ""
    normalized = _normalized_status(status)
    return (
        status in CANCELLED_STATUSES
        or "cancel" in normalized
        or "iptal" in normalized
        or "reject" in normalized
        or "unsupplied" in normalized
    )


def _is_refunded_order(order: Order) -> bool:
    status = order.status or ""
    normalized = _normalized_status(status)
    return (
        status in REFUNDED_STATUSES
        or "refund" in normalized
        or "iade" in normalized
        or "return" in normalized
    )


def _report_products(orders: list, max_items: int = 15) -> list:
    counts = {}
    for order in orders:
        data = _parse_raw_json(order.raw_json)
        if order.platform == "migros":
            for item in data.get("items") or []:
                name = item.get("name") or "Ürün"
                counts[name] = counts.get(name, 0) + (item.get("amount") or 1)
        elif order.platform == "getir":
            for item in getir.products(data):
                if not isinstance(item, dict):
                    continue
                name = getir.product_name(item)
                counts[name] = counts.get(name, 0) + getir.product_quantity(item)
        elif order.platform == tmp.PLATFORM:
            for line in tmp.lines(data):
                if not isinstance(line, dict):
                    continue
                name = tmp.line_name(line)
                counts[name] = counts.get(name, 0) + tmp.line_quantity(line)
        elif order.platform == hb.PLATFORM:
            for line in hb.lines(data):
                if not isinstance(line, dict):
                    continue
                name = hb.line_name(line)
                counts[name] = counts.get(name, 0) + hb.line_quantity(line)
        elif order.platform == ys.PLATFORM:
            for item in ys.items(data):
                if not isinstance(item, dict):
                    continue
                name = ys.item_name(item)
                counts[name] = counts.get(name, 0) + ys.item_quantity(item)
        else:
            for line in data.get("lines") or []:
                name = line.get("name") or line.get("productName") or "Ürün"
                counts[name] = counts.get(name, 0) + tgo._line_quantity(line)
    return [
        {"name": name, "quantity": qty}
        for name, qty in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:max_items]
    ]


def _report_platforms(valid: list, cancelled: list, refunded: list) -> list:
    grouped = {}
    for key, orders in (("valid", valid), ("cancelled", cancelled), ("refunded", refunded)):
        for order in orders:
            bucket = grouped.setdefault(order.platform, {
                "platform": order.platform,
                "valid_count": 0,
                "valid_total": 0,
                "cancelled_count": 0,
                "cancelled_total": 0,
                "refunded_count": 0,
                "refunded_total": 0,
            })
            bucket[f"{key}_count"] += 1
            bucket[f"{key}_total"] += order.total_price or 0
    return sorted(grouped.values(), key=lambda item: item["valid_total"], reverse=True)


def _order_detail_context(order: Order) -> dict:
    raw = _parse_raw_json(order.raw_json)
    if order.platform == "migros":
        return _migros_detail_context(order, raw)
    if order.platform == "getir":
        return _getir_detail_context(order, raw)
    if order.platform == tmp.PLATFORM:
        return _tmp_detail_context(order, raw)
    if order.platform == hb.PLATFORM:
        return _hb_detail_context(order, raw)
    if order.platform == ys.PLATFORM:
        return _ys_detail_context(order, raw)
    if order.platform in {TGO_FOOD_PLATFORM, TGO_MARKET_PLATFORM}:
        return _tgo_detail_context(order, raw)
    return {
        "raw": raw,
        "items": [],
        "customer": "-",
        "store": "-",
        "delivery": "-",
        "payment": order.payment_type or "-",
        "address": "",
        "address_direction": "",
        "flags": [],
        "order_note": order.customer_note or "",
    }


def _parse_raw_json(raw_json: str) -> dict:
    if not raw_json:
        return {}
    try:
        data = json.loads(raw_json)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def _tgo_detail_context(order: Order, raw: dict) -> dict:
    payment = raw.get("payment") or {}
    payment_map = {
        "PAY_WITH_CARD": "Online Kart",
        "PAY_WITH_ON_DELIVERY": "Kapıda Ödeme",
        "PAY_WITH_MEAL_CARD": "Yemek Kartı",
    }
    delivery_map = {"GO": "TGo Kuryesi", "STORE": "Restoran Kuryesi"}
    app_raw = (raw.get("userInformation") or {}).get("appName", "")

    return {
        "raw": raw,
        "items": _tgo_detail_items(raw),
        "totals": _generic_detail_totals(order.total_price),
        "customer": _first_text(raw, "customerName", "customerFullName", "fullName") or "-",
        "store": _first_text(raw, "storeName", "restaurantName", "sellerName") or "-",
        "source": app_raw or order.app_source or "-",
        "delivery": delivery_map.get(raw.get("deliveryType"), raw.get("deliveryType") or "-"),
        "payment": payment_map.get(payment.get("paymentType"), order.payment_type or payment.get("paymentType") or "-"),
        "address": _tgo_address(raw),
        "address_direction": "",
        "flags": [],
        "order_note": raw.get("customerNote") or order.customer_note or "",
    }


def _tgo_detail_items(raw: dict) -> list:
    items = []
    for line in raw.get("lines") or []:
        if not isinstance(line, dict):
            continue
        details = [_display_detail_text(part) for part in tgo._line_detail_parts(line)]
        items.append({
            "name": line.get("name") or line.get("productName") or "?",
            "quantity": tgo._line_quantity(line),
            "price": _tgo_line_price_text(line),
            "note": "",
            "details": details,
        })
    return items


def _tgo_line_price_text(line: dict) -> str:
    for key in ("totalPrice", "price", "amount", "discountedPrice", "sellingPrice"):
        value = line.get(key)
        if value not in (None, ""):
            try:
                return f"{float(value or 0):.2f} TL"
            except (TypeError, ValueError):
                return str(value)
    return ""


def _generic_detail_totals(total_price) -> dict:
    try:
        total = float(total_price or 0)
    except (TypeError, ValueError):
        total = 0
    if not total:
        return {}
    return {"total": f"{total:.2f} TL", "discount": "", "discounted": f"{total:.2f} TL"}


def _getir_detail_context(order: Order, raw: dict) -> dict:
    return {
        "raw": raw,
        "items": _getir_detail_items(raw),
        "customer": getir.customer_name(raw) or "-",
        "store": getir.restaurant_name(raw) or "-",
        "source": "Getir Yemek",
        "delivery": getir.delivery_label(raw),
        "payment": order.payment_type or getir.payment_label(raw),
        "address": getir.address_text(raw),
        "address_direction": getir.address_direction(raw),
        "flags": [],
        "order_note": getir.customer_note(raw) or order.customer_note or "",
    }


def _getir_detail_items(raw: dict) -> list:
    items = []
    for item in getir.products(raw):
        if not isinstance(item, dict):
            continue
        items.append({
            "name": getir.product_name(item),
            "quantity": getir.product_quantity(item),
            "note": "",
            "details": [_display_detail_text(part) for part in getir.item_detail_parts(item)],
        })
    return items


def _tmp_detail_context(order: Order, raw: dict) -> dict:
    return {
        "raw": raw,
        "items": _tmp_detail_items(raw),
        "customer": tmp.customer_name(raw) or "-",
        "store": _first_text(raw, "supplierName", "sellerName", "storeName") or "-",
        "source": "Trendyol Pazaryeri",
        "delivery": tmp.cargo_label(raw),
        "payment": order.payment_type or "-",
        "address": tmp.address_text(raw),
        "address_direction": "",
        "flags": [],
        "order_note": order.customer_note or "",
    }


def _tmp_detail_items(raw: dict) -> list:
    items = []
    for line in tmp.lines(raw):
        if not isinstance(line, dict):
            continue
        items.append({
            "name": tmp.line_name(line),
            "quantity": tmp.line_quantity(line),
            "note": "",
            "details": tmp.line_details(line),
        })
    return items


def _hb_detail_context(order: Order, raw: dict) -> dict:
    return {
        "raw": raw,
        "items": _hb_detail_items(raw),
        "customer": hb.customer_name(raw) or "-",
        "store": "-",
        "source": "Hepsiburada",
        "delivery": hb.cargo_label(raw),
        "payment": order.payment_type or "Hepsiburada",
        "address": hb.address_text(raw),
        "address_direction": "",
        "flags": [],
        "order_note": order.customer_note or "",
    }


def _hb_detail_items(raw: dict) -> list:
    items = []
    for line in hb.lines(raw):
        if not isinstance(line, dict):
            continue
        items.append({
            "name": hb.line_name(line),
            "quantity": hb.line_quantity(line),
            "note": "",
            "details": hb.line_details(line),
        })
    return items


def _ys_detail_context(order: Order, raw: dict) -> dict:
    customer = ys.customer_name(raw)
    customer_data = raw.get("customer") or {}
    items = []
    for item in ys.items(raw):
        if not isinstance(item, dict):
            continue
        items.append({
            "name": ys.item_name(item),
            "quantity": ys.item_quantity(item),
            "price": ys.item_price_text(item),
            "note": "",
            "details": ys.item_details(item),
            "options": ys.item_options(item),
        })
    return {
        "raw": raw,
        "items": items,
        "totals": _generic_detail_totals(order.total_price),
        "customer": customer,
        "customer_phone": customer_data.get("phone_number") or "",
        "order_created_at": _ys_order_created_at(raw),
        "store": ys.client(raw).get("name") or "-",
        "source": "Yemeksepeti",
        "delivery": ys.delivery_label(raw),
        "payment": order.payment_type or ys.payment_type(raw),
        "address": ys.address_text(raw),
        "address_direction": ys.address_instructions(raw),
        "flags": [],
        "order_note": order.customer_note or "",
    }


def _ys_order_created_at(raw: dict) -> str:
    sys_data = raw.get("sys") or {}
    value = str(sys_data.get("created_at") or "").strip()
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return value


def _migros_detail_context(order: Order, raw: dict) -> dict:
    ext = raw.get("extendedProperties") or {}
    customer = raw.get("customer") or {}
    address = customer.get("deliveryAddress") or {}
    payment = (raw.get("payment") or {}).get("type") or {}
    provider_map = {"RESTAURANT": "Restoran Kuryesi", "MIGROS": "Migros Kuryesi"}
    flags = []
    if ext.get("ringDoorBell") is False:
        flags.append("Zili çalmayın")
    elif ext.get("ringDoorBell") is True:
        flags.append("Zili çalın")
    if ext.get("contactlessDelivery"):
        flags.append("Temassız teslimat")
    if ext.get("saveGreen"):
        flags.append("Çatal bıçak göndermeyin")

    return {
        "raw": raw,
        "items": _migros_detail_items(raw),
        "totals": _migros_detail_totals(raw),
        "customer": customer.get("fullName") or "-",
        "customer_phone": customer.get("phoneNumber") or "",
        "order_created_at": _migros_order_created_at(raw),
        "store": (raw.get("store") or {}).get("name") or "-",
        "source": "Migros Yemek",
        "delivery": provider_map.get(raw.get("deliveryProvider"), raw.get("deliveryProvider") or "-"),
        "payment": payment.get("description") or payment.get("name") or order.payment_type or "-",
        "address": address.get("detail") or "",
        "address_direction": address.get("direction") or "",
        "flags": flags,
        "order_note": ext.get("orderNote") or order.customer_note or "",
    }


def _migros_detail_items(raw: dict) -> list:
    items = []
    for item in raw.get("items") or []:
        if not isinstance(item, dict):
            continue
        options = _migros_detail_options(item.get("options") or [])
        items.append({
            "name": item.get("name") or "?",
            "quantity": item.get("amount") or 1,
            "price": item.get("priceText") or _migros_penny_text(item.get("price")),
            "note": item.get("note") or "",
            "details": [] if options else [_display_detail_text(part) for part in migros._item_detail_parts(item)],
            "options": options,
        })
    return items


def _migros_detail_options(options: list) -> list:
    rows = []
    for option in options or []:
        if not isinstance(option, dict):
            continue
        name = option.get("itemNames") or option.get("headerName") or "-"
        header = option.get("headerName") or ""
        excluded = bool(option.get("excluded"))
        label = f"Ã‡Ä±karÄ±lacak: {name}" if excluded else (f"{header}: {name}" if header and header != name else name)
        rows.append({
            "label": _display_detail_text(label),
            "name": name,
            "header": header,
            "quantity": option.get("quantity") or 1,
            "price": option.get("primaryDiscountedPriceText") or option.get("primaryPriceText") or _migros_penny_text(option.get("primaryDiscountedPrice") or option.get("primaryPrice")),
            "excluded": excluded,
            "children": _migros_detail_options(option.get("subOptions") or []),
        })
    return rows


def _migros_detail_totals(raw: dict) -> dict:
    prices = raw.get("prices") or {}
    total_text = _migros_price_text(prices.get("total"))
    discounted_text = (
        _migros_price_text(prices.get("discounted"))
        or _migros_price_text(prices.get("migrosDiscounted"))
        or _migros_price_text(prices.get("restaurantDiscounted"))
    )
    total_amount = _migros_price_amount(prices.get("total"))
    discounted_amount = (
        _migros_price_amount(prices.get("discounted"))
        or _migros_price_amount(prices.get("migrosDiscounted"))
        or _migros_price_amount(prices.get("restaurantDiscounted"))
    )
    discount_text = ""
    if total_amount is not None and discounted_amount is not None:
        discount_text = _migros_lira_text(max(0, total_amount - discounted_amount))
    return {
        "total": total_text,
        "discount": discount_text,
        "discounted": discounted_text or total_text,
    }


def _migros_price_text(node) -> str:
    if not isinstance(node, dict):
        return ""
    return node.get("text") or _migros_penny_text(node.get("amountAsPenny"))


def _migros_price_amount(node):
    if not isinstance(node, dict) or node.get("amountAsPenny") is None:
        return None
    try:
        return int(node.get("amountAsPenny") or 0) / 100
    except (TypeError, ValueError):
        return None


def _migros_lira_text(value: float) -> str:
    return f"{value:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _migros_penny_text(value) -> str:
    try:
        amount = int(value or 0) / 100
    except (TypeError, ValueError):
        return ""
    return f"{amount:.2f} TL"


def _migros_order_created_at(raw: dict) -> str:
    created_ms = ((raw.get("log") or {}).get("createdAsMs"))
    if not created_ms:
        return ""
    try:
        dt = datetime.fromtimestamp(int(created_ms) / 1000, tz=pytz.utc).astimezone(TURKEY_TZ)
        return dt.strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


def _migros_user_id(raw: dict):
    return (raw.get("customer") or {}).get("id") or raw.get("userId") or raw.get("UserId")


def _display_detail_text(value: str) -> str:
    replacements = {
        "Cikarilacak": "Çıkarılacak",
        "Urun notu": "Ürün notu",
        "Ozel not": "Özel not",
        "Siparis notu": "Sipariş notu",
    }
    text = value or ""
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _first_text(data: dict, *keys) -> str:
    for key in keys:
        value = data.get(key)
        if value:
            return str(value).strip()
    return ""


def _tgo_address(raw: dict) -> str:
    address = raw.get("address") or raw.get("deliveryAddress") or {}
    if isinstance(address, str):
        return address
    if not isinstance(address, dict):
        return ""
    for key in ("fullAddress", "address", "detail", "description"):
        if address.get(key):
            return str(address[key]).strip()
    parts = [address.get(k) for k in ("neighborhood", "street", "buildingNo", "floor", "doorNumber", "district", "city")]
    return " ".join(str(part).strip() for part in parts if part)


# ── Profil ──────────────────────────────────────────────────────────────────

@dashboard_bp.route("/profil", methods=["GET", "POST"])
@login_required
def profile():
    sound_options = ORDER_POPUP_SOUND_OPTIONS
    if request.method == "POST":
        name       = request.form.get("name", "").strip()
        current_pw = request.form.get("current_password", "")
        new_pw     = request.form.get("new_password", "")
        confirm_pw = request.form.get("confirm_password", "")

        if name:
            current_user.name = name

        # Bildirim kanalı + WhatsApp numarası
        channel = request.form.get("notification_channel", "").strip()
        if not _can_use_whatsapp() and channel in ("whatsapp", "both"):
            current_user.notification_channel = "telegram"
            flash("WhatsApp bildirimleri Pro planda kullanılabilir. Ücretsiz planda Telegram açık kalır.", "warning")
        elif channel in ("telegram", "whatsapp", "both"):
            current_user.notification_channel = channel
        wa_number = request.form.get("whatsapp_number", "").strip()
        current_user.whatsapp_number = wa_number or None
        popup_sound = request.form.get("order_popup_sound", "classic").strip()
        if popup_sound not in {value for value, _ in sound_options}:
            popup_sound = "classic"
        current_user.order_popup_sound_enabled = "order_popup_sound_enabled" in request.form
        current_user.order_popup_sound = popup_sound

        if current_pw or new_pw:
            if not current_user.check_password(current_pw):
                flash("Mevcut şifre hatalı.", "danger")
                return render_template("dashboard/profile.html", sound_options=sound_options)
            if new_pw != confirm_pw:
                flash("Yeni şifreler eşleşmiyor.", "danger")
                return render_template("dashboard/profile.html", sound_options=sound_options)
            if len(new_pw) < 6:
                flash("Şifre en az 6 karakter olmalı.", "danger")
                return render_template("dashboard/profile.html", sound_options=sound_options)
            current_user.set_password(new_pw)

        db.session.commit()
        flash("Profil güncellendi.", "success")

    return render_template("dashboard/profile.html", sound_options=sound_options)


@dashboard_bp.route("/test-bildirim", methods=["POST"])
@login_required
def send_test_notification():
    """Seçili kanala test bildirimi gönderir. WhatsApp'ta önce onaylı şablonu dener,
    olmazsa (24s müşteri penceresi açıksa) serbest metne düşer — böylece şablon onayı
    beklenmeden de test edilebilir."""
    from notifications import whatsapp, telegram as tg
    cfg = current_app.config
    _force_free_notification_channel()
    db.session.commit()
    ch = (current_user.notification_channel or "telegram").lower()
    tg_text = "🔔 <b>Test bildirimi</b>\nBildirimlerin çalışıyor! 🎉\n— SiparişGeldi"
    wa_text = "🔔 Test bildirimi — bildirimlerin çalışıyor! 🎉 (SiparişGeldi)"
    results = []

    if ch in ("telegram", "both"):
        if current_user.telegram_chat_id and cfg.get("TELEGRAM_BOT_TOKEN"):
            ok = tg.send_message(cfg["TELEGRAM_BOT_TOKEN"], current_user.telegram_chat_id, tg_text)
            results.append("Telegram ✅" if ok else "Telegram ❌")
        else:
            results.append("Telegram ⏭ (bağlı değil)")

    if ch in ("whatsapp", "both"):
        tok  = cfg.get("WHATSAPP_ACCESS_TOKEN")
        pnid = cfg.get("WHATSAPP_PHONE_NUMBER_ID")
        num  = current_user.whatsapp_number
        if tok and pnid and num:
            ver = cfg.get("WHATSAPP_API_VERSION", "v21.0")
            ok, err = whatsapp.send_template(
                num, cfg.get("WHATSAPP_TEMPLATE_NAME", "siparis_bildirim"),
                cfg.get("WHATSAPP_TEMPLATE_LANG", "tr"),
                ["Test bildirimi", "TEST-001", "Örnek ürün x1", "0,00 ₺"], tok, pnid, ver)
            if ok:
                results.append("WhatsApp ✅ (şablon)")
            else:
                ok2, err2 = whatsapp.send_text(num, wa_text, tok, pnid, ver)
                results.append("WhatsApp ✅ (serbest metin)" if ok2
                               else f"WhatsApp ❌ ({err or err2})")
        else:
            results.append("WhatsApp ⏭ (numara/credential eksik)")

    flash("Test sonucu: " + (" · ".join(results) if results else "kanal ayarlı değil"), "info")
    return redirect(url_for("dashboard.profile"))

"""Panel: özet, Telegram bağlama, TrendyolGo kurulum, siparişler, profil."""
import json
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError
import pytz

from extensions import db
from models import (Integration, Order, ProductCost, PlatformExpense, DailyAdvertisingExpense,
                    PlatformCommission, AdisyoReport, AdisyoConnection)
from integrations import getir, hepsiburada as hb, migros, trendyol_marketplace as tmp, trendyolgo as tgo, yemeksepeti as ys
from notifications.dispatcher import send_to_user, record_whatsapp_result
from utils import platform_label, status_label

dashboard_bp = Blueprint("dashboard", __name__)
TURKEY_TZ = pytz.timezone("Europe/Istanbul")
TGO_FOOD_PLATFORM = "trendyolgo"
TGO_MARKET_PLATFORM = "trendyolgo_market"

PENDING_STATUSES = {"Created", "NEW_PENDING", "Pending", "New", "Scheduled", "Awaiting", "RECEIVED"}
PREPARING_STATUSES = {"Picking", "Invoiced", "Approved", "Prepared", "ScheduledApproved", "READY_FOR_PICKUP", "ACCEPTED", "PREPARED"}
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
    return bool(getattr(user, "is_pro_active", False))


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
    cfg = current_app.config
    whatsapp_status = {
        "access": _can_use_whatsapp(),
        "channel": (current_user.notification_channel or "telegram").lower(),
        "number": bool(current_user.whatsapp_number),
        "token": bool(cfg.get("WHATSAPP_ACCESS_TOKEN")),
        "phone_number_id": bool(cfg.get("WHATSAPP_PHONE_NUMBER_ID")),
        "template": cfg.get("WHATSAPP_TEMPLATE_NAME", "siparis_bildirim"),
        "report_template": cfg.get("WHATSAPP_REPORT_TEMPLATE_NAME", "gunluk_raporr"),
        "language": cfg.get("WHATSAPP_TEMPLATE_LANG", "tr"),
        "version": cfg.get("WHATSAPP_API_VERSION", "v21.0"),
        "webhook_url": url_for("webhooks.whatsapp_status_webhook", _external=True),
        "webhook_verify_token": bool(cfg.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN")),
        "app_secret": bool(cfg.get("WHATSAPP_APP_SECRET")),
        "last_status": current_user.whatsapp_last_status or "",
        "last_status_at": current_user.whatsapp_last_status_at,
        "last_error": current_user.whatsapp_last_error or "",
    }
    return render_template(
        "dashboard/connect_whatsapp.html",
        can_use_whatsapp=_can_use_whatsapp(),
        whatsapp_status=whatsapp_status,
    )


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
    print(
        "[WHATSAPP TEST] user=%s number=%s token=%s phone_number_id=%s template=%s lang=%s"
        % (
            current_user.id,
            bool(num),
            bool(tok),
            bool(pnid),
            cfg.get("WHATSAPP_TEMPLATE_NAME", "siparis_bildirim"),
            cfg.get("WHATSAPP_TEMPLATE_LANG", "tr"),
        )
    )
    if not (num and tok and pnid):
        flash("WhatsApp numarası veya sistem yapılandırması eksik.", "warning")
        return redirect(url_for("dashboard.connect_whatsapp"))
    ver = cfg.get("WHATSAPP_API_VERSION", "v21.0")
    ok, result = whatsapp.send_template(
        num, cfg.get("WHATSAPP_TEMPLATE_NAME", "siparis_bildirim"),
        cfg.get("WHATSAPP_TEMPLATE_LANG", "tr"),
        ["Test bildirimi", "TEST-001", "Örnek ürün x1", "0,00 ₺"], tok, pnid, ver)
    if ok:
        record_whatsapp_result(
            current_user,
            "accepted",
            message_id=result if isinstance(result, str) and result.startswith("wamid.") else None,
        )
    else:
        template_error = result
        ok, fallback_result = whatsapp.send_text(
            num,
            "🔔 Test — WhatsApp bildirimlerin çalışıyor! (SiparişGeldi)",
            tok,
            pnid,
            ver,
        )
        if ok:
            result = fallback_result
            record_whatsapp_result(
                current_user,
                "accepted",
                message_id=result if isinstance(result, str) and result.startswith("wamid.") else None,
            )
        else:
            result = f"{template_error} | Serbest metin: {fallback_result}"
            record_whatsapp_result(current_user, "failed", error=result)
    flash("✅ WhatsApp test mesajı gönderildi." if ok else f"⚠️ Gönderilemedi: {result}",
          "success" if ok else "warning")
    return redirect(url_for("dashboard.connect_whatsapp"))


@dashboard_bp.route("/whatsapp/test-rapor", methods=["POST"])
@login_required
def test_whatsapp_report():
    """WhatsApp rapor şablonunu ayrıca test eder."""
    if not _can_use_whatsapp():
        flash("WhatsApp rapor testi Pro planda kullanılabilir.", "warning")
        return redirect(url_for("dashboard.connect_whatsapp"))
    from notifications import whatsapp
    cfg = current_app.config
    num = current_user.whatsapp_number
    tok = cfg.get("WHATSAPP_ACCESS_TOKEN")
    pnid = cfg.get("WHATSAPP_PHONE_NUMBER_ID")
    template = cfg.get("WHATSAPP_REPORT_TEMPLATE_NAME", "gunluk_raporr")
    lang = cfg.get("WHATSAPP_TEMPLATE_LANG", "tr")
    print(
        "[WHATSAPP RAPOR TEST] user=%s number=%s token=%s phone_number_id=%s template=%s lang=%s"
        % (current_user.id, bool(num), bool(tok), bool(pnid), template, lang)
    )
    if not (num and tok and pnid):
        flash("WhatsApp numarası veya sistem yapılandırması eksik.", "warning")
        return redirect(url_for("dashboard.connect_whatsapp"))
    ok, result = whatsapp.send_template(
        num,
        template,
        lang,
        [
            f"Günlük · Test · {datetime.now(TURKEY_TZ).strftime('%d.%m.%Y')} · 1 geçerli, 0 iptal, 0 iade",
            "Test ürün x1",
            "100,00 ₺",
        ],
        tok,
        pnid,
        cfg.get("WHATSAPP_API_VERSION", "v21.0"),
    )
    if ok:
        record_whatsapp_result(
            current_user,
            "accepted",
            message_id=result if isinstance(result, str) and result.startswith("wamid.") else None,
        )
    else:
        record_whatsapp_result(current_user, "failed", error=result)
    flash("✅ WhatsApp rapor test mesajı gönderildi." if ok else f"⚠️ Rapor şablonu gönderilemedi: {result}",
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
        vendor_id = request.form.get("remote_id", request.form.get("vendor_id", "")).strip()
        environment = request.form.get("environment", "live").strip().lower()
        client_id = request.form.get("client_id", "").strip()
        client_secret = request.form.get("client_secret", "").strip()

        if not _can_enable_platform(intg):
            flash("Ücretsiz planda 1 platform bağlayabilirsin. WhatsApp ve çoklu platform için Pro plana geç.", "warning")
            return render_template("dashboard/yemeksepeti_setup.html", intg=intg, **_ys_setup_context(intg))
        if not vendor_id and not store_id:
            flash("Yemeksepeti POS remoteId zorunludur.", "danger")
            return render_template("dashboard/yemeksepeti_setup.html", intg=intg, **_ys_setup_context(intg))
        if environment not in ("sandbox", "live"):
            environment = "live"

        if not intg:
            intg = Integration(user_id=current_user.id, platform=ys.PLATFORM)
            db.session.add(intg)
        intg.ys_chain_id = chain_id or None
        intg.ys_store_id = store_id or vendor_id
        intg.ys_vendor_id = vendor_id or store_id
        intg.ys_environment = environment
        if client_id:
            intg.ys_client_id = client_id
        if client_secret:
            intg.ys_client_secret = client_secret
        intg.is_active = True
        intg.last_error = None
        db.session.commit()

        flash("Yemeksepeti POS restoran kimliği kaydedildi. Sipariş endpoint'i bu remoteId için hazır.", "success")
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
    username = current_app.config.get("YEMEKSEPETI_POS_USERNAME", "")
    password = current_app.config.get("YEMEKSEPETI_POS_PASSWORD", "")
    if not username or not password:
        flash("Yemeksepeti POS username/password bilgileri henüz tanımlanmadı.", "warning")
        return redirect(url_for("dashboard.yemeksepeti_setup"))
    try:
        ys.get_pos_access_token(
            username, password, intg.ys_environment or "live",
            current_app.config.get("YEMEKSEPETI_POS_API_BASE", ""),
        )
        intg.last_error = None
        intg.last_sync_at = datetime.utcnow()
        db.session.commit()
        flash("Yemeksepeti POS Middleware bağlantısı doğrulandı.", "success")
    except Exception as exc:
        intg.last_error = f"Yemeksepeti POS baglanti: {exc}"[:300]
        db.session.commit()
        flash("Yemeksepeti POS Middleware bağlantısı doğrulanamadı.", "danger")
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
    chain_code = intg.ys_chain_id or current_app.config.get("YEMEKSEPETI_POS_CHAIN_CODE", "")
    remote_id = intg.ys_vendor_id or intg.ys_store_id
    username = current_app.config.get("YEMEKSEPETI_POS_USERNAME", "")
    password = current_app.config.get("YEMEKSEPETI_POS_PASSWORD", "")
    status = request.form.get("status", "").strip().lower()
    if not chain_code or not remote_id or not username or not password:
        flash("Chain code, remoteId veya POS credential bilgileri eksik.", "warning")
        return redirect(url_for("dashboard.yemeksepeti_setup"))
    if status not in {"online", "offline"}:
        flash("Geçersiz POS erişilebilirlik durumu.", "warning")
        return redirect(url_for("dashboard.yemeksepeti_setup"))

    try:
        ys.set_pos_reachability(
            chain_code, remote_id, status == "online", username, password,
            intg.ys_environment or "live",
            current_app.config.get("YEMEKSEPETI_POS_API_BASE", ""),
        )
        intg.last_sync_at = datetime.utcnow()
        intg.last_error = None
        db.session.commit()
        flash(f"Yemeksepeti POS durumu gönderildi: {status}", "success")
    except Exception as e:
        intg.last_error = f"Yemeksepeti POS erisilebilirlik: {e}"[:300]
        db.session.commit()
        flash("Yemeksepeti POS durumu gönderilemedi.", "danger")
    return redirect(url_for("dashboard.yemeksepeti_setup"))


def _ys_setup_context(intg: Integration = None) -> dict:
    return {
        "ys_plugin_base_url": url_for("webhooks.yemeksepeti_pos_dispatch", remote_id="REMOTE_ID", _external=True).rsplit("/order/", 1)[0],
        "ys_pos_credentials_ready": bool(
            current_app.config.get("YEMEKSEPETI_POS_USERNAME")
            and current_app.config.get("YEMEKSEPETI_POS_PASSWORD")
            and current_app.config.get("YEMEKSEPETI_POS_JWT_SECRET")
        ),
        "ys_pos_base": ys.pos_api_base(
            (intg.ys_environment if intg else "live") or "live",
            current_app.config.get("YEMEKSEPETI_POS_API_BASE", ""),
        ),
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
    # Adisyo siparişleri günlük rapor modelinde tutulur; istatistikler için
    # aynı ortak sipariş biçimine dönüştürülür.
    if not platform or platform == "adisyo":
        reports = (AdisyoReport.query.join(AdisyoConnection)
                   .join(Integration, AdisyoConnection.integration_id == Integration.id)
                   .filter(Integration.user_id == current_user.id, AdisyoReport.state == "ready",
                           AdisyoReport.day >= start_date, AdisyoReport.day <= end_date).all())
        for report in reports:
            try:
                summary = json.loads(report.summary_json or "{}")
                count = max(0, int(summary.get("count") or 0) - int(summary.get("cancelled") or 0))
                total = float(summary.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            per_order = total / count if count else 0
            for index in range(count):
                orders.append(Order(user_id=current_user.id, platform="adisyo",
                                    external_id=f"adisyo-{report.day}-{index}",
                                    status="Completed", total_price=per_order,
                                    created_at=datetime.combine(report.day, datetime.min.time())))
        orders.sort(key=lambda item: item.created_at or datetime.min, reverse=True)
    summary = _build_analytics_summary(orders, start_date, end_date)
    previous_start, previous_end = _previous_calendar_week(end_date)
    current_week_start = end_date - timedelta(days=end_date.weekday())
    current_week_query = Order.query.filter_by(user_id=current_user.id)
    if platform:
        current_week_query = current_week_query.filter_by(platform=platform)
    current_week_query = _apply_report_date_filter(current_week_query, current_week_start, end_date)
    current_week_orders = current_week_query.all()
    if not platform or platform == "adisyo":
        current_week_orders += _analytics_adisyo_orders(current_user.id, current_week_start, end_date)
    current_week = _build_previous_week_summary(
        current_week_orders,
        current_week_start,
        week_end=end_date,
    )
    previous_query = Order.query.filter_by(user_id=current_user.id)
    if platform:
        previous_query = previous_query.filter_by(platform=platform)
    previous_query = _apply_report_date_filter(previous_query, previous_start, previous_end)
    previous_orders = previous_query.all()
    if not platform or platform == "adisyo":
        previous_orders += _analytics_adisyo_orders(current_user.id, previous_start, previous_end)
    previous_week = _build_previous_week_summary(previous_orders, previous_start)
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


def _analytics_adisyo_orders(user_id, start_date, end_date):
    reports = (AdisyoReport.query.join(AdisyoConnection)
               .join(Integration, AdisyoConnection.integration_id == Integration.id)
               .filter(Integration.user_id == user_id, AdisyoReport.state == "ready",
                       AdisyoReport.day >= start_date, AdisyoReport.day <= end_date).all())
    result = []
    for report in reports:
        try:
            summary = json.loads(report.summary_json or "{}")
            count = max(0, int(summary.get("count") or 0) - int(summary.get("cancelled") or 0))
            total = float(summary.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        for index in range(count):
            result.append(Order(user_id=user_id, platform="adisyo",
                                external_id=f"adisyo-{report.day}-{index}", status="Completed",
                                total_price=total / count if count else 0,
                                created_at=datetime.combine(report.day, datetime.min.time())))
    return result


@dashboard_bp.route("/abonelik")
@login_required
def subscription():
    integrations = Integration.query.filter_by(user_id=current_user.id).all()
    active_integrations = [i for i in integrations if i.is_active]
    now = datetime.utcnow()
    pro_days_left = None
    if current_user.pro_expires_at:
        pro_days_left = max(0, (current_user.pro_expires_at.date() - now.date()).days)
    return render_template(
        "dashboard/subscription.html",
        integrations=integrations,
        active_integrations=active_integrations,
        pro_days_left=pro_days_left,
        payment_returned=request.args.get("payment_returned") == "1",
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
        order_created_local=_order_local_datetime(order),
        detail=detail,
        migros_actions=migros_actions,
        migros_cancel_reasons=_migros_cancel_reasons(migros_intg) if migros_actions else [],
        getir_actions=getir_actions,
        yemeksepeti_actions=yemeksepeti_actions,
        trendyolgo_actions=trendyolgo_actions,
    )


@dashboard_bp.route("/maliyetler", methods=["GET", "POST"])
@login_required
def product_costs():
    """Satılan ürün bazında birim maliyet ve karlılık görünümü."""
    if request.method == "POST":
        if request.form.get("form_type") == "commission":
            platform = request.form.get("commission_platform", "").strip()[:30]
            try:
                percentage = float(request.form.get("commission_percentage", "0").replace(",", "."))
                if percentage < 0 or percentage > 100:
                    raise ValueError
            except ValueError:
                flash("Komisyon oranı 0 ile 100 arasında olmalı.", "danger")
                return redirect(url_for("dashboard.product_costs"))
            row = PlatformCommission.query.filter_by(user_id=current_user.id, platform=platform).first()
            if not row:
                row = PlatformCommission(user_id=current_user.id, platform=platform)
                db.session.add(row)
            row.percentage = percentage
            db.session.commit()
            flash("Platform komisyonu kaydedildi.", "success")
            return redirect(url_for("dashboard.product_costs"))
        if request.form.get("form_type") == "expense":
            try:
                amount = float(request.form.get("expense_amount", "0").replace(",", "."))
                if not 0 <= amount <= 10000000:
                    raise ValueError
            except ValueError:
                flash("Geçerli bir gider tutarı girin.", "danger")
                return redirect(url_for("dashboard.product_costs"))
            existing = PlatformExpense.query.filter_by(user_id=current_user.id,
                platform=request.form.get("expense_platform", "genel")[:30],
                name=request.form.get("expense_name", "Diğer gider").strip()[:120] or "Diğer gider").first()
            if existing:
                existing.amount = amount
                existing.expense_type = request.form.get("expense_type", "fixed") if request.form.get("expense_type") in ("fixed", "per_order") else "fixed"
            else:
                db.session.add(PlatformExpense(user_id=current_user.id,
                    platform=request.form.get("expense_platform", "genel")[:30],
                    name=request.form.get("expense_name", "Diğer gider").strip()[:120] or "Diğer gider",
                    amount=amount, expense_type=request.form.get("expense_type", "fixed") if request.form.get("expense_type") in ("fixed", "per_order") else "fixed",
                    day_from=datetime.utcnow().date(), day_to=datetime.utcnow().date()))
            db.session.commit()
            flash("Platform gideri kaydedildi.", "success")
            return redirect(url_for("dashboard.product_costs"))
        if request.form.get("form_type") == "advertising":
            raw_start = request.form.get("advertising_day_from", "").strip() or request.form.get("advertising_day", "").strip()
            raw_end = request.form.get("advertising_day_to", "").strip() or raw_start
            try:
                advertising_start = datetime.strptime(raw_start, "%Y-%m-%d").date()
                advertising_end = datetime.strptime(raw_end, "%Y-%m-%d").date()
                amount = float(request.form.get("advertising_amount", "0").replace(",", "."))
                if advertising_end < advertising_start or (advertising_end - advertising_start).days > 730:
                    raise ValueError
                if not 0 <= amount <= 10000000:
                    raise ValueError
            except (TypeError, ValueError):
                flash("Geçerli bir tarih aralığı ve reklam gideri tutarı girin. Aralık en fazla 731 gün olabilir.", "danger")
                return redirect(url_for("dashboard.product_costs"))
            try:
                day = advertising_start
                while day <= advertising_end:
                    expense = DailyAdvertisingExpense.query.filter_by(
                        user_id=current_user.id, day=day
                    ).first()
                    if not expense:
                        expense = DailyAdvertisingExpense(user_id=current_user.id, day=day)
                        db.session.add(expense)
                    expense.amount = amount
                    day += timedelta(days=1)
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Günlük reklam gideri kaydedilemedi user_id=%s", current_user.id)
                flash("Reklam gideri kaydedilemedi. Lütfen tekrar deneyin.", "danger")
                return redirect(url_for("dashboard.product_costs"))
            day_count = (advertising_end - advertising_start).days + 1
            flash(f"{day_count} gün için günlük reklam gideri kaydedildi.", "success")
            return redirect(url_for("dashboard.product_costs"))
        key = request.form.get("product_key", "").strip()
        platform = request.form.get("platform", "").strip()[:30]
        name = request.form.get("product_name", "Ürün").strip()[:180]
        try:
            cost = float(request.form.get("unit_cost", "0").replace(",", "."))
            if cost < 0 or cost > 1000000:
                raise ValueError
        except ValueError:
            flash("Geçerli bir maliyet girin.", "danger")
            return redirect(url_for("dashboard.product_costs"))
        # Maliyet ürün adina aittir; platformdan bagimsiz ortak kayit tutulur.
        normalized_name = " ".join(name.casefold().split())
        matching = ProductCost.query.filter_by(user_id=current_user.id).all()
        row = next((r for r in matching if " ".join((r.product_name or "").casefold().split()) == normalized_name), None)
        if not row:
            row = ProductCost(user_id=current_user.id, platform="all", product_key=normalized_name, product_name=name)
            db.session.add(row)
        row.platform, row.product_key = "all", normalized_name
        row.product_name, row.unit_cost = name, cost
        for other in matching:
            if other is not row and " ".join((other.product_name or "").casefold().split()) == normalized_name:
                other.unit_cost = cost
                db.session.delete(other)
        db.session.commit()
        flash("Ürün maliyeti kaydedildi.", "success")
        return redirect(url_for("dashboard.product_costs", days=request.form.get("days", "30")))

    days = request.args.get("days", "30", type=int)
    days = days if days in (7, 30, 90, 365) else 30
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    try:
        custom_start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
        custom_end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1) if end_date else None
    except ValueError:
        custom_start, custom_end = None, None
        start_date, end_date = "", ""
    selected_platforms = [value.strip() for value in request.args.getlist("platform") if value.strip()]
    platform_filter = set(selected_platforms)
    search = request.args.get("q", "").strip().casefold()
    since = custom_start or (datetime.utcnow() - timedelta(days=days))
    until = custom_end or datetime.utcnow() + timedelta(seconds=1)
    if until <= since:
        since = datetime.utcnow() - timedelta(days=days)
        until = datetime.utcnow() + timedelta(seconds=1)
        start_date, end_date = "", ""
    rows = ProductCost.query.filter_by(user_id=current_user.id).all()
    costs = {" ".join((r.product_name or "").casefold().split()): r for r in rows}
    products = {}
    for order in Order.query.filter(Order.user_id == current_user.id, Order.created_at >= since, Order.created_at < until).all():
        if platform_filter and order.platform not in platform_filter:
            continue
        # Karlılıkta teslim edilen siparişler dahil, yalnızca iptal/iade hariçtir.
        if order.status in PROBLEM_STATUSES:
            continue
        data = _parse_raw_json(order.raw_json)
        for item in _cost_product_lines(order.platform, data):
            key = (order.platform, item["key"])
            row = products.setdefault(key, {"platform": order.platform, "key": item["key"], "name": item["name"], "quantity": 0.0, "revenue": 0.0})
            row["quantity"] += item["quantity"]
            row["revenue"] += item["revenue"]
    # Adisyo siparişleri Order tablosunda değil, hazır günlük raporlarda tutulur.
    if not platform_filter or "adisyo" in platform_filter:
        adisyo_reports = (AdisyoReport.query.join(AdisyoConnection)
                          .join(Integration, AdisyoConnection.integration_id == Integration.id)
                          .filter(Integration.user_id == current_user.id,
                                  AdisyoReport.state == "ready",
                                  AdisyoReport.day >= since.date(),
                                  AdisyoReport.day < until.date()).all())
        for report in adisyo_reports:
            try:
                summary = json.loads(report.summary_json or "{}")
            except (TypeError, ValueError):
                continue
            for item in summary.get("products", []):
                name = str(item.get("name") or "Ürün").strip()
                quantity = float(item.get("quantity") or 0)
                revenue = float(item.get("amount") or 0)
                key = ("adisyo", " ".join(name.casefold().split()))
                row = products.setdefault(key, {"platform": "adisyo", "key": key[1], "name": name, "quantity": 0.0, "revenue": 0.0})
                row["quantity"] += quantity
                row["revenue"] += revenue
    for row in products.values():
        saved = costs.get(" ".join(row["name"].casefold().split()))
        row["cost"] = saved.unit_cost if saved else None
        row["total_cost"] = row["quantity"] * row["cost"] if row["cost"] is not None else None
        row["profit"] = row["revenue"] - row["total_cost"] if row["total_cost"] is not None else None
        row["margin"] = row["profit"] / row["revenue"] * 100 if row["profit"] is not None and row["revenue"] else None
        row["avg_price"] = row["revenue"] / row["quantity"] if row["quantity"] else 0
        row["category"] = _cost_product_category(row["name"])
    category_order = {"Yiyecekler": 0, "İçecekler": 1, "Tatlılar": 2, "Paketleme / Ekstra": 3, "Diğer": 4}
    product_rows = sorted(products.values(), key=lambda r: (-r["revenue"], r["name"]))
    if search:
        product_rows = [r for r in product_rows if search in r["name"].casefold()]
    all_expenses = PlatformExpense.query.filter_by(user_id=current_user.id).all()
    expenses = [e for e in all_expenses if not platform_filter or e.platform in platform_filter or e.platform == "genel"]
    order_counts = {}
    for order in Order.query.filter(Order.user_id == current_user.id, Order.created_at >= since, Order.created_at < until).all():
        if (not platform_filter or order.platform in platform_filter) and not _is_cancelled_order(order) and not _is_refunded_order(order):
            order_counts[order.platform] = order_counts.get(order.platform, 0) + 1
    if not platform_filter or "adisyo" in platform_filter:
        for report in adisyo_reports if 'adisyo_reports' in locals() else []:
            try:
                summary = json.loads(report.summary_json or "{}")
                order_counts["adisyo"] = order_counts.get("adisyo", 0) + max(0, int(summary.get("count") or 0) - int(summary.get("cancelled") or 0))
            except (TypeError, ValueError):
                pass
    order_counts["genel"] = sum(order_counts.values())
    expense_total = sum(e.amount * order_counts.get(e.platform, 0) if e.expense_type == "per_order" else e.amount for e in expenses)
    commissions = {r.platform: r.percentage for r in PlatformCommission.query.filter_by(user_id=current_user.id).all()}
    commission_total = sum(r["revenue"] * commissions.get(r["platform"], 0) / 100 for r in products.values())
    revenue_total = sum(r["revenue"] for r in products.values())
    cost_total = sum(r["total_cost"] or 0 for r in products.values())
    # Günlük özet: iptal/iade siparişleri hariç, ürün maliyeti ve platform kesintileri dahil.
    daily = {}
    for order in Order.query.filter(Order.user_id == current_user.id, Order.created_at >= since, Order.created_at < until).all():
        if platform_filter and order.platform not in platform_filter:
            continue
        if _is_cancelled_order(order) or _is_refunded_order(order):
            continue
        day = order.created_at.date()
        row = daily.setdefault(day, {"date": day, "orders": 0, "platform_orders": {}, "platform_revenue": {}, "products": {}, "revenue": 0.0, "cost": 0.0, "commission": 0.0, "expense": 0.0})
        row["orders"] += 1
        row["platform_orders"][order.platform] = row["platform_orders"].get(order.platform, 0) + 1
        data = _parse_raw_json(order.raw_json)
        for item in _cost_product_lines(order.platform, data):
            row["revenue"] += item["revenue"]
            row["platform_revenue"][order.platform] = row["platform_revenue"].get(order.platform, 0.0) + item["revenue"]
            saved = costs.get(" ".join(item["name"].casefold().split()))
            if saved:
                row["cost"] += item["quantity"] * saved.unit_cost
            product_key = " ".join(item["name"].casefold().split())
            product = row["products"].setdefault(product_key, {"name": item["name"], "quantity": 0.0, "revenue": 0.0, "cost": 0.0})
            product["quantity"] += item["quantity"]
            product["revenue"] += item["revenue"]
            if saved:
                product["cost"] += item["quantity"] * saved.unit_cost
    if not platform_filter or "adisyo" in platform_filter:
        for report in adisyo_reports if 'adisyo_reports' in locals() else []:
            try:
                summary = json.loads(report.summary_json or "{}")
            except (TypeError, ValueError):
                continue
            day = report.day
            row = daily.setdefault(day, {"date": day, "orders": 0, "platform_orders": {}, "platform_revenue": {}, "products": {}, "revenue": 0.0, "cost": 0.0, "commission": 0.0, "expense": 0.0})
            valid_orders = max(0, int(summary.get("count") or 0) - int(summary.get("cancelled") or 0))
            row["orders"] += valid_orders
            row["platform_orders"]["adisyo"] = row["platform_orders"].get("adisyo", 0) + valid_orders
            for item in summary.get("products", []):
                name = str(item.get("name") or "Ürün").strip()
                quantity = float(item.get("quantity") or 0)
                revenue = float(item.get("amount") or 0)
                row["revenue"] += revenue
                row["platform_revenue"]["adisyo"] = row["platform_revenue"].get("adisyo", 0.0) + revenue
                saved = costs.get(" ".join(name.casefold().split()))
                if saved:
                    row["cost"] += quantity * saved.unit_cost
                product_key = " ".join(name.casefold().split())
                product = row["products"].setdefault(product_key, {"name": name, "quantity": 0.0, "revenue": 0.0, "cost": 0.0})
                product["quantity"] += quantity
                product["revenue"] += revenue
                if saved:
                    product["cost"] += quantity * saved.unit_cost
    try:
        advertising_expenses = (DailyAdvertisingExpense.query
                                .filter(DailyAdvertisingExpense.user_id == current_user.id,
                                        DailyAdvertisingExpense.day >= since.date(),
                                        DailyAdvertisingExpense.day < until.date())
                                .order_by(DailyAdvertisingExpense.day.desc()).all())
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Günlük reklam giderleri okunamadı user_id=%s", current_user.id)
        advertising_expenses = []
        flash("Reklam giderleri şu an okunamadı. Sayfa diğer bilgilerle açıldı.", "warning")
    advertising_total = sum(expense.amount for expense in advertising_expenses)
    expense_total += advertising_total
    for expense in advertising_expenses:
        row = daily.setdefault(expense.day, {"date": expense.day, "orders": 0,
                                             "platform_orders": {}, "platform_revenue": {},
                                             "products": {}, "revenue": 0.0, "cost": 0.0,
                                             "commission": 0.0, "expense": 0.0,
                                             "advertising_expense": 0.0})
        row["advertising_expense"] += expense.amount
        row["expense"] += expense.amount
    # Komisyonu günlük/platform cirosu tamamlandıktan sonra bir kez hesapla.
    for row in daily.values():
        row.setdefault("advertising_expense", 0.0)
        row["commission"] = sum(
            revenue * commissions.get(platform, 0) / 100
            for platform, revenue in row["platform_revenue"].items()
        )
    fixed_expenses = 0.0
    for expense in expenses:
        if expense.expense_type == "per_order":
            for row in daily.values():
                count = row["orders"] if expense.platform == "genel" else row["platform_orders"].get(expense.platform, 0)
                row["expense"] += expense.amount * count
        else:
            fixed_expenses += expense.amount
    if daily and fixed_expenses:
        for row in daily.values():
            row["expense"] += fixed_expenses * row["revenue"] / revenue_total if revenue_total else fixed_expenses / len(daily)
    daily_rows = sorted(daily.values(), key=lambda row: row["date"], reverse=True)
    for row in daily_rows:
        row["profit"] = row["revenue"] - row["cost"] - row["commission"] - row["expense"]
        row["margin"] = row["profit"] / row["revenue"] * 100 if row["revenue"] else 0
        row["products"] = sorted(
            ({**product, "profit": product["revenue"] - product["cost"]} for product in row["products"].values()),
            key=lambda product: (-product["revenue"], product["name"]),
        )
    return render_template("dashboard/product_costs.html", products=product_rows, days=days,
                           platform_label=platform_label, expenses=expenses, expense_total=expense_total,
                           commissions=commissions, commission_total=commission_total, order_counts=order_counts,
                           revenue_total=revenue_total, cost_total=cost_total,
                           profit_total=revenue_total - cost_total - expense_total - commission_total,
                           selected_platforms=selected_platforms, search=search, daily_rows=daily_rows,
                           start_date=start_date, end_date=end_date,
                           advertising_expenses=advertising_expenses,
                           advertising_total=advertising_total,
                           today=datetime.now(TURKEY_TZ).date().isoformat())


@dashboard_bp.route("/maliyet-girisi", methods=["GET", "POST"])
@login_required
def product_cost_entry():
    """Eksik ürün maliyetlerini tek ekrandan toplu kaydetme."""
    if request.method == "POST":
        names = request.form.getlist("product_name")
        saved = 0
        existing = ProductCost.query.filter_by(user_id=current_user.id).all()
        by_name = {" ".join((row.product_name or "").casefold().split()): row for row in existing}
        for index, name in enumerate(names):
            name = name.strip()[:180]
            raw = request.form.get(f"unit_cost_{index}", "").strip().replace(",", ".")
            if not name or not raw:
                continue
            try:
                amount = float(raw)
                if amount < 0 or amount > 1000000:
                    continue
            except ValueError:
                continue
            key = " ".join(name.casefold().split())
            row = by_name.get(key)
            if not row:
                row = ProductCost(user_id=current_user.id, platform="all", product_key=key, product_name=name)
                db.session.add(row)
                by_name[key] = row
            row.platform, row.product_key, row.product_name, row.unit_cost = "all", key, name, amount
            saved += 1
        db.session.commit()
        flash(f"{saved} ürün maliyeti kaydedildi.", "success")
        return redirect(url_for("dashboard.product_cost_entry"))

    since = datetime.utcnow() - timedelta(days=365)
    names = set()
    for order in Order.query.filter(Order.user_id == current_user.id, Order.created_at >= since).all():
        if _is_cancelled_order(order) or _is_refunded_order(order):
            continue
        for item in _cost_product_lines(order.platform, _parse_raw_json(order.raw_json)):
            names.add(" ".join(item["name"].casefold().split()))
    for report in (AdisyoReport.query.join(AdisyoConnection)
                   .join(Integration, AdisyoConnection.integration_id == Integration.id)
                   .filter(Integration.user_id == current_user.id, AdisyoReport.state == "ready",
                           AdisyoReport.day >= since.date()).all()):
        try:
            summary = json.loads(report.summary_json or "{}")
            names.update(" ".join(str(item.get("name") or "Ürün").casefold().split())
                         for item in summary.get("products", []))
        except (TypeError, ValueError):
            continue
    existing = ProductCost.query.filter_by(user_id=current_user.id).all()
    cost_names = {" ".join((row.product_name or "").casefold().split()) for row in existing}
    missing = sorted((name for name in names if name not in cost_names), key=str.casefold)
    return render_template("dashboard/product_cost_entry.html", products=missing)


def _cost_product_category(name: str) -> str:
    text = (name or "").casefold()
    if any(word in text for word in ("ayran", "kahve", "latte", "americano", "çay", "cay", "mocha", "soda", "su ", "ice", "matcha", "cola", "şerbet", "serbet")):
        return "İçecekler"
    if any(word in text for word in ("kek", "pasta", "kurabiye", "cookie", "tiramisu", "tatlı", "tatli", "dondurma", "marlenka", "brownie")):
        return "Tatlılar"
    if any(word in text for word in ("poşet", "poset", "peçete", "pecete", "viyol", "paket", "çatal", "catal", "sos")):
        return "Paketleme / Ekstra"
    if any(word in text for word in ("sandviç", "sandvic", "tost", "burger", "köfte", "kofte", "döner", "doner", "pizza", "çorba", "corba", "ekmek", "salata", "makarna", "tavuk")):
        return "Yiyecekler"
    return "Diğer"


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
        flash("Bu Migros siparişi için işlem kullanılamaz.", "warning")
        return _order_action_redirect(order)

    intg = Integration.query.filter_by(user_id=current_user.id, platform="migros", is_active=True).first()
    if not intg or not intg.migros_api_key or not intg.migros_store_id:
        flash("Migros API Key ve Store ID bilgileri eksik.", "danger")
        return _order_action_redirect(order)
    secret = current_app.config.get("MIGROS_SECRET_KEY", "")
    if not secret:
        flash("MIGROS_SECRET_KEY Railway tarafında tanımlı değil.", "danger")
        return _order_action_redirect(order)

    raw = detail.get("raw") or {}
    base_url = current_app.config.get("MIGROS_API_BASE")
    cancel_reason_id = request.form.get("cancel_reason_id", "").strip()
    if action in {"reject", "cancel"} and not cancel_reason_id:
        flash("Migros red/iptal işlemi için iptal sebebi seçilmelidir.", "warning")
        return _order_action_redirect(order)

    try:
        if action == "cancel":
            user_id = _migros_user_id(raw)
            if not user_id:
                flash("Migros iptal işlemi için sipariş payload'unda User ID bulunamadı.", "danger")
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
        order.mark_status_notified(next_status)
        intg.last_sync_at = datetime.utcnow()
        intg.last_error = None
        db.session.commit()

        user = current_user
        amount = f"{order.total_price or 0:.2f} ₺"
        items = migros.summarize_items(raw)
        status_message = migros.format_order_status_update(
            raw,
            next_status,
            cancel_reason_id=cancel_reason_id,
        )
        is_problem = next_status in {migros.ORDER_STATUS_REJECTED, "Cancelled"}
        should_notify = intg.notify_cancel if is_problem else intg.notify_status_change
        if should_notify:
            title = (
                "Sipariş reddedildi · Migros Yemek"
                if next_status == migros.ORDER_STATUS_REJECTED
                else "Sipariş iptal · Migros Yemek"
                if next_status == "Cancelled"
                else f"{status_label(next_status)} · Migros Yemek"
            )
            send_to_user(
                user,
                status_message,
                wa=[title, order.order_number or order.external_id, items, amount],
            )
            print(
                f"[MIGROS] manuel durum bildirimi "
                f"#{order.order_number or order.external_id} -> {next_status} "
                f"(user={order.user_id})"
            )
        flash(f"Migros işlemi gönderildi: {selected['label']}", "success")
    except Exception as e:
        intg.last_error = f"Migros sipariş işlemi: {e}"[:300]
        db.session.commit()
        flash(f"Migros işlemi gönderilemedi: {e}", "danger")
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
    if not intg or not (intg.ys_vendor_id or intg.ys_store_id):
        flash("Yemeksepeti POS remoteId bilgisi eksik.", "danger")
        return _order_action_redirect(order)
    username = current_app.config.get("YEMEKSEPETI_POS_USERNAME", "")
    password = current_app.config.get("YEMEKSEPETI_POS_PASSWORD", "")
    if not username or not password:
        flash("Yemeksepeti POS credential bilgileri henüz tanımlanmadı.", "danger")
        return _order_action_redirect(order)

    raw = _parse_raw_json(order.raw_json)
    reason = request.form.get("rejection_reason", "OTHER").strip().upper()
    method, callback_url, body, next_status = ys.pos_action(
        raw, action, str(order.id), rejection_reason=reason
    )

    try:
        ys.send_pos_callback(
            method,
            callback_url,
            body,
            username,
            password,
            intg.ys_environment or "live",
            current_app.config.get("YEMEKSEPETI_POS_API_BASE", ""),
        )
        order.status = next_status
        order.raw_json = json.dumps(raw, ensure_ascii=False)
        intg.last_sync_at = datetime.utcnow()
        intg.last_error = None
        db.session.commit()
        flash(f"Yemeksepeti işlemi gönderildi: {selected['label']}", "success")
    except Exception as e:
        intg.last_error = f"Yemeksepeti sipariş işlemi: {e}"[:300]
        db.session.commit()
        current_app.logger.warning("Yemeksepeti POS islemi basarisiz order_id=%s: %s", order.id, e)
        flash(f"Yemeksepeti işlemi gönderilemedi: {e}", "danger")
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
    watch_id = request.args.get("watch_id", 0, type=int) or 0
    watch_ids = {int(value) for value in request.args.get("watch_ids", "").split(",") if value.isdigit()}
    if watch_id:
        watch_ids.add(watch_id)
    latest_order_id = db.session.query(func.max(Order.id)).filter_by(user_id=current_user.id).scalar() or 0
    watch_pending = None
    pending_by_id = {}
    if watch_ids:
        watched_orders = Order.query.filter(Order.user_id == current_user.id, Order.id.in_(watch_ids)).all()
        for watched_order in watched_orders:
            pending_by_id[str(watched_order.id)] = bool(
                watched_order.status in PENDING_STATUSES or not (watched_order.status or "").strip()
            )
        watch_pending = pending_by_id.get(str(watch_id), False) if watch_id else None
    if latest_order_id <= since_id:
        return jsonify({"latest_id": latest_order_id, "orders": [], "watch_pending": watch_pending, "pending_by_id": pending_by_id})

    new_orders = (
        Order.query
        .filter(Order.user_id == current_user.id, Order.id > since_id)
        .filter(or_(Order.status.is_(None), ~Order.status.in_(sorted(ACTIVE_EXCLUDED_STATUSES))))
        .order_by(Order.id.asc())
        .limit(20)
        .all()
    )
    if not new_orders:
        return jsonify({"latest_id": latest_order_id, "orders": [], "watch_pending": watch_pending, "pending_by_id": pending_by_id})
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
    return jsonify({"latest_id": next_since_id, "orders": payload, "watch_pending": watch_pending, "pending_by_id": pending_by_id})


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
            "action": "accept",
            "label": "Kabul et",
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

    urls = ys.callback_urls(raw)
    if status == ys.STATUS_RECEIVED:
        if urls.get("orderAcceptedUrl"):
            actions.append({"action": "accept", "label": "Kabul et", "next_status": ys.STATUS_ACCEPTED})
        if urls.get("orderRejectedUrl"):
            actions.append({"action": "reject", "label": "Reddet", "next_status": ys.STATUS_REJECTED, "needs_reason": True})
    if status in {ys.STATUS_RECEIVED, ys.STATUS_ACCEPTED} and urls.get("orderPreparedUrl"):
        actions.append({"action": "prepared", "label": "Hazırlandı yap", "next_status": ys.STATUS_PREPARED})
    if status in {ys.STATUS_ACCEPTED, ys.STATUS_PREPARED} and urls.get("orderPickedUpUrl"):
        actions.append({"action": "picked_up", "label": "Teslim alındı yap", "next_status": ys.STATUS_DISPATCHED})

    intg = Integration.query.filter_by(
        user_id=order.user_id, platform=ys.PLATFORM, is_active=True
    ).first()
    disabled_reason = None
    if not intg or not (intg.ys_vendor_id or intg.ys_store_id):
        disabled_reason = "Önce Yemeksepeti POS remoteId bilgisini kaydet."
    elif not current_app.config.get("YEMEKSEPETI_POS_USERNAME") or not current_app.config.get("YEMEKSEPETI_POS_PASSWORD"):
        disabled_reason = "Yemeksepeti POS credential bilgileri geldiğinde bu işlem açılacak."
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
            actions.append({"action": "prepared", "label": "Hazırlandı yap", "next_status": migros.ORDER_STATUS_PREPARED})
        if status == "Prepared":
            actions.append({"action": "delivery", "label": "Yola çıktı yap", "next_status": migros.ORDER_STATUS_DELIVERY})
        actions.append({"action": "cancel", "label": "İptal et", "next_status": "Cancelled", "needs_reason": True})
    elif status == "Delivery":
        actions.append({"action": "completed", "label": "Tamamlandı yap", "next_status": migros.ORDER_STATUS_COMPLETED})
        actions.append({"action": "cancel", "label": "İptal et", "next_status": "Cancelled", "needs_reason": True})
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


def _cost_product_lines(platform, data):
    """Farklı platform payload'larını maliyet ekranının ortak satırlarına çevirir."""
    lines = []
    if platform == "migros":
        source = data.get("items") or []
        for item in source:
            qty = float(item.get("amount") or item.get("quantity") or 1)
            name = str(item.get("name") or "Ürün")
            revenue = float(item.get("totalPrice") or item.get("price") or item.get("unitPrice") or 0) * qty
            lines.append({"key": name, "name": name, "quantity": qty, "revenue": revenue})
    elif platform in (tmp.PLATFORM, hb.PLATFORM):
        source = tmp.lines(data) if platform == tmp.PLATFORM else hb.lines(data)
        getter = tmp if platform == tmp.PLATFORM else hb
        for item in source:
            qty = getter.line_quantity(item)
            name = getter.line_name(item)
            lines.append({"key": str(item.get("barcode") or item.get("id") or name), "name": name,
                          "quantity": qty, "revenue": float(item.get("totalPrice") or item.get("price") or 0) * qty})
    elif platform == ys.PLATFORM:
        for item in ys.items(data):
            qty = ys.item_quantity(item)
            name = ys.item_name(item)
            lines.append({"key": str(item.get("id") or name), "name": name, "quantity": qty,
                          "revenue": float(item.get("total_price") or item.get("unit_price") or 0) * qty})
    else:
        for item in data.get("lines") or []:
            qty = tgo._line_quantity(item)
            name = str(item.get("name") or item.get("productName") or "Ürün")
            revenue = float(item.get("totalPrice") or item.get("total") or item.get("price") or 0)
            lines.append({"key": str(item.get("barcode") or item.get("productId") or name), "name": name,
                          "quantity": qty, "revenue": revenue if revenue and qty <= 1 else revenue * qty})
    return lines


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
        "customer_phone": customer_data.get("mobilePhone") or customer_data.get("phone_number") or "",
        "order_created_at": _ys_order_created_at(raw),
        "store": (raw.get("platformRestaurant") or {}).get("id") or ys.client(raw).get("name") or "-",
        "source": "Yemeksepeti",
        "delivery": ys.delivery_label(raw),
        "payment": order.payment_type or ys.payment_type(raw),
        "address": ys.address_text(raw),
        "address_direction": ys.address_instructions(raw),
        "flags": ["Test siparişi - mutfağa hazırlatmayın"] if raw.get("test") else [],
        "order_note": order.customer_note or "",
    }


def _ys_order_created_at(raw: dict) -> str:
    sys_data = raw.get("sys") or {}
    value = str(raw.get("createdAt") or sys_data.get("created_at") or "").strip()
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
        "customer_id": customer.get("id") or raw.get("userId") or raw.get("UserId") or "",
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
                record_whatsapp_result(
                    current_user,
                    "accepted",
                    message_id=err if isinstance(err, str) and err.startswith("wamid.") else None,
                )
                results.append("WhatsApp ✅ (şablon)")
            else:
                ok2, err2 = whatsapp.send_text(num, wa_text, tok, pnid, ver)
                if ok2:
                    record_whatsapp_result(
                        current_user,
                        "accepted",
                        message_id=err2 if isinstance(err2, str) and err2.startswith("wamid.") else None,
                    )
                    results.append("WhatsApp ✅ (serbest metin)")
                else:
                    record_whatsapp_result(
                        current_user,
                        "failed",
                        error=f"{err or 'Şablon hatası'} | Serbest metin: {err2}",
                    )
                    results.append(f"WhatsApp ❌ ({err or err2})")
        else:
            record_whatsapp_result(
                current_user,
                "skipped",
                error="WhatsApp numarası veya credential eksik",
            )
            results.append("WhatsApp ⏭ (numara/credential eksik)")

    flash("Test sonucu: " + (" · ".join(results) if results else "kanal ayarlı değil"), "info")
    return redirect(url_for("dashboard.profile"))

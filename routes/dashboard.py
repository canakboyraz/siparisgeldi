"""Panel: özet, Telegram bağlama, TrendyolGo kurulum, siparişler, profil."""
import secrets
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user

from extensions import db
from models import Integration, Order
from integrations.trendyolgo import test_connection
from integrations import migros

dashboard_bp = Blueprint("dashboard", __name__)


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
        if channel in ("telegram", "whatsapp", "both"):
            current_user.notification_channel = channel
        db.session.commit()
        flash("WhatsApp ayarların kaydedildi.", "success")
        return redirect(url_for("dashboard.connect_whatsapp"))
    return render_template("dashboard/connect_whatsapp.html")


@dashboard_bp.route("/whatsapp/test", methods=["POST"])
@login_required
def test_whatsapp():
    """WhatsApp'a örnek sipariş bildirimi gönderir (şablon → serbest metin fallback)."""
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
    intg = Integration.query.filter_by(user_id=current_user.id, platform="trendyolgo").first()

    if request.method == "POST":
        supplier_id = request.form.get("supplier_id", "").strip()
        api_key     = request.form.get("api_key", "").strip()
        api_secret  = request.form.get("api_secret", "").strip()

        if not supplier_id or not api_key or not api_secret:
            flash("Tüm alanlar zorunludur.", "danger")
            return render_template("dashboard/trendyolgo_setup.html", intg=intg)

        ok, msg, _ = test_connection(supplier_id, api_key, api_secret)
        if not ok:
            flash(f"API bağlantısı başarısız: {msg}", "danger")
            return render_template("dashboard/trendyolgo_setup.html", intg=intg)

        if not intg:
            intg = Integration(user_id=current_user.id, platform="trendyolgo")
            db.session.add(intg)

        intg.tgo_supplier_id = supplier_id
        intg.tgo_api_key     = api_key
        intg.tgo_api_secret  = api_secret
        intg.is_active       = True
        db.session.commit()

        flash(f"✅ TrendyolGo bağlandı! {msg}", "success")
        if not current_user.telegram_connected:
            flash("Bildirim alabilmek için Telegram'ı da bağlayın.", "warning")
        return redirect(url_for("dashboard.index"))

    return render_template("dashboard/trendyolgo_setup.html", intg=intg)


# ── Migros Yemek ────────────────────────────────────────────────────────────

@dashboard_bp.route("/migros", methods=["GET", "POST"])
@login_required
def migros_setup():
    intg = Integration.query.filter_by(user_id=current_user.id, platform="migros").first()
    migros_api_base = current_app.config.get("MIGROS_API_BASE")

    if request.method == "POST":
        api_key  = request.form.get("api_key", "").strip()
        store_id = request.form.get("store_id", "").strip()
        group_id = request.form.get("group_id", "").strip()

        if not api_key or not store_id:
            flash("Restoran API Key ve Store (Restoran) ID zorunludur.", "danger")
            return render_template("dashboard/migros_setup.html", intg=intg,
                                   webhook_urls=_migros_webhook_urls(),
                                   migros_api_base=migros_api_base)

        # Bağlantıyı doğrula (GetStoreGroups — şifreleme gerektirmez, sadece api key)
        secret = current_app.config.get("MIGROS_SECRET_KEY", "")
        ok, msg, _ = migros.test_connection(api_key, secret, migros_api_base)

        if not intg:
            intg = Integration(user_id=current_user.id, platform="migros")
            db.session.add(intg)

        intg.migros_api_key  = api_key
        intg.migros_store_id = store_id
        intg.migros_group_id = group_id
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

    return render_template("dashboard/migros_setup.html", intg=intg,
                           webhook_urls=_migros_webhook_urls(),
                           migros_api_base=migros_api_base)


def _migros_webhook_urls():
    """Migros'a iletilecek FİRMA seviyesi webhook URL'leri (herkes için aynı)."""
    return {
        "order_created":  url_for("webhooks.migros_order_created", _external=True),
        "order_canceled": url_for("webhooks.migros_order_canceled", _external=True),
        "delivery_status": url_for("webhooks.migros_delivery_status", _external=True),
    }


@dashboard_bp.route("/entegrasyon/<int:intg_id>/durum", methods=["POST"])
@login_required
def toggle_integration(intg_id):
    intg = Integration.query.filter_by(id=intg_id, user_id=current_user.id).first_or_404()
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


# ── Profil ──────────────────────────────────────────────────────────────────

@dashboard_bp.route("/profil", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        name       = request.form.get("name", "").strip()
        current_pw = request.form.get("current_password", "")
        new_pw     = request.form.get("new_password", "")
        confirm_pw = request.form.get("confirm_password", "")

        if name:
            current_user.name = name

        # Bildirim kanalı + WhatsApp numarası
        channel = request.form.get("notification_channel", "").strip()
        if channel in ("telegram", "whatsapp", "both"):
            current_user.notification_channel = channel
        wa_number = request.form.get("whatsapp_number", "").strip()
        current_user.whatsapp_number = wa_number or None

        if current_pw or new_pw:
            if not current_user.check_password(current_pw):
                flash("Mevcut şifre hatalı.", "danger")
                return render_template("dashboard/profile.html")
            if new_pw != confirm_pw:
                flash("Yeni şifreler eşleşmiyor.", "danger")
                return render_template("dashboard/profile.html")
            if len(new_pw) < 6:
                flash("Şifre en az 6 karakter olmalı.", "danger")
                return render_template("dashboard/profile.html")
            current_user.set_password(new_pw)

        db.session.commit()
        flash("Profil güncellendi.", "success")

    return render_template("dashboard/profile.html")


@dashboard_bp.route("/test-bildirim", methods=["POST"])
@login_required
def send_test_notification():
    """Seçili kanala test bildirimi gönderir. WhatsApp'ta önce onaylı şablonu dener,
    olmazsa (24s müşteri penceresi açıksa) serbest metne düşer — böylece şablon onayı
    beklenmeden de test edilebilir."""
    from notifications import whatsapp, telegram as tg
    cfg = current_app.config
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

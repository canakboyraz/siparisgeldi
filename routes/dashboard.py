"""Panel: özet, Telegram bağlama, TrendyolGo kurulum, siparişler, profil."""
import json
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, or_

from extensions import db
from models import Integration, Order
from integrations import migros, trendyolgo as tgo

dashboard_bp = Blueprint("dashboard", __name__)

PENDING_STATUSES = {"Created", "NEW_PENDING", "Pending", "New"}
PREPARING_STATUSES = {"Picking", "Invoiced", "Approved", "Prepared"}
DELIVERY_STATUSES = {"Shipped", "Delivery", "OnDelivery", "On_Delivery"}
CANCELLED_STATUSES = {"Cancelled", "UnSupplied", "Rejected"}
REFUNDED_STATUSES = {"Refunded", "Returned"}
PROBLEM_STATUSES = CANCELLED_STATUSES | REFUNDED_STATUSES
DONE_STATUSES = {"Delivered", "Completed"}
ACTIVE_EXCLUDED_STATUSES = PROBLEM_STATUSES | DONE_STATUSES
UNACCEPTED_WARNING_SECONDS = 120


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

        ok, msg, _ = tgo.test_connection(supplier_id, api_key, api_secret)
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


@dashboard_bp.route("/siparis/<int:order_id>")
@login_required
def order_detail(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    detail = _order_detail_context(order)
    return render_template("dashboard/order_detail.html", order=order, detail=detail)


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
    rows = [_active_order_row(order, now) for order in orders_paged.items]

    all_user_orders = base_query.with_entities(Order.status, Order.created_at).all()
    counts = _active_order_counts(all_user_orders, now)

    return render_template(
        "dashboard/active_orders.html",
        orders=orders_paged,
        rows=rows,
        counts=counts,
        filtered_total=filtered_total,
        filters={
            "platform": platform,
            "durum": status_group,
            "q": search,
            "date_from": date_from,
            "date_to": date_to,
        },
        groups=_status_group_options(),
    )


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


def _active_order_row(order: Order, now: datetime) -> dict:
    age_seconds = int((now - order.created_at).total_seconds()) if order.created_at else 0
    is_pending = order.status in PENDING_STATUSES
    return {
        "order": order,
        "age_minutes": max(0, age_seconds // 60),
        "is_unaccepted_warning": is_pending and age_seconds >= UNACCEPTED_WARNING_SECONDS,
        "group": _order_group(order.status),
    }


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


def _order_detail_context(order: Order) -> dict:
    raw = _parse_raw_json(order.raw_json)
    if order.platform == "migros":
        return _migros_detail_context(order, raw)
    if order.platform == "trendyolgo":
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
            "note": "",
            "details": details,
        })
    return items


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
        "customer": customer.get("fullName") or "-",
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
        items.append({
            "name": item.get("name") or "?",
            "quantity": item.get("amount") or 1,
            "note": item.get("note") or "",
            "details": [_display_detail_text(part) for part in migros._item_detail_parts(item)],
        })
    return items


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

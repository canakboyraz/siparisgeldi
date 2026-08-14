"""Arka plan iş yöneticisi (APScheduler).

- Her N saniyede aktif TrendyolGo entegrasyonlarını sorgular → yeni sipariş /
  statü değişimi bildirimi gönderir.
- Her N saniyede merkezi bota gelen /start olaylarını işleyip kullanıcı
  hesaplarına Telegram chat_id bağlar.
- Her gece 23:45 günlük özet raporu gönderir.
"""
import json
from datetime import datetime, timedelta

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import current_app

from extensions import db
from models import Integration, Order, User, AppState
from integrations import getir, hepsiburada as hb, trendyol_marketplace as tmp, trendyolgo as tgo, yemeksepeti as ys
from notifications import telegram
from notifications.dispatcher import send_to_user
from utils import status_label

TURKEY_TZ = pytz.timezone("Europe/Istanbul")
scheduler = BackgroundScheduler(timezone=TURKEY_TZ)

TGO_UNACCEPTED_ALERT_STATUS = "UNACCEPTED_2MIN"
TGO_FOOD_PLATFORM = "trendyolgo"
TGO_MARKET_PLATFORM = "trendyolgo_market"

CANCELLED_ORDER_STATUSES = {
    "Cancelled",
    "Canceled",
    "CANCELED",
    "CANCELLED",
    "UnSupplied",
    "Rejected",
    "REJECTED",
    "AdminCancelled",
    "AutoCancelled",
}

REFUNDED_ORDER_STATUSES = {
    "Refunded",
    "Refund",
    "Returned",
    "Return",
    "PartiallyRefunded",
    "PartialRefunded",
    "RETURNED",
    "REFUNDED",
}


def _hb_api_base(environment: str) -> str:
    if environment == "test":
        return current_app.config.get("HEPSIBURADA_API_BASE_TEST")
    return current_app.config.get("HEPSIBURADA_API_BASE_LIVE")


# ── Sipariş polling ─────────────────────────────────────────────────────────

def poll_trendyolgo(app):
    with app.app_context():
        integrations = Integration.query.filter(
            Integration.platform.in_([TGO_FOOD_PLATFORM, TGO_MARKET_PLATFORM]),
            Integration.is_active.is_(True),
        ).all()
        for intg in integrations:
            if not intg.tgo_supplier_id or not intg._tgo_api_key:
                continue
            try:
                _process_tgo(intg)
                intg.last_sync_at = datetime.utcnow()
                intg.last_error = None
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                intg.last_error = str(e)[:300]
                db.session.commit()
                print(f"[WORKER TGO] Hata user={intg.user_id}: {e}")


def poll_trendyol_marketplace(app):
    with app.app_context():
        integrations = Integration.query.filter_by(platform=tmp.PLATFORM, is_active=True).all()
        for intg in integrations:
            if not intg.tmp_supplier_id or not intg._tmp_api_key:
                continue
            try:
                _process_tmp(intg)
                intg.last_sync_at = datetime.utcnow()
                intg.last_error = None
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                intg.last_error = str(e)[:300]
                db.session.commit()
                print(f"[WORKER TMP] Hata user={intg.user_id}: {e}")


def poll_hepsiburada(app):
    with app.app_context():
        integrations = Integration.query.filter_by(platform=hb.PLATFORM, is_active=True).all()
        for intg in integrations:
            if not intg.hb_merchant_id or not intg.hb_username or not intg._hb_service_key:
                continue
            try:
                _process_hb(intg)
                intg.last_sync_at = datetime.utcnow()
                intg.last_error = None
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                intg.last_error = str(e)[:300]
                db.session.commit()
                print(f"[WORKER HB] Hata user={intg.user_id}: {e}")


def _process_hb(intg):
    since = (intg.last_sync_at or intg.created_at or datetime.utcnow()) - timedelta(minutes=20)
    environment = intg.hb_environment or "live"
    base = _hb_api_base(environment)
    orders = hb.get_open_orders(
        intg.hb_merchant_id,
        intg.hb_username,
        intg.hb_service_key,
        environment=environment,
        since=since,
        override_base=base,
    )
    if intg.hb_auto_packaging:
        orders.extend(hb.get_packages(
            intg.hb_merchant_id,
            intg.hb_username,
            intg.hb_service_key,
            environment=environment,
            since=since,
            override_base=base,
        ))
    cancellations = hb.get_cancelled_orders(
        intg.hb_merchant_id,
        intg.hb_username,
        intg.hb_service_key,
        environment=environment,
        since=since,
        override_base=base,
    )
    user = db.session.get(User, intg.user_id)

    for order_data in orders:
        _upsert_hb_order(intg, user, order_data, is_cancel=False)
    for order_data in cancellations:
        _upsert_hb_order(intg, user, order_data, is_cancel=True)


def _upsert_hb_order(intg, user, order_data: dict, is_cancel: bool = False):
    fields = hb.extract_order_fields(order_data)
    if not fields["external_id"]:
        return
    if is_cancel:
        fields["status"] = "Cancelled"

    existing = Order.query.filter_by(
        user_id=intg.user_id, platform=hb.PLATFORM, external_id=fields["external_id"]
    ).first()

    if not existing:
        order = Order(
            user_id=intg.user_id,
            platform=hb.PLATFORM,
            raw_json=json.dumps(order_data, ensure_ascii=False),
            **fields,
        )
        order.mark_status_notified("Cancelled" if is_cancel else "INITIAL")
        db.session.add(order)
        db.session.commit()

        if is_cancel and intg.notify_cancel:
            amount = f"{fields['total_price']:.2f} ₺"
            send_to_user(
                user,
                hb.format_cancel_message(order_data),
                wa=["Sipariş iptal · Hepsiburada", fields["order_number"], hb.summarize_items(order_data), amount],
            )
            print(f"[HB] iptal #{fields['order_number']} (user={intg.user_id})")
        elif not is_cancel and intg.notify_new_order:
            amount = f"{fields['total_price']:.2f} ₺"
            send_to_user(
                user,
                hb.format_new_order_message(order_data),
                wa=["Yeni sipariş · Hepsiburada", fields["order_number"], hb.summarize_items(order_data), amount],
            )
            print(f"[HB] yeni siparis #{fields['order_number']} (user={intg.user_id})")
        return

    current_status = fields["status"]
    if existing.status != current_status:
        existing.status = current_status
        existing.order_number = fields["order_number"] or existing.order_number
        existing.total_price = fields["total_price"]
        existing.payment_type = fields["payment_type"]
        existing.customer_note = fields["customer_note"]
        existing.raw_json = json.dumps(order_data, ensure_ascii=False)

    wants = intg.notify_cancel if is_cancel else intg.notify_status_change
    if current_status in hb.STATUS_NOTIFY and not existing.is_status_notified(current_status) and wants:
        existing.mark_status_notified(current_status)
        db.session.commit()
        amount = f"{fields['total_price']:.2f} ₺"
        if is_cancel:
            send_to_user(
                user,
                hb.format_cancel_message(order_data),
                wa=["Sipariş iptal · Hepsiburada", fields["order_number"], hb.summarize_items(order_data), amount],
            )
        else:
            send_to_user(
                user,
                hb.format_status_message(order_data, current_status),
                wa=[f"{status_label(current_status)} · Hepsiburada", fields["order_number"], hb.summarize_items(order_data), amount],
            )
        print(f"[HB] durum #{fields['order_number']} -> {current_status} (user={intg.user_id})")
    else:
        db.session.commit()


def _process_tmp(intg):
    since = (intg.last_sync_at or intg.created_at or datetime.utcnow()) - timedelta(minutes=10)
    orders = tmp.get_orders(
        intg.tmp_supplier_id,
        intg.tmp_api_key,
        intg.tmp_api_secret,
        base_url=current_app.config.get("TRENDYOL_MARKETPLACE_API_BASE"),
        since=since,
    )
    user = db.session.get(User, intg.user_id)

    for order_data in orders:
        fields = tmp.extract_order_fields(order_data)
        if not fields["external_id"]:
            continue

        existing = Order.query.filter_by(
            user_id=intg.user_id, platform=tmp.PLATFORM, external_id=fields["external_id"]
        ).first()

        if not existing:
            order = Order(
                user_id=intg.user_id,
                platform=tmp.PLATFORM,
                raw_json=json.dumps(order_data, ensure_ascii=False),
                **fields,
            )
            order.mark_status_notified("INITIAL")
            db.session.add(order)
            db.session.commit()

            if intg.notify_new_order:
                amount = f"{fields['total_price']:.2f} ₺"
                send_to_user(
                    user,
                    tmp.format_new_order_message(order_data),
                    wa=["Yeni pazaryeri siparişi · Trendyol", fields["order_number"], tmp.whatsapp_items_summary(order_data), amount],
                )
                print(f"[TMP] yeni siparis #{fields['order_number']} (user={intg.user_id})")
            continue

        current_status = fields["status"]
        if existing.status != current_status:
            existing.status = current_status
            existing.order_number = fields["order_number"] or existing.order_number
            existing.total_price = fields["total_price"]
            existing.payment_type = fields["payment_type"]
            existing.customer_note = fields["customer_note"]
            existing.raw_json = json.dumps(order_data, ensure_ascii=False)

        is_cancel = _is_cancelled_order(existing)
        is_refund = _is_refunded_order(existing)
        wants = intg.notify_cancel if (is_cancel or is_refund) else intg.notify_status_change
        if current_status in tmp.STATUS_NOTIFY and not existing.is_status_notified(current_status) and wants:
            existing.mark_status_notified(current_status)
            db.session.commit()
            amount = f"{fields['total_price']:.2f} ₺"
            send_to_user(
                user,
                tmp.format_status_message(order_data, current_status),
                wa=[f"{status_label(current_status)} · Trendyol Pazaryeri", fields["order_number"], tmp.whatsapp_items_summary(order_data), amount],
            )
            print(f"[TMP] durum #{fields['order_number']} -> {current_status} (user={intg.user_id})")
        else:
            db.session.commit()


def _process_tgo_legacy(intg):
    orders = tgo.get_orders(intg.tgo_supplier_id, intg.tgo_api_key, intg.tgo_api_secret)
    user = db.session.get(User, intg.user_id)

    for order_data in orders:
        external_id    = order_data.get("id")
        current_status = order_data.get("packageStatus", "")
        order_number   = order_data.get("orderNumber", "")
        if not external_id:
            continue

        existing = Order.query.filter_by(
            user_id=intg.user_id, platform="trendyolgo", external_id=str(external_id)
        ).first()

        if not existing:
            # Yeni sipariş
            order = Order(
                user_id=intg.user_id, platform="trendyolgo",
                external_id=str(external_id), order_number=str(order_number),
                status=current_status, total_price=order_data.get("totalPrice", 0) or 0,
                payment_type=(order_data.get("payment") or {}).get("paymentType", ""),
                app_source=(order_data.get("userInformation") or {}).get("appName", ""),
                customer_note=order_data.get("customerNote", ""),
                raw_json=json.dumps(order_data, ensure_ascii=False),
            )
            order.mark_status_notified("INITIAL")
            db.session.add(order)
            db.session.commit()

            if intg.notify_new_order:
                amount = f"{order_data.get('totalPrice', 0) or 0:.2f} ₺"
                send_to_user(user, tgo.format_new_order_message(order_data),
                             wa=["Yeni sipariş · Trendyol Go", str(order_number),
                                 tgo.summarize_items(order_data), amount])
                print(f"[TGO] 🆕 #{order_number} (user={intg.user_id})")
        else:
            # Statü değişimi
            if existing.status != current_status:
                existing.status = current_status
                existing.raw_json = json.dumps(order_data, ensure_ascii=False)

            if _should_alert_unaccepted_tgo(existing, current_status, intg):
                existing.mark_status_notified(TGO_UNACCEPTED_ALERT_STATUS)
                db.session.commit()
                amount = f"{order_data.get('totalPrice', 0) or 0:.2f} ₺"
                send_to_user(user, _format_unaccepted_tgo_message(order_data),
                             wa=["Acil: siparis kabul edilmedi", str(order_number),
                                 tgo.summarize_items(order_data), amount])
                print(f"[TGO] ⚠️ #{order_number} 2 dk kabul edilmedi (user={intg.user_id})")
                continue

            is_cancel = current_status in ("Cancelled", "UnSupplied")
            wants = intg.notify_cancel if is_cancel else intg.notify_status_change

            if (current_status in tgo.STATUS_NOTIFY
                    and not existing.is_status_notified(current_status) and wants):
                existing.mark_status_notified(current_status)
                db.session.commit()
                amount = f"{order_data.get('totalPrice', 0) or 0:.2f} ₺"
                send_to_user(user, tgo.format_status_message(order_data, current_status),
                             wa=[f"{status_label(current_status)} · Trendyol Go", str(order_number),
                                 tgo.summarize_items(order_data), amount])
                print(f"[TGO] 🔄 #{order_number} → {current_status} (user={intg.user_id})")
            else:
                db.session.commit()


def _should_alert_unaccepted_tgo(order: Order, current_status: str, intg: Integration) -> bool:
    """Return True once when a TrendyolGo order waits in Created for 2+ minutes."""
    from flask import current_app

    if not intg.notify_new_order:
        return False
    if current_status != "Created":
        return False
    if order.is_status_notified(TGO_UNACCEPTED_ALERT_STATUS):
        return False
    if not order.created_at:
        return False
    alert_after = timedelta(seconds=current_app.config.get("TGO_UNACCEPTED_ALERT_SECONDS", 120))
    return datetime.utcnow() - order.created_at >= alert_after


def _format_unaccepted_tgo_message(order: dict) -> str:
    order_number = order.get("orderNumber", "N/A")
    total_price = order.get("totalPrice", 0) or 0
    eta = order.get("eta", "-")
    items = tgo.summarize_items(order)
    return (
        "⚠️ <b>ACIL: SIPARIS HALA KABUL EDILMEDI</b>\n"
        f"{'━'*28}\n"
        f"📋 <b>Siparis No:</b> #{order_number}\n"
        "⏱️ <b>Bekleme:</b> 2 dakikayi gecti\n"
        f"🛍️ <b>Urunler:</b> {items}\n"
        f"💰 <b>Tutar:</b> {total_price:.2f} ₺\n"
        f"⏱️ <b>Sure:</b> {eta}\n"
        f"{'━'*28}\n"
        "TrendyolGo panelinden veya uygulamadan hemen kontrol edin."
    )


# ── Telegram hesap bağlama ──────────────────────────────────────────────────

def poll_telegram_binds(app):
    """Merkezi bota gelen /start olaylarını işleyip chat_id bağlar."""
    with app.app_context():
        bot_token = app.config.get("TELEGRAM_BOT_TOKEN", "")
        if not bot_token:
            return

        offset = int(AppState.get("tg_update_offset", "0"))
        updates = telegram.get_updates(bot_token, offset=offset)
        if not updates:
            return

        max_id = offset
        for upd in updates:
            max_id = max(max_id, upd.get("update_id", 0))
            link_token, chat_id = telegram.parse_start_command(upd)
            if not chat_id:
                continue

            if link_token:
                user = User.query.filter_by(telegram_link_token=link_token).first()
                if user:
                    user.telegram_chat_id = chat_id
                    db.session.commit()
                    telegram.send_message(
                        bot_token, chat_id,
                        f"✅ <b>Bağlantı başarılı!</b>\n\nMerhaba {user.name}, "
                        f"siparişlerin artık buraya gelecek. 🚀"
                    )
                    print(f"[TG BIND] user={user.id} ↔ chat={chat_id}")
                else:
                    telegram.send_message(
                        bot_token, chat_id,
                        "⚠️ Geçersiz bağlantı linki. Panelden yeni bir bağlantı linki alın."
                    )

        # offset'i son işlenen +1 yap
        AppState.set("tg_update_offset", str(max_id + 1))


# ── Raporlar (günlük / haftalık / aylık) ─────────────────────────────────────

def _aggregate_products(orders, max_items: int = 15) -> str:
    """Sipariş listesinin raw_json'undan ürün adetlerini toplar.
    'Ice Latte x4, Browni x2' biçiminde döndürür (adete göre azalan)."""
    counts = {}
    for o in orders:
        try:
            data = json.loads(o.raw_json) if o.raw_json else {}
        except (ValueError, TypeError):
            continue
        if o.platform == "migros":
            for it in (data.get("items") or []):
                name = it.get("name", "?")
                counts[name] = counts.get(name, 0) + (it.get("amount", 1) or 1)
        elif o.platform == "getir":
            for it in getir.products(data):
                if not isinstance(it, dict):
                    continue
                name = getir.product_name(it)
                counts[name] = counts.get(name, 0) + getir.product_quantity(it)
        elif o.platform == tmp.PLATFORM:
            for ln in tmp.lines(data):
                if not isinstance(ln, dict):
                    continue
                name = tmp.line_name(ln)
                counts[name] = counts.get(name, 0) + tmp.line_quantity(ln)
        elif o.platform == hb.PLATFORM:
            for ln in hb.lines(data):
                if not isinstance(ln, dict):
                    continue
                name = hb.line_name(ln)
                counts[name] = counts.get(name, 0) + hb.line_quantity(ln)
        elif o.platform == ys.PLATFORM:
            for item in ys.items(data):
                if not isinstance(item, dict):
                    continue
                name = ys.item_name(item)
                counts[name] = counts.get(name, 0) + ys.item_quantity(item)
        else:  # trendyolgo
            for ln in (data.get("lines") or []):
                name = ln.get("name", "?")
                qty = len(ln.get("items", [])) or 1
                counts[name] = counts.get(name, 0) + qty

    if not counts:
        return "-"
    items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    parts = [f"{name} x{qty}" for name, qty in items[:max_items]]
    s = ", ".join(parts)
    if len(items) > max_items:
        s += f" +{len(items) - max_items} çeşit"
    return s


def _period_orders(intg, start_dt, end_dt=None):
    """intg için [start_dt, end_dt) aralığındaki siparişleri döndürür (UTC-naive)."""
    start_utc = start_dt.astimezone(pytz.utc).replace(tzinfo=None)
    q = Order.query.filter(
        Order.user_id == intg.user_id,
        Order.platform == intg.platform,
        Order.created_at >= start_utc,
    )
    if end_dt is not None:
        end_utc = end_dt.astimezone(pytz.utc).replace(tzinfo=None)
        q = q.filter(Order.created_at < end_utc)
    return q.all()


def _normalized_status(status: str) -> str:
    return (status or "").replace("_", "").replace("-", "").replace(" ", "").lower()


def _is_cancelled_order(order: Order) -> bool:
    status = order.status or ""
    normalized = _normalized_status(status)
    return (
        status in CANCELLED_ORDER_STATUSES
        or "cancel" in normalized
        or "iptal" in normalized
        or "reject" in normalized
        or "unsupplied" in normalized
    )


def _is_refunded_order(order: Order) -> bool:
    status = order.status or ""
    normalized = _normalized_status(status)
    return (
        status in REFUNDED_ORDER_STATUSES
        or "refund" in normalized
        or "iade" in normalized
        or "return" in normalized
    )


def _send_period_report(intg, kind: str, period_label: str, orders):
    """Ortak rapor gönderici: kind = 'Günlük' | 'Haftalık' | 'Aylık'."""
    refunded  = [o for o in orders if _is_refunded_order(o)]
    cancelled = [o for o in orders if _is_cancelled_order(o) and o not in refunded]
    active    = [o for o in orders if o not in cancelled and o not in refunded]
    revenue   = sum(o.total_price for o in active)
    cancelled_total = sum(o.total_price for o in cancelled)
    refunded_total = sum(o.total_price for o in refunded)
    products  = _aggregate_products(active)
    label = {
        TGO_FOOD_PLATFORM: "Trendyol Go",
        TGO_MARKET_PLATFORM: "Trendyol Go Market",
        "migros": "Migros Yemek",
        "getir": "Getir Yemek",
        tmp.PLATFORM: "Trendyol Pazaryeri",
        hb.PLATFORM: "Hepsiburada",
        ys.PLATFORM: "Yemeksepeti",
    }.get(intg.platform, intg.platform)

    emoji = {"Günlük": "📊", "Haftalık": "📅", "Aylık": "🗓️"}.get(kind, "📊")
    msg = (
        f"{emoji} <b>{kind} Rapor — {label}</b>\n"
        f"📆 {period_label}\n"
        f"{'━'*28}\n"
        f"✅ <b>Geçerli Sipariş:</b> {len(active)}\n"
        f"❌ <b>İptal Sipariş:</b> {len(cancelled)} ({cancelled_total:.2f} ₺)\n"
        f"↩️ <b>İade Sipariş:</b> {len(refunded)} ({refunded_total:.2f} ₺)\n"
        f"💰 <b>Geçerli Ciro:</b> {revenue:.2f} ₺\n"
        f"{'━'*28}\n"
        f"🛍️ <b>Satılan Ürünler:</b>\n{products}\n"
    )
    user = db.session.get(User, intg.user_id)
    # WhatsApp rapor şablonu: {{1}}=başlık+dönem {{2}}=ürünler {{3}}=özet {{4}}=ciro
    from flask import current_app
    wa_template = current_app.config.get("WHATSAPP_REPORT_TEMPLATE_NAME", "gunluk_rapor")
    wa = [
        f"{kind} · {label} · {period_label} · {len(active)} geçerli, {len(cancelled)} iptal, {len(refunded)} iade",
        products[:400] if products != "-" else "Sipariş yok",
        f"{revenue:.2f} ₺",
    ]
    send_to_user(user, msg, wa=wa, wa_template=wa_template)
    print(f"[RAPOR/{kind}] user={intg.user_id} platform={intg.platform}")


def send_daily_reports(app):
    with app.app_context():
        today = datetime.now(TURKEY_TZ).date()
        for intg in Integration.query.filter_by(is_active=True).all():
            if not intg.notify_daily_report:
                continue
            try:
                start = TURKEY_TZ.localize(datetime.combine(today, datetime.min.time()))
                orders = _period_orders(intg, start)
                _send_period_report(intg, "Günlük", today.strftime('%d.%m.%Y'), orders)
            except Exception as e:
                print(f"[RAPOR] Günlük hata user={intg.user_id}: {e}")


def send_weekly_reports(app):
    """Her Pazartesi 08:00 — önceki 7 gün (Pzt-Paz)."""
    with app.app_context():
        now = datetime.now(TURKEY_TZ)
        end = TURKEY_TZ.localize(datetime.combine(now.date(), datetime.min.time()))
        start = end - timedelta(days=7)
        label = f"{start.strftime('%d.%m')} – {(end - timedelta(days=1)).strftime('%d.%m.%Y')}"
        for intg in Integration.query.filter_by(is_active=True).all():
            if not getattr(intg, "notify_weekly_report", True):
                continue
            try:
                orders = _period_orders(intg, start, end)
                _send_period_report(intg, "Haftalık", label, orders)
            except Exception as e:
                print(f"[RAPOR] Haftalık hata user={intg.user_id}: {e}")


def send_monthly_reports(app):
    """Ayın 1'i 08:00 — önceki takvim ayı."""
    with app.app_context():
        now = datetime.now(TURKEY_TZ)
        first_this = TURKEY_TZ.localize(datetime(now.year, now.month, 1))
        last_month_end = first_this
        prev = last_month_end - timedelta(days=1)
        start = TURKEY_TZ.localize(datetime(prev.year, prev.month, 1))
        label = start.strftime('%B %Y')
        for intg in Integration.query.filter_by(is_active=True).all():
            if not getattr(intg, "notify_monthly_report", True):
                continue
            try:
                orders = _period_orders(intg, start, last_month_end)
                _send_period_report(intg, "Aylık", label, orders)
            except Exception as e:
                print(f"[RAPOR] Aylık hata user={intg.user_id}: {e}")


# ── Scheduler kurulumu ──────────────────────────────────────────────────────

def _process_tgo(intg):
    since = datetime.utcnow() - timedelta(days=1)
    service = _tgo_service_for_platform(intg.platform)
    orders = _get_tgo_orders_for_service(intg, since, service)
    user = db.session.get(User, intg.user_id)
    processed = 0

    for order_data in orders:
        _upsert_tgo_order(intg, user, order_data)
        processed += 1

    _process_tgo_claims(intg, user, service)
    return processed


def _tgo_service_for_platform(platform: str) -> str:
    return tgo.SERVICE_GROCERY if platform == TGO_MARKET_PLATFORM else tgo.SERVICE_MEAL


def _tgo_platform_label(platform: str) -> str:
    return "Trendyol Go Market" if platform == TGO_MARKET_PLATFORM else "Trendyol Go"


def _get_tgo_orders_for_service(intg, since: datetime, service: str) -> list:
    return tgo.get_orders(
        intg.tgo_supplier_id,
        intg.tgo_api_key,
        intg.tgo_api_secret,
        statuses=tgo.ORDER_POLL_STATUSES,
        since=since,
        service=service,
    )


def _upsert_tgo_order(intg, user, order_data: dict):
    external_id = str(order_data.get("id") or "").strip()
    if not external_id:
        return

    current_status = str(order_data.get("packageStatus") or "").strip()
    order_number = str(order_data.get("orderNumber") or "").strip()
    total_price = _tgo_total_price(order_data)
    amount = _format_tgo_amount(total_price)

    existing = Order.query.filter_by(
        user_id=intg.user_id,
        platform=intg.platform,
        external_id=external_id,
    ).first()

    if not existing:
        order = Order(
            user_id=intg.user_id,
            platform=intg.platform,
            external_id=external_id,
            order_number=order_number,
            status=current_status,
            total_price=total_price,
            payment_type=(order_data.get("payment") or {}).get("paymentType", ""),
            app_source=(order_data.get("userInformation") or {}).get("appName", ""),
            customer_note=order_data.get("customerNote", ""),
            raw_json=json.dumps(order_data, ensure_ascii=False),
        )
        order.mark_status_notified("INITIAL")
        db.session.add(order)
        db.session.commit()

        if current_status in tgo.CANCEL_STATUSES:
            _notify_tgo_problem(intg, user, order_data, "Siparis iptal", amount)
        elif current_status in tgo.REFUND_STATUSES:
            _notify_tgo_problem(intg, user, order_data, "Siparis iade", amount)
        elif intg.notify_new_order:
            send_to_user(
                user,
                tgo.format_new_order_message(order_data),
                wa=[f"Yeni siparis - {_tgo_platform_label(intg.platform)}", order_number, tgo.summarize_items(order_data), amount],
            )
        return

    status_changed = existing.status != current_status
    if status_changed:
        existing.status = current_status
        existing.total_price = total_price
        existing.payment_type = (order_data.get("payment") or {}).get("paymentType", "")
        existing.customer_note = order_data.get("customerNote", "")
        existing.raw_json = json.dumps(order_data, ensure_ascii=False)

    if _should_alert_unaccepted_tgo(existing, current_status, intg):
        existing.mark_status_notified(TGO_UNACCEPTED_ALERT_STATUS)
        db.session.commit()
        send_to_user(
            user,
            _format_unaccepted_tgo_message(order_data),
            wa=["Acil: siparis kabul edilmedi", order_number, tgo.summarize_items(order_data), amount],
        )
        return

    if not status_changed or current_status not in tgo.STATUS_NOTIFY or existing.is_status_notified(current_status):
        db.session.commit()
        return

    if current_status in tgo.CANCEL_STATUSES:
        existing.mark_status_notified(current_status)
        db.session.commit()
        _notify_tgo_problem(intg, user, order_data, "Siparis iptal", amount)
        return

    if current_status in tgo.REFUND_STATUSES:
        existing.mark_status_notified(current_status)
        db.session.commit()
        _notify_tgo_problem(intg, user, order_data, "Siparis iade", amount)
        return

    if intg.notify_status_change:
        existing.mark_status_notified(current_status)
        db.session.commit()
        send_to_user(
            user,
            tgo.format_status_message(order_data, current_status),
            wa=[f"{status_label(current_status)} - {_tgo_platform_label(intg.platform)}", order_number, tgo.summarize_items(order_data), amount],
        )
    else:
        db.session.commit()


def _notify_tgo_problem(intg, user, order_data: dict, title: str, amount: str):
    if not intg.notify_cancel:
        return
    order_number = str(order_data.get("orderNumber") or "").strip()
    current_status = str(order_data.get("packageStatus") or "").strip()
    send_to_user(
        user,
        tgo.format_status_message(order_data, current_status),
        wa=[f"{title} - {_tgo_platform_label(intg.platform)}", order_number, tgo.summarize_items(order_data), amount],
    )


def _format_tgo_amount(value) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"{amount:.2f} TL"


def _tgo_total_price(order_data: dict) -> float:
    try:
        return float(order_data.get("totalPrice") or 0)
    except (TypeError, ValueError):
        return 0.0


def _process_tgo_claims(intg, user, service: str):
    try:
        claims = tgo.get_claims(
            intg.tgo_supplier_id,
            intg.tgo_api_key,
            intg.tgo_api_secret,
            since=datetime.utcnow() - timedelta(days=1),
            service=service,
        )
    except requests.exceptions.HTTPError as exc:
        if getattr(exc.response, "status_code", 0) in (400, 403, 404):
            return
        raise
    except requests.exceptions.RequestException:
        return

    for claim in claims:
        claim_id = tgo.claim_external_id(claim)
        if not claim_id:
            continue

        claim_status = tgo.claim_status(claim)
        report_status = "Cancelled" if claim_status in {"Cancelled", "Rejected"} else "Refunded"
        external_id = f"claim:{claim_id}"
        claim_order_number = tgo.claim_order_number(claim)
        existing = Order.query.filter_by(
            user_id=intg.user_id,
            platform=intg.platform,
            external_id=external_id,
        ).first()
        related = _find_tgo_order_by_number(intg.user_id, intg.platform, claim_order_number)
        related_raw = _raw_json_dict(related.raw_json) if related else None
        amount = tgo.claim_total_price(claim, original_order=related_raw, fallback=(related.total_price if related else 0))

        if existing:
            existing.status = report_status
            existing.total_price = existing.total_price or amount
            existing.customer_note = tgo.claim_customer_note(claim)
            existing.raw_json = json.dumps(claim, ensure_ascii=False)
            should_notify = not existing.is_status_notified(report_status)
            existing.mark_status_notified(report_status)
            db.session.commit()
            if should_notify and intg.notify_cancel and report_status == "Refunded":
                _notify_tgo_claim(user, claim, existing.total_price, intg.platform)
            continue

        order = Order(
            user_id=intg.user_id,
            platform=intg.platform,
            external_id=external_id,
            order_number=claim_order_number or claim_id,
            status=report_status,
            total_price=amount,
            payment_type="Iade",
            app_source=(related.app_source if related else ""),
            customer_note=tgo.claim_customer_note(claim),
            raw_json=json.dumps(claim, ensure_ascii=False),
        )
        order.mark_status_notified(report_status)
        db.session.add(order)
        db.session.commit()
        if intg.notify_cancel and report_status == "Refunded":
            _notify_tgo_claim(user, claim, amount, intg.platform)


def _find_tgo_order_by_number(user_id: int, platform: str, order_number: str):
    if not order_number:
        return None
    return (
        Order.query.filter_by(user_id=user_id, platform=platform, order_number=str(order_number))
        .filter(~Order.external_id.like("claim:%"))
        .order_by(Order.created_at.desc())
        .first()
    )


def _raw_json_dict(value: str) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _notify_tgo_claim(user, claim: dict, amount: float, platform: str = TGO_FOOD_PLATFORM):
    send_to_user(
        user,
        tgo.format_claim_message(claim),
        wa=[f"Siparis iade - {_tgo_platform_label(platform)}", tgo.claim_order_number(claim) or tgo.claim_external_id(claim),
            tgo.claim_items_summary(claim), f"{amount:.2f} TL"],
    )


def start_scheduler(app):
    if scheduler.running:
        return

    interval = app.config.get("POLL_INTERVAL_SECONDS", 30)

    scheduler.add_job(poll_trendyolgo, "interval", seconds=interval,
                      args=[app], id="tgo_poll", replace_existing=True, max_instances=1)

    scheduler.add_job(poll_trendyol_marketplace, "interval", seconds=interval,
                      args=[app], id="tmp_poll", replace_existing=True, max_instances=1)

    scheduler.add_job(poll_hepsiburada, "interval", seconds=interval,
                      args=[app], id="hb_poll", replace_existing=True, max_instances=1)

    scheduler.add_job(poll_telegram_binds, "interval", seconds=5,
                      args=[app], id="tg_bind", replace_existing=True, max_instances=1)

    scheduler.add_job(send_daily_reports, "cron", hour=23, minute=45,
                      args=[app], id="daily_report", replace_existing=True)

    # Haftalık — her Pazartesi 08:00 (önceki 7 gün)
    scheduler.add_job(send_weekly_reports, "cron", day_of_week="mon", hour=8, minute=0,
                      args=[app], id="weekly_report", replace_existing=True)

    # Aylık — ayın 1'i 08:00 (önceki ay)
    scheduler.add_job(send_monthly_reports, "cron", day=1, hour=8, minute=0,
                      args=[app], id="monthly_report", replace_existing=True)

    scheduler.start()
    print(f"[SCHEDULER] Başlatıldı ✅ (polling: {interval}s)")


if __name__ == "__main__":
    # Ayrı süreç olarak çalıştırma (prod): RUN_SCHEDULER=0 iken web'den ayrı.
    import time
    from app import create_app
    application = create_app(start_scheduler=False)
    start_scheduler(application)
    print("[WORKER] Bağımsız modda çalışıyor. Durdurmak için CTRL+C.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[WORKER] Durduruldu.")

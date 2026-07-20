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

from extensions import db
from models import Integration, Order, User, AppState
from integrations import trendyolgo as tgo
from notifications import telegram
from notifications.dispatcher import send_to_user
from utils import status_label

TURKEY_TZ = pytz.timezone("Europe/Istanbul")
scheduler = BackgroundScheduler(timezone=TURKEY_TZ)

TGO_UNACCEPTED_ALERT_STATUS = "UNACCEPTED_2MIN"


# ── Sipariş polling ─────────────────────────────────────────────────────────

def poll_trendyolgo(app):
    with app.app_context():
        integrations = Integration.query.filter_by(platform="trendyolgo", is_active=True).all()
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


def _process_tgo(intg):
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


def _send_period_report(intg, kind: str, period_label: str, orders):
    """Ortak rapor gönderici: kind = 'Günlük' | 'Haftalık' | 'Aylık'."""
    cancelled = [o for o in orders if o.status in ("Cancelled", "UnSupplied")]
    active    = [o for o in orders if o.status not in ("Cancelled", "UnSupplied")]
    revenue   = sum(o.total_price for o in active)
    products  = _aggregate_products(active)
    label = {"trendyolgo": "Trendyol Go", "migros": "Migros Yemek"}.get(intg.platform, intg.platform)

    emoji = {"Günlük": "📊", "Haftalık": "📅", "Aylık": "🗓️"}.get(kind, "📊")
    msg = (
        f"{emoji} <b>{kind} Rapor — {label}</b>\n"
        f"📆 {period_label}\n"
        f"{'━'*28}\n"
        f"✅ <b>Geçerli Sipariş:</b> {len(active)}\n"
        f"❌ <b>İptal:</b> {len(cancelled)}\n"
        f"💰 <b>Toplam Ciro:</b> {revenue:.2f} ₺\n"
        f"{'━'*28}\n"
        f"🛍️ <b>Satılan Ürünler:</b>\n{products}\n"
    )
    user = db.session.get(User, intg.user_id)
    # WhatsApp rapor şablonu: {{1}}=başlık+dönem {{2}}=ürünler {{3}}=özet {{4}}=ciro
    from flask import current_app
    wa_template = current_app.config.get("WHATSAPP_REPORT_TEMPLATE_NAME", "gunluk_rapor")
    wa = [
        f"{kind} · {label} · {period_label} · {len(active)} geçerli, {len(cancelled)} iptal",
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

def start_scheduler(app):
    if scheduler.running:
        return

    interval = app.config.get("POLL_INTERVAL_SECONDS", 30)

    scheduler.add_job(poll_trendyolgo, "interval", seconds=interval,
                      args=[app], id="tgo_poll", replace_existing=True, max_instances=1)

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

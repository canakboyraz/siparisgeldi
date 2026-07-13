"""Arka plan iş yöneticisi (APScheduler).

- Her N saniyede aktif TrendyolGo entegrasyonlarını sorgular → yeni sipariş /
  statü değişimi bildirimi gönderir.
- Her N saniyede merkezi bota gelen /start olaylarını işleyip kullanıcı
  hesaplarına Telegram chat_id bağlar.
- Her gece 23:45 günlük özet raporu gönderir.
"""
import json
from datetime import datetime

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler

from extensions import db
from models import Integration, Order, User, AppState
from integrations import trendyolgo as tgo
from notifications import telegram
from notifications.dispatcher import send_to_user

TURKEY_TZ = pytz.timezone("Europe/Istanbul")
scheduler = BackgroundScheduler(timezone=TURKEY_TZ)


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
                send_to_user(user, tgo.format_new_order_message(order_data))
                print(f"[TGO] 🆕 #{order_number} (user={intg.user_id})")
        else:
            # Statü değişimi
            if existing.status != current_status:
                existing.status = current_status
                existing.raw_json = json.dumps(order_data, ensure_ascii=False)

            is_cancel = current_status in ("Cancelled", "UnSupplied")
            wants = intg.notify_cancel if is_cancel else intg.notify_status_change

            if (current_status in tgo.STATUS_NOTIFY
                    and not existing.is_status_notified(current_status) and wants):
                existing.mark_status_notified(current_status)
                db.session.commit()
                send_to_user(user, tgo.format_status_message(order_data, current_status))
                print(f"[TGO] 🔄 #{order_number} → {current_status} (user={intg.user_id})")
            else:
                db.session.commit()


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


# ── Günlük rapor ────────────────────────────────────────────────────────────

def send_daily_reports(app):
    with app.app_context():
        today = datetime.now(TURKEY_TZ).date()
        integrations = Integration.query.filter_by(is_active=True).all()
        for intg in integrations:
            if not intg.notify_daily_report:
                continue
            try:
                _daily_report(intg, today)
            except Exception as e:
                print(f"[RAPOR] Hata user={intg.user_id}: {e}")


def _daily_report(intg, today):
    start = TURKEY_TZ.localize(datetime.combine(today, datetime.min.time()))
    orders = Order.query.filter(
        Order.user_id == intg.user_id,
        Order.platform == intg.platform,
        Order.created_at >= start.astimezone(pytz.utc).replace(tzinfo=None),
    ).all()

    cancelled = [o for o in orders if o.status in ("Cancelled", "UnSupplied")]
    active    = [o for o in orders if o.status not in ("Cancelled", "UnSupplied")]
    revenue   = sum(o.total_price for o in active)
    label = {"trendyolgo": "Trendyol Go", "migros": "Migros Yemek"}.get(intg.platform, intg.platform)

    msg = (
        f"📊 <b>Günlük Rapor — {label}</b>\n"
        f"📅 {today.strftime('%d.%m.%Y')}\n"
        f"{'━'*28}\n"
        f"✅ <b>Geçerli Sipariş:</b> {len(active)}\n"
        f"❌ <b>İptal:</b> {len(cancelled)}\n"
        f"💰 <b>Toplam Ciro:</b> {revenue:.2f} ₺\n"
        f"{'━'*28}\n"
        f"🕙 <i>{datetime.now(TURKEY_TZ).strftime('%H:%M')}</i>"
    )
    user = db.session.get(User, intg.user_id)
    send_to_user(user, msg)
    print(f"[RAPOR] user={intg.user_id} platform={intg.platform}")


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

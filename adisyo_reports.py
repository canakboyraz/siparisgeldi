"""Durable, paginated Adisyo daily report tasks."""
import json
from datetime import datetime, timedelta
from html import escape

from flask import current_app
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import AdisyoConnection, AdisyoReport, Integration, Order
from integrations import adisyo
from notifications.dispatcher import send_to_user


LIVE_REFRESH_MINUTES = 15      # bugünün raporu bu sıklıkla yenilenir
ERROR_RETRY_MINUTES = 60       # hata veren bağlantı daha seyrek denenir


def queue_report(connection, day, send=False, refresh=False):
    report = AdisyoReport.query.filter_by(connection_id=connection.id, day=day).first()
    if report is None:
        report = AdisyoReport(connection_id=connection.id, day=day, send_requested=send,
                              started_at=datetime.utcnow())
        db.session.add(report)
    elif refresh and report.state in ("ready", "error"):
        # Eski özet yeni tur bitene kadar ekranda kalır; yalnızca sayfa verisi sıfırlanır.
        report.state, report.page, report.attempts = "queued", 1, 0
        report.rows_json, report.error = "{}", None
        report.send_requested, report.notification_status = send, None
        report.started_at = datetime.utcnow()
    db.session.commit()
    return report


def day_end_utc(day):
    end = adisyo.TURKEY_TZ.localize(datetime.combine(day + timedelta(days=1), datetime.min.time()))
    return end.astimezone(adisyo.pytz.utc).replace(tzinfo=None)


def is_final(report):
    """Gün kapandıktan sonra başlayan okuma turu tüm siparişleri içerir."""
    return report.started_at is None or report.started_at >= day_end_utc(report.day)


def schedule(connection, now):
    """Bugünü sık sık yeniler; dünü gece bir kez kesinleştirip raporunu gönderir."""
    today, yesterday = now.date(), now.date() - timedelta(days=1)
    notify = bool(connection.integration.notify_daily_report)
    utcnow = datetime.utcnow()
    if (now.hour, now.minute) >= (0, 15):
        report = AdisyoReport.query.filter_by(connection_id=connection.id, day=yesterday).first()
        if report is None:
            if notify:
                queue_report(connection, yesterday, send=True)
        elif report.state != "queued" and not is_final(report):
            queue_report(connection, yesterday, send=notify, refresh=True)
    # Sipariş satırları saklanmadan önce hazırlanmış eski raporları bir kez yeniden oku.
    old = (AdisyoReport.query.filter(AdisyoReport.connection_id == connection.id,
                                     AdisyoReport.started_at.is_(None),
                                     AdisyoReport.state.in_(("ready", "error")))
           .order_by(AdisyoReport.day.desc()).first())
    if old is not None and not AdisyoReport.query.filter_by(connection_id=connection.id, state="queued").first():
        queue_report(connection, old.day, refresh=True)
    report = AdisyoReport.query.filter_by(connection_id=connection.id, day=today).first()
    if report is None:
        queue_report(connection, today)
    elif report.state != "queued":
        wait = ERROR_RETRY_MINUTES if report.state == "error" else LIVE_REFRESH_MINUTES
        if not report.started_at or report.started_at <= utcnow - timedelta(minutes=wait):
            queue_report(connection, today, refresh=True)


def report_message(report):
    summary = json.loads(report.summary_json)
    label = f"Adisyo - {report.connection.restaurant_name} - {report.day:%d.%m.%Y}"
    lines = [f"<b>{escape(label)}</b>", "Siparis olusturma tarihine gore",
             f"Siparis: {summary['count']} | Iptal: {summary['cancelled']}",
             f"Brut toplam: {summary['gross_amount']} TL", f"Gecerli ciro: {summary['amount']} TL",
             f"Iptal tutari: {summary['cancelled_amount']} TL",
             f"Indirim: {summary['discount']} TL | Vergi: {summary['tax']} TL", "", "<b>Urunler</b>"]
    for item in summary["products"][:25]:
        lines.append(f"{escape(item['name'][:80])}: {item['quantity']} adet / {item['amount']} TL")
    if len(summary["products"]) > 25:
        lines.append("Tum urunler rapor ekraninda.")
    lines.extend(["", "<b>Odemeler</b>"])
    lines.extend(f"{escape(p['name'][:60])}: {p['amount']} TL" for p in summary["payments"][:10])
    lines.append("https://www.siparisgeldi.net/panel/adisyo")
    # Existing report template has three parameters. The panel retains full detail.
    brief = "; ".join(f"{p['name'][:50]} x{p['quantity']}" for p in summary["products"])
    if len(brief) > 650:
        brief = brief[:600] + "; tum urunler siparisgeldi.net/panel/adisyo"
    return "\n".join(lines), [f"{label} | {summary['count']} siparis, {summary['cancelled']} iptal",
                               brief or "Urun yok", f"{summary['amount']} TL"]


def tick(app):
    with app.app_context():
        now = datetime.now(adisyo.TURKEY_TZ)
        connections = AdisyoConnection.query.join(Integration).filter(Integration.is_active.is_(True)).all()
        for connection in connections:
            try:
                schedule(connection, now)
                process_page(connection.id)
            except IntegrityError:
                db.session.rollback()
            except Exception:
                db.session.rollback()
                # Never log remote response bodies, request headers or credentials.
                current_app.logger.exception("Adisyo rapor gorevi basarisiz connection_id=%s", connection.id)


def save_orders(connection, rows):
    """Adisyo satışlarını diğer platformlar gibi tek tek sipariş olarak saklar.

    Böylece Tüm siparişler, raporlar, istatistikler ve kârlılık aynı kaynaktan
    beslenir. Müşteri bilgisi tutulmaz; yalnızca ürün, ödeme ve tutarlar.
    """
    user_id = connection.integration.user_id
    ids = [row["id"] for row in rows]
    existing = {o.external_id: o for o in Order.query.filter(
        Order.user_id == user_id, Order.platform == "adisyo", Order.external_id.in_(ids)).all()} if ids else {}
    for row in rows:
        order = existing.get(row["id"])
        if order is None:
            order = Order(user_id=user_id, platform="adisyo", external_id=row["id"])
            db.session.add(order)
        order.order_number = row["id"][:50]
        order.status = "Cancelled" if row["cancelled"] else "Completed"
        order.total_price = float(row["amount"])
        order.payment_type = ", ".join(sorted({p["name"] for p in row["payments"]}))[:50] or None
        order.app_source = "Adisyo"
        order.raw_json = json.dumps({"source": "adisyo", "products": row["products"], "payments": row["payments"],
                                     "discount": row["discount"], "tax": row["tax"]}, ensure_ascii=False)
        if row.get("created"):
            order.created_at = datetime.fromisoformat(row["created"])


def process_page(connection_id):
    connection = AdisyoConnection.query.filter_by(id=connection_id).with_for_update(skip_locked=True).first()
    now = datetime.utcnow()
    if not connection or (connection.next_request_at and connection.next_request_at > now):
        db.session.rollback()
        return
    report = AdisyoReport.query.filter_by(connection_id=connection_id, state="queued").order_by(AdisyoReport.day).first()
    if not report:
        db.session.rollback()
        return
    try:
        rows, page_count = adisyo.completed_page(connection, report.day, report.page)
        stored = json.loads(report.rows_json)
        page_rows = []
        for row in rows:
            normalized = adisyo.normalize(row, report.day)
            if normalized:
                stored[normalized["id"]] = normalized
                page_rows.append(normalized)
        save_orders(connection, page_rows)
        report.rows_json = json.dumps(stored, ensure_ascii=False)
        report.attempts, report.error = 0, None
        connection.integration.last_sync_at, connection.integration.last_error = now, None
        if report.page >= page_count:
            report.summary_json = json.dumps(adisyo.summarize(stored.values()), ensure_ascii=False)
            report.rows_json, report.state = "{}", "ready"
        else:
            report.page += 1
        connection.next_request_at = datetime.utcnow() + timedelta(seconds=45)
    except adisyo.AdisyoError as exc:
        report.attempts += 1
        report.error = connection.integration.last_error = str(exc)
        if report.attempts >= 5:
            report.state = "error"
        connection.next_request_at = datetime.utcnow() + timedelta(seconds=min(900, 60 * 2 ** report.attempts))
    db.session.commit()
    if report.state == "ready" and report.send_requested:
        # Claim before external sends: dispatcher may commit its own transaction.
        claimed = AdisyoReport.query.filter_by(id=report.id, notification_status=None).update(
            {"notification_status": "attempting"}, synchronize_session=False)
        db.session.commit()
        if claimed:
            message, params = report_message(report)
            sent = send_to_user(connection.integration.user, message, wa=params,
                                wa_template=current_app.config.get("WHATSAPP_REPORT_TEMPLATE_NAME", "gunluk_raporr"),
                                source="adisyo")
            report.notification_status = "accepted" if sent else "failed"
            db.session.commit()

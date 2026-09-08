"""Durable, paginated Adisyo daily report tasks."""
import json
from datetime import datetime, timedelta
from html import escape

from flask import current_app
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import AdisyoConnection, AdisyoReport, Integration
from integrations import adisyo
from notifications.dispatcher import send_to_user


def queue_report(connection, day, send=False, refresh=False):
    report = AdisyoReport.query.filter_by(connection_id=connection.id, day=day).first()
    if report is None:
        report = AdisyoReport(connection_id=connection.id, day=day, send_requested=send)
        db.session.add(report)
    elif refresh and report.state in ("ready", "error"):
        report.state, report.page, report.attempts = "queued", 1, 0
        report.rows_json, report.summary_json, report.error = "{}", None, None
        report.send_requested, report.notification_status = send, None
    db.session.commit()
    return report


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
                if (now.hour, now.minute) >= (0, 15) and connection.integration.notify_daily_report:
                    queue_report(connection, now.date() - timedelta(days=1), send=True)
                process_page(connection.id)
            except IntegrityError:
                db.session.rollback()
            except Exception:
                db.session.rollback()
                # Never log remote response bodies, request headers or credentials.
                current_app.logger.exception("Adisyo rapor gorevi basarisiz connection_id=%s", connection.id)


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
        for row in rows:
            normalized = adisyo.normalize(row, report.day)
            if normalized:
                stored[normalized["id"]] = normalized
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

import json
from datetime import datetime, timedelta, date

from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user

from extensions import db
from models import Integration, AdisyoConnection, AdisyoReport
from integrations.adisyo import TURKEY_TZ
from adisyo_reports import queue_report

adisyo_bp = Blueprint("adisyo", __name__)


@adisyo_bp.route("", methods=["GET", "POST"])
@login_required
def setup():
    integration = Integration.query.filter_by(user_id=current_user.id, platform="adisyo").first()
    connection = integration.adisyo_connection if integration else None
    today = datetime.now(TURKEY_TZ).date()
    if request.method == "POST":
        from routes.dashboard import _can_enable_platform
        name = request.form.get("restaurant_name", "").strip()
        consumer = request.form.get("consumer", "").strip()
        key = request.form.get("api_key", "").strip()
        secret = request.form.get("api_secret", "").strip()
        if not _can_enable_platform(integration):
            flash("Coklu platform icin Pro erisimi gerekiyor.", "warning")
        elif not name or not consumer or len(name) > 120 or len(consumer) > 120 or not consumer.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in consumer):
            flash("Restoran adi ve gecerli Consumer zorunludur (en fazla 120 karakter).", "danger")
        elif (not connection and (not key or not secret)) or max(len(key), len(secret)) > 2048 or any(c in key + secret for c in "\r\n"):
            flash("Gecerli Web App Key ve API Secret Key girin.", "danger")
        elif not current_app.config.get("ENCRYPTION_KEY"):
            flash("ENCRYPTION_KEY eksik; yonetici yapilandirmasi gerekli.", "danger")
        elif connection and AdisyoReport.query.filter_by(connection_id=connection.id, state="queued").first():
            flash("Rapor hazirlaniyor. Baglantiyi degistirmeden once bitmesini bekleyin.", "warning")
        else:
            if not integration:
                integration = Integration(user_id=current_user.id, platform="adisyo", notify_new_order=False,
                                          notify_status_change=False, notify_cancel=False,
                                          notify_weekly_report=False, notify_monthly_report=False)
                db.session.add(integration)
                connection = AdisyoConnection(integration=integration)
                db.session.add(connection)
            connection.restaurant_name, connection.consumer = name, consumer
            if key:
                connection.api_key = key
            if secret:
                connection.api_secret = secret
            integration.notify_daily_report = "daily_report" in request.form
            integration.is_active = True
            db.session.commit()
            flash("Baglanti kaydedildi. Rapor hazirlayarak API erisimini kontrol edebilirsiniz.", "success")
        return redirect(url_for("adisyo.setup"))
    reports = AdisyoReport.query.filter_by(connection_id=connection.id).order_by(AdisyoReport.day.desc()).limit(31).all() if connection else []
    selected = next((r for r in reports if str(r.id) == request.args.get("report")), None)
    selected = selected or next((r for r in reports if r.state == "ready"), None)
    summary = json.loads(selected.summary_json) if selected and selected.summary_json else None
    return render_template("dashboard/adisyo.html", connection=connection, integration=integration,
                           reports=reports, selected=selected, summary=summary, today=today,
                           yesterday=today - timedelta(days=1))


@adisyo_bp.post("/rapor")
@login_required
def report():
    integration = Integration.query.filter_by(user_id=current_user.id, platform="adisyo", is_active=True).first_or_404()
    connection = integration.adisyo_connection
    if not connection:
        return redirect(url_for("adisyo.setup"))
    try:
        day = date.fromisoformat(request.form.get("day", ""))
        today = datetime.now(TURKEY_TZ).date()
        if not today - timedelta(days=31) <= day <= today:
            raise ValueError
    except ValueError:
        flash("Son 31 gun icinden bir tarih secin.", "danger")
        return redirect(url_for("adisyo.setup"))
    queue_report(connection, day, send="send" in request.form, refresh=True)
    flash("Rapor siraya alindi. Arka plan gorevi tamamladiginda bu ekranda gorunecek.", "success")
    return redirect(url_for("adisyo.setup"))

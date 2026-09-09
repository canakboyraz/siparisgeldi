from datetime import datetime, timedelta
from flask import Blueprint, current_app, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from extensions import db
from models import Payment
from integrations import paytr

paytr_bp = Blueprint("paytr", __name__)
PRICE = 250.0


def configured():
    return all(current_app.config.get(k) for k in ("PAYTR_MERCHANT_ID", "PAYTR_MERCHANT_KEY", "PAYTR_MERCHANT_SALT"))


@paytr_bp.post("/start")
@login_required
def start():
    if not configured():
        flash("PayTR bilgileri henuz yapilandirilmadi.", "warning")
        return redirect(url_for("dashboard.subscription"))
    oid = paytr.merchant_oid()
    payment = Payment(user_id=current_user.id, merchant_oid=oid, amount=PRICE)
    db.session.add(payment)
    db.session.commit()
    try:
        token = paytr.iframe_token(current_app.config, oid, current_user, PRICE,
            url_for("paytr.success", _external=True), url_for("paytr.fail", _external=True), request.remote_addr or "0.0.0.0")
    except Exception as exc:
        payment.status, payment.failure_reason = "failed", str(exc)[:300]
        db.session.commit()
        current_app.logger.warning("PayTR token olusturulamadi user_id=%s reason=%s", current_user.id, str(exc)[:300])
        flash("PayTR ödeme başlatılamadı. Railway değişkenlerini ve PayTR test modunu kontrol edin.", "danger")
        return redirect(url_for("dashboard.subscription"))
    return render_template("dashboard/paytr_checkout.html", token=token)


@paytr_bp.post("/callback")
def callback():
    oid = request.form.get("merchant_oid", "")
    current_app.logger.info("PayTR callback alindi method=%s oid_var=%s", request.method, bool(oid))
    payment = Payment.query.filter_by(merchant_oid=oid).first()
    valid = bool(payment and paytr.verify_callback(
        current_app.config, oid, request.form.get("status", ""),
        request.form.get("total_amount", ""), request.form.get("hash", "")
    ))
    if not payment or not valid:
        current_app.logger.warning(
            "PayTR callback reddedildi payment=%s hash_valid=%s status=%s",
            bool(payment), valid, request.form.get("status", "")[:30]
        )
        return "PAYTR notification failed", 400
    if payment.status == "success":
        return "OK"
    status = request.form.get("status", "")
    try:
        total = float(request.form.get("total_amount", "0"))
    except ValueError:
        total = -1
    if status == "success" and abs(total - payment.amount) < 0.01:
        payment.status = "success"
        user = db.session.get(__import__("models").User, payment.user_id)
        user.plan = "pro"
        user.feature_whatsapp = True
        user.feature_multi_platform = True
        payment.reference = request.form.get("payment_id", "")[:120]
    else:
        payment.status, payment.failure_reason = "failed", request.form.get("failed_reason_msg", "")[:300]
    db.session.commit()
    current_app.logger.info("PayTR callback islendi payment_id=%s status=%s", payment.id, payment.status)
    return "OK"


@paytr_bp.get("/success")
@login_required
def success():
    flash("Odeme sonucu isleniyor. Pro erisim callback onayindan sonra acilir.", "info")
    return redirect(url_for("dashboard.subscription"))


@paytr_bp.get("/fail")
@login_required
def fail():
    flash("Odeme tamamlanamadi. Lutfen tekrar deneyin.", "danger")
    return redirect(url_for("dashboard.subscription"))

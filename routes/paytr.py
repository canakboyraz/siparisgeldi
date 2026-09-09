from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from flask import Blueprint, current_app, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from extensions import db
from models import Payment
from integrations import paytr

paytr_bp = Blueprint("paytr", __name__)
PRICE = 250.0


def _amount_in_kurus(value):
    """Veritabanindaki TL tutari kuruşa cevirir."""
    raw = str(value or "").strip().replace(" ", "").replace(",", ".")
    try:
        return int((Decimal(raw) * 100).quantize(Decimal("1")))
    except (InvalidOperation, ValueError):
        return None


def _paytr_total_in_kurus(value):
    """PayTR callback'indeki total_amount kuruş formatindadir (25000 = 250 TL)."""
    raw = str(value or "").strip().replace(" ", "")
    try:
        return int(Decimal(raw))
    except (InvalidOperation, ValueError):
        return None


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
    total_raw = request.form.get("total_amount", "")
    status_normalized = status.strip().lower()
    total_kurus = _paytr_total_in_kurus(total_raw)
    expected_kurus = _amount_in_kurus(payment.amount)
    current_app.logger.info(
        "PayTR callback verisi payment_id=%s status=%s total_var=%s tutar_eslesti=%s",
        payment.id, status_normalized[:30], bool(total_raw),
        total_kurus is not None and total_kurus == expected_kurus,
    )
    if status_normalized == "success" and total_kurus is not None and total_kurus == expected_kurus:
        payment.status = "success"
        user = db.session.get(__import__("models").User, payment.user_id)
        now = datetime.utcnow()
        period_start = user.pro_expires_at if user.pro_expires_at and user.pro_expires_at > now else now
        user.pro_started_at = user.pro_started_at or period_start
        user.pro_expires_at = period_start + timedelta(days=30)
        user.plan = "pro"
        user.feature_whatsapp = True
        user.feature_multi_platform = True
        payment.reference = request.form.get("payment_id", "")[:120]
    else:
        payment.status = "failed"
        payment.failure_reason = (
            request.form.get("failed_reason_msg", "")
            or f"status={status_normalized or 'bos'}, total_amount={str(total_raw)[:40]}"
        )[:300]
    db.session.commit()
    current_app.logger.info("PayTR callback islendi payment_id=%s status=%s", payment.id, payment.status)
    return "OK"


@paytr_bp.get("/success")
@login_required
def success():
    flash("Odeme sonucu isleniyor. Pro erisim callback onayindan sonra acilir.", "info")
    return redirect(url_for("dashboard.subscription", payment_returned=1))


@paytr_bp.get("/fail")
@login_required
def fail():
    flash("Odeme tamamlanamadi. Lutfen tekrar deneyin.", "danger")
    return redirect(url_for("dashboard.subscription"))

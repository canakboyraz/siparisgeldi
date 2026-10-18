"""Herkese açık sayfalar (landing)."""
from flask import Blueprint, current_app, jsonify, render_template, redirect, url_for
from sqlalchemy import text
from flask_login import current_user

public_bp = Blueprint("public", __name__)


@public_bp.route("/")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    return render_template("public/landing.html")


@public_bp.route("/kar-hesaplayici")
def profit_calculator():
    return render_template("public/profit_calculator.html")


@public_bp.route("/iletisim")
def contact():
    return render_template("public/contact.html")


@public_bp.route("/mesafeli-satis-sozlesmesi")
def distance_sales_agreement():
    return render_template("public/legal_distance_sales.html")


@public_bp.route("/on-bilgilendirme-formu")
def preliminary_information():
    return render_template("public/legal_preliminary_information.html")


@public_bp.route("/iptal-iade-politikasi")
def cancellation_refund_policy():
    return render_template("public/legal_refund.html")


@public_bp.route("/gizlilik-politikasi")
def privacy_policy():
    return render_template("public/legal_privacy.html")


@public_bp.route("/kvkk-aydinlatma-metni")
def kvkk_notice():
    return render_template("public/legal_kvkk.html")


@public_bp.route("/healthz")
def healthz():
    """Uptime izleme (UptimeRobot vb.) için. DB erişimi ve worker heartbeat'i.

    200 → her şey yolunda · 503 → DB'ye ulaşılamıyor veya worker 3 dk'dır sessiz.
    """
    from extensions import db
    import monitoring
    status = {"db": "ok", "worker": "ok"}
    code = 200
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        status["db"] = "down"
        return jsonify(status), 503
    age = monitoring.heartbeat_age_seconds()
    status["worker_heartbeat_age_s"] = None if age is None else int(age)
    if age is None or age > 180:
        status["worker"] = "stale"
        code = 503
    return jsonify(status), code

"""Herkese açık sayfalar (landing)."""
from flask import Blueprint, render_template, redirect, url_for
from flask_login import current_user

public_bp = Blueprint("public", __name__)


@public_bp.route("/")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    return render_template("public/landing.html")


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

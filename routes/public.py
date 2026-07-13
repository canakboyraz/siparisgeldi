"""Herkese açık sayfalar (landing)."""
from flask import Blueprint, render_template, redirect, url_for
from flask_login import current_user

public_bp = Blueprint("public", __name__)


@public_bp.route("/")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    return render_template("public/landing.html")

"""Kimlik doğrulama: kayıt, giriş, çıkış."""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db
from models import User

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/giris", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user, remember=True)
            return redirect(url_for("dashboard.index"))
        flash("E-posta veya şifre hatalı.", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/kayit", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm_password", "")

        if not name or not email or not password:
            flash("Tüm alanları doldurun.", "danger")
        elif password != confirm:
            flash("Şifreler eşleşmiyor.", "danger")
        elif len(password) < 6:
            flash("Şifre en az 6 karakter olmalı.", "danger")
        elif User.query.filter_by(email=email).first():
            flash("Bu e-posta zaten kayıtlı.", "danger")
        else:
            user = User(name=name, email=email)
            user.set_password(password)
            user.ensure_link_token()
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Hesabınız oluşturuldu! Şimdi Telegram'ı bağlayın.", "success")
            return redirect(url_for("dashboard.connect_telegram"))

    return render_template("auth/register.html")


@auth_bp.route("/cikis")
@login_required
def logout():
    logout_user()
    return redirect(url_for("public.landing"))

"""Kimlik doğrulama: kayıt, giriş, çıkış."""
import time

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db
from models import User

auth_bp = Blueprint("auth", __name__)
_login_failures = {}
_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_MAX_FAILURES = 8


def _login_key(email: str) -> str:
    return f"{request.remote_addr or 'unknown'}:{email}"


def _too_many_login_attempts(email: str) -> bool:
    now = time.time()
    key = _login_key(email)
    attempts = [ts for ts in _login_failures.get(key, []) if now - ts < _LOGIN_WINDOW_SECONDS]
    _login_failures[key] = attempts
    return len(attempts) >= _LOGIN_MAX_FAILURES


def _record_login_failure(email: str):
    now = time.time()
    key = _login_key(email)
    _login_failures[key] = [
        ts for ts in _login_failures.get(key, []) if now - ts < _LOGIN_WINDOW_SECONDS
    ] + [now]


def _clear_login_failures(email: str):
    _login_failures.pop(_login_key(email), None)


@auth_bp.route("/giris", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if _too_many_login_attempts(email):
            flash("Çok fazla hatalı deneme yapıldı. Lütfen birkaç dakika sonra tekrar deneyin.", "danger")
            return render_template("auth/login.html"), 429
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            _clear_login_failures(email)
            login_user(user, remember=True)
            return redirect(url_for("dashboard.index"))
        _record_login_failure(email)
        flash("E-posta veya şifre hatalı.", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/kayit", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

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


@auth_bp.route("/cikis", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("public.landing"))

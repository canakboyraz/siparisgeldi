"""Kimlik doğrulama: kayıt, giriş, çıkış, şifre sıfırlama, e-posta doğrulama."""
import logging
import time
from datetime import datetime, timedelta

from flask import Blueprint, current_app, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from extensions import db
from models import User

auth_bp = Blueprint("auth", __name__)
log = logging.getLogger(__name__)

_login_failures = {}
_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_MAX_FAILURES = 8

_reset_requests = {}
_RESET_WINDOW_SECONDS = 60 * 60
_RESET_MAX_REQUESTS = 5

MIN_PASSWORD_LENGTH = 8
RESET_TOKEN_MAX_AGE = 60 * 60            # 1 saat
VERIFY_TOKEN_MAX_AGE = 7 * 24 * 60 * 60  # 7 gün


# ── Yardımcılar ─────────────────────────────────────────────────────────────

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


def _reset_rate_limited(email: str) -> bool:
    now = time.time()
    key = _login_key(email)
    recent = [ts for ts in _reset_requests.get(key, []) if now - ts < _RESET_WINDOW_SECONDS]
    limited = len(recent) >= _RESET_MAX_REQUESTS
    if not limited:
        recent.append(now)
    _reset_requests[key] = recent
    return limited


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=salt)


def make_reset_token(user: User) -> str:
    # Şifre hash'inin bir parçası token'a gömülür: şifre değişince eski
    # bağlantılar otomatik geçersiz olur (tek kullanımlık davranış).
    return _serializer("password-reset").dumps({"uid": user.id, "ph": user.password_hash[-16:]})


def load_reset_token(token: str):
    try:
        data = _serializer("password-reset").loads(token, max_age=RESET_TOKEN_MAX_AGE)
    except (SignatureExpired, BadSignature):
        return None
    user = db.session.get(User, int(data.get("uid", 0)))
    if not user or user.password_hash[-16:] != data.get("ph"):
        return None
    return user


def make_verify_token(user: User) -> str:
    return _serializer("email-verify").dumps({"uid": user.id, "email": user.email})


def load_verify_token(token: str):
    try:
        data = _serializer("email-verify").loads(token, max_age=VERIFY_TOKEN_MAX_AGE)
    except (SignatureExpired, BadSignature):
        return None
    user = db.session.get(User, int(data.get("uid", 0)))
    if not user or user.email != data.get("email"):
        return None
    return user


def send_verification_email(user: User) -> bool:
    from notifications import email as mailer
    url = url_for("auth.verify_email", token=make_verify_token(user), _external=True)
    return mailer.send_verification(user.email, user.name, url)


def _send_reset_link(user: User) -> bool:
    """Sıfırlama bağlantısını e-postaya; Telegram bağlıysa oraya da gönderir."""
    from notifications import email as mailer
    url = url_for("auth.reset_password", token=make_reset_token(user), _external=True)
    sent = mailer.send_password_reset(user.email, user.name, url)
    if user.telegram_chat_id:
        try:
            from notifications import telegram
            tg_sent = telegram.send_message(
                current_app.config.get("TELEGRAM_BOT_TOKEN", ""), user.telegram_chat_id,
                "🔐 <b>Şifre sıfırlama</b>\n\nYeni şifre belirlemek için bağlantı (1 saat geçerli):\n"
                f"{url}\n\nBu isteği sen yapmadıysan dikkate alma.",
            )
            sent = sent or tg_sent
        except Exception as e:  # noqa: BLE001
            log.error("[AUTH] Telegram sıfırlama linki gönderilemedi user=%s: %s", user.id, e)
    return sent


def _password_problem(password: str, confirm: str):
    if password != confirm:
        return "Şifreler eşleşmiyor."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Şifre en az {MIN_PASSWORD_LENGTH} karakter olmalı."
    return None


# ── Giriş / kayıt / çıkış ───────────────────────────────────────────────────

@auth_bp.route("/giris", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated and getattr(current_user, "is_demo", False):
        logout_user()
    elif current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if _too_many_login_attempts(email):
            flash("Çok fazla hatalı deneme yapıldı. Lütfen birkaç dakika sonra tekrar deneyin.", "danger")
            return render_template("auth/login.html"), 429
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            if user.is_active is False:
                flash("Hesabınız pasif durumda. Destek ile iletişime geçin.", "danger")
                return render_template("auth/login.html"), 403
            _clear_login_failures(email)
            login_user(user, remember=True)
            return redirect(url_for("dashboard.index"))
        _record_login_failure(email)
        flash("E-posta veya şifre hatalı.", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/kayit", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated and getattr(current_user, "is_demo", False):
        logout_user()  # demodan gerçek hesaba geçiş
    elif current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        accepted = request.form.get("accept_terms") == "1"

        problem = _password_problem(password, confirm)
        if not name or not email or not password:
            flash("Tüm alanları doldurun.", "danger")
        elif problem:
            flash(problem, "danger")
        elif not accepted:
            flash("Devam etmek için gizlilik politikası ve KVKK aydınlatma metnini onaylayın.", "danger")
        elif User.query.filter_by(email=email).first():
            flash("Bu e-posta zaten kayıtlı.", "danger")
        else:
            user = User(name=name, email=email)
            user.set_password(password)
            user.ensure_link_token()
            trial_days = int(current_app.config.get("TRIAL_DAYS", 0) or 0)
            if trial_days > 0:
                now = datetime.utcnow()
                user.plan = "pro"
                user.is_trial = True
                user.pro_started_at = now
                user.pro_expires_at = now + timedelta(days=trial_days)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            send_verification_email(user)
            if trial_days > 0:
                flash(f"Hesabın oluşturuldu! {trial_days} gün boyunca tüm Pro özellikler açık. "
                      "Şimdi Telegram'ı bağla.", "success")
            else:
                flash("Hesabınız oluşturuldu! Şimdi Telegram'ı bağlayın.", "success")
            return redirect(url_for("dashboard.connect_telegram"))

    return render_template("auth/register.html", min_password_length=MIN_PASSWORD_LENGTH)


@auth_bp.route("/cikis", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("public.landing"))


# ── Şifre sıfırlama ─────────────────────────────────────────────────────────

@auth_bp.route("/sifremi-unuttum", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if email and not _reset_rate_limited(email):
            user = User.query.filter_by(email=email).first()
            if user:
                _send_reset_link(user)
        # Hesabın varlığını sızdırmamak için her durumda aynı mesaj.
        flash("Bu e-posta ile kayıtlı bir hesap varsa şifre sıfırlama bağlantısı gönderildi. "
              "Gelen kutunu (ve spam klasörünü) kontrol et.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot_password.html")


@auth_bp.route("/sifre-sifirla/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = load_reset_token(token)
    if not user:
        flash("Şifre sıfırlama bağlantısı geçersiz veya süresi dolmuş. Yeniden iste.", "danger")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        problem = _password_problem(password, request.form.get("confirm_password", ""))
        if problem:
            flash(problem, "danger")
        else:
            user.set_password(password)
            # Bağlantı e-postaya geldiyse adres de doğrulanmış sayılır.
            if not user.email_verified_at:
                user.email_verified_at = datetime.utcnow()
            db.session.commit()
            _clear_login_failures(user.email)
            flash("Şifren güncellendi. Yeni şifrenle giriş yapabilirsin.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", min_password_length=MIN_PASSWORD_LENGTH)


# ── E-posta doğrulama ───────────────────────────────────────────────────────

@auth_bp.route("/eposta-dogrula/<token>")
def verify_email(token):
    user = load_verify_token(token)
    if not user:
        flash("Doğrulama bağlantısı geçersiz veya süresi dolmuş. Panelden yeniden gönderebilirsin.", "danger")
    else:
        if not user.email_verified_at:
            user.email_verified_at = datetime.utcnow()
            db.session.commit()
        flash("E-posta adresin doğrulandı. Teşekkürler!", "success")
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    return redirect(url_for("auth.login"))


@auth_bp.route("/eposta-dogrula/tekrar", methods=["POST"])
@login_required
def resend_verification():
    if current_user.email_verified_at:
        flash("E-posta adresin zaten doğrulanmış.", "info")
    elif _reset_rate_limited(f"verify:{current_user.email}"):
        flash("Çok fazla istek. Biraz sonra tekrar dene.", "warning")
    elif send_verification_email(current_user):
        flash(f"Doğrulama bağlantısı {current_user.email} adresine gönderildi.", "success")
    else:
        flash("E-posta şu an gönderilemedi. Lütfen daha sonra tekrar dene.", "danger")
    return redirect(request.referrer or url_for("dashboard.index"))


# ── Demo hesabı ─────────────────────────────────────────────────────────────

_demo_requests = {}
_DEMO_WINDOW_SECONDS = 60 * 60
_DEMO_MAX_PER_IP = 10


@auth_bp.route("/demo", methods=["POST"])
def start_demo():
    """Ziyaretçiye özel, örnek verilerle dolu geçici bir hesap açar ve giriş yapar."""
    import demo
    if current_user.is_authenticated and not getattr(current_user, "is_demo", False):
        return redirect(url_for("dashboard.index"))
    now = time.time()
    ip = request.remote_addr or "unknown"
    recent = [ts for ts in _demo_requests.get(ip, []) if now - ts < _DEMO_WINDOW_SECONDS]
    if len(recent) >= _DEMO_MAX_PER_IP:
        flash("Çok fazla demo isteği geldi. Biraz sonra tekrar dene.", "warning")
        return redirect(url_for("public.landing"))
    _demo_requests[ip] = recent + [now]
    if current_user.is_authenticated:
        logout_user()
    user = demo.create_demo_user()
    login_user(user)
    return redirect(url_for("dashboard.index"))

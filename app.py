"""Uygulama fabrikasÄ± (application factory)."""
import secrets

from flask import Flask, abort, request, session
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import text

from config import Config
from extensions import db, login_manager


def _ensure_schema():
    """Mevcut veritabanlarina sonradan eklenen kolonlari guvenle ekler."""
    backend = db.engine.url.get_backend_name()

    if backend.startswith("postgres"):
        stmts = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_number VARCHAR(30)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS notification_channel VARCHAR(20) DEFAULT 'telegram'",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS feature_whatsapp BOOLEAN DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS feature_multi_platform BOOLEAN DEFAULT FALSE",
            "ALTER TABLE integrations ADD COLUMN IF NOT EXISTS migros_group_id VARCHAR(50)",
            "ALTER TABLE integrations ADD COLUMN IF NOT EXISTS notify_weekly_report BOOLEAN DEFAULT TRUE",
            "ALTER TABLE integrations ADD COLUMN IF NOT EXISTS notify_monthly_report BOOLEAN DEFAULT TRUE",
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_migros_store_id
            ON integrations (migros_store_id)
            WHERE platform = 'migros' AND migros_store_id IS NOT NULL
            """,
        ]
    elif backend.startswith("sqlite"):
        with db.engine.begin() as conn:
            user_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
            intg_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(integrations)")).fetchall()}
            stmts = []
            if "whatsapp_number" not in user_cols:
                stmts.append("ALTER TABLE users ADD COLUMN whatsapp_number VARCHAR(30)")
            if "notification_channel" not in user_cols:
                stmts.append("ALTER TABLE users ADD COLUMN notification_channel VARCHAR(20) DEFAULT 'telegram'")
            if "feature_whatsapp" not in user_cols:
                stmts.append("ALTER TABLE users ADD COLUMN feature_whatsapp BOOLEAN DEFAULT FALSE")
            if "feature_multi_platform" not in user_cols:
                stmts.append("ALTER TABLE users ADD COLUMN feature_multi_platform BOOLEAN DEFAULT FALSE")
            if "migros_group_id" not in intg_cols:
                stmts.append("ALTER TABLE integrations ADD COLUMN migros_group_id VARCHAR(50)")
            if "notify_weekly_report" not in intg_cols:
                stmts.append("ALTER TABLE integrations ADD COLUMN notify_weekly_report BOOLEAN DEFAULT TRUE")
            if "notify_monthly_report" not in intg_cols:
                stmts.append("ALTER TABLE integrations ADD COLUMN notify_monthly_report BOOLEAN DEFAULT TRUE")
            for s in stmts:
                try:
                    conn.execute(text(s))
                except Exception as e:
                    print(f"[SCHEMA] atlandi: {s} -> {e}")
        return
    else:
        return

    with db.engine.begin() as conn:
        for s in stmts:
            try:
                conn.execute(text(s))
            except Exception as e:
                print(f"[SCHEMA] atlandi: {s} -> {e}")

def create_app(config_class=Config, start_scheduler=None):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Reverse proxy (Railway/Render/Nginx) arkasÄ±nda gerÃ§ek ÅŸema/host'u oku ki
    # url_for(_external=True) â†’ https://siparisgeldi.net/... doÄŸru Ã¼retilsin.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Eklentileri baÄŸla
    db.init_app(app)
    login_manager.init_app(app)

    # Modeller (tablo kaydÄ± iÃ§in import ÅŸart)
    import models  # noqa: F401

    # Blueprint'ler
    from routes.public import public_bp
    from routes.auth import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.webhooks import webhooks_bp
    from routes.admin import admin_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp, url_prefix="/panel")
    app.register_blueprint(webhooks_bp, url_prefix="/webhooks")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    # Åablonlarda kullanÄ±lacak yardÄ±mcÄ±lar
    from datetime import datetime
    import utils

    from routes.admin import is_admin
    from flask_login import current_user

    def csrf_token():
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token
        return token

    @app.before_request
    def protect_forms():
        if request.method != "POST" or request.path.startswith("/webhooks/"):
            return None
        sent = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(str(session.get("_csrf_token", "")), str(sent)):
            abort(400)
        return None

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.context_processor
    def inject_helpers():
        return {
            "now": datetime.utcnow,
            "status_label": utils.status_label,
            "status_color": utils.status_color,
            "platform_label": utils.platform_label,
            "bot_username": app.config.get("TELEGRAM_BOT_USERNAME", ""),
            "user_is_admin": is_admin(current_user),
            "is_pro_user": lambda user=None: (getattr(user or current_user, "plan", "free") or "free").lower() == "pro",
            "user_can_whatsapp": lambda user=None: bool(getattr(user or current_user, "has_whatsapp_access", False)),
            "user_can_multi_platform": lambda user=None: bool(getattr(user or current_user, "has_multi_platform_access", False)),
            "company": {
                "legal_name": app.config.get("COMPANY_LEGAL_NAME", "SipariÅŸGeldi"),
                "brand_name": app.config.get("COMPANY_BRAND_NAME", "SipariÅŸGeldi"),
                "address": app.config.get("COMPANY_ADDRESS", ""),
                "phone": app.config.get("COMPANY_PHONE", ""),
                "email": app.config.get("COMPANY_EMAIL", ""),
                "tax_office": app.config.get("COMPANY_TAX_OFFICE", ""),
                "tax_number": app.config.get("COMPANY_TAX_NUMBER", ""),
            },
            "csrf_token": csrf_token,
        }

    # TablolarÄ± oluÅŸtur + hafif ÅŸema gÃ¼ncellemeleri (mevcut Postgres'e yeni kolon)
    with app.app_context():
        db.create_all()
        _ensure_schema()

    # Arka plan zamanlayÄ±cÄ± (dev: web sÃ¼reci iÃ§inde)
    should_start = app.config.get("RUN_SCHEDULER", True) if start_scheduler is None else start_scheduler
    if should_start:
        from worker import start_scheduler as _start
        _start(app)

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

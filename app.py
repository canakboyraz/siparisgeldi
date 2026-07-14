"""Uygulama fabrikası (application factory)."""
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import text

from config import Config
from extensions import db, login_manager


def _ensure_schema():
    """Var olan Postgres tablolarına eksik kolonları güvenle ekler.
    create_all() yalnızca eksik TABLOLARI oluşturur, kolon eklemez; bu yüzden
    sonradan eklenen alanlar için hafif bir 'ADD COLUMN IF NOT EXISTS' geçeriz.
    SQLite (yerel) taze DB oluşturduğundan atlanır."""
    backend = db.engine.url.get_backend_name()
    if not backend.startswith("postgres"):
        return
    stmts = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_number VARCHAR(30)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS notification_channel VARCHAR(20) DEFAULT 'telegram'",
        "ALTER TABLE integrations ADD COLUMN IF NOT EXISTS migros_group_id VARCHAR(50)",
    ]
    with db.engine.begin() as conn:
        for s in stmts:
            try:
                conn.execute(text(s))
            except Exception as e:
                print(f"[SCHEMA] atlandı: {s} → {e}")


def create_app(config_class=Config, start_scheduler=None):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Reverse proxy (Railway/Render/Nginx) arkasında gerçek şema/host'u oku ki
    # url_for(_external=True) → https://siparisgeldi.net/... doğru üretilsin.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Eklentileri bağla
    db.init_app(app)
    login_manager.init_app(app)

    # Modeller (tablo kaydı için import şart)
    import models  # noqa: F401

    # Blueprint'ler
    from routes.public import public_bp
    from routes.auth import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.webhooks import webhooks_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp, url_prefix="/panel")
    app.register_blueprint(webhooks_bp, url_prefix="/webhooks")

    # Şablonlarda kullanılacak yardımcılar
    from datetime import datetime
    import utils

    @app.context_processor
    def inject_helpers():
        return {
            "now": datetime.utcnow,
            "status_label": utils.status_label,
            "status_color": utils.status_color,
            "platform_label": utils.platform_label,
            "bot_username": app.config.get("TELEGRAM_BOT_USERNAME", ""),
        }

    # Tabloları oluştur + hafif şema güncellemeleri (mevcut Postgres'e yeni kolon)
    with app.app_context():
        db.create_all()
        _ensure_schema()

    # Arka plan zamanlayıcı (dev: web süreci içinde)
    should_start = app.config.get("RUN_SCHEDULER", True) if start_scheduler is None else start_scheduler
    if should_start:
        from worker import start_scheduler as _start
        _start(app)

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

"""Uygulama fabrikası (application factory)."""
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from extensions import db, login_manager


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

    # Tabloları oluştur
    with app.app_context():
        db.create_all()

    # Arka plan zamanlayıcı (dev: web süreci içinde)
    should_start = app.config.get("RUN_SCHEDULER", True) if start_scheduler is None else start_scheduler
    if should_start:
        from worker import start_scheduler as _start
        _start(app)

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

"""Uygulama yapılandırması."""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")

    # Genel alan adı / marka
    APP_DOMAIN = os.environ.get("APP_DOMAIN", "siparisgeldi.net")
    # Reverse proxy (Railway/Render) arkasında dış URL'ler https üretilsin
    PREFERRED_URL_SCHEME = os.environ.get("PREFERRED_URL_SCHEME", "https")

    # Veritabanı — varsayılan SQLite, prod'da DATABASE_URL ile Postgres.
    # Railway/Heroku bazen "postgres://" verir; SQLAlchemy "postgresql://" ister.
    _db_url = os.environ.get("DATABASE_URL", "sqlite:///siparis_saas.db")
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # API credential şifreleme anahtarı (Fernet). Üret:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")

    # Merkezi Telegram botu (BotFather). Kullanıcılar bu botu /start'lar.
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "")  # @ olmadan

    # Sipariş polling aralığı (saniye)
    POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))

    # Migros Yemek (Gourmet) API
    # Test: https://test.gourmet.migrosonline.com  ·  Canlı: https://gourmet.migrosonline.com
    MIGROS_API_BASE = os.environ.get("MIGROS_API_BASE", "https://gourmet.migrosonline.com")
    # Secret Key ENTEGRASYON FİRMASI (bizim) bazında TEK adettir; şifreleme için
    # kullanılır. Migros webhook URL'lerini ilettikten sonra bize verilir.
    MIGROS_SECRET_KEY = os.environ.get("MIGROS_SECRET_KEY", "")
    # Migros webhook'ları Basic Auth ile gelir (firma bazında tek kimlik).
    # Migros'a vereceğin kullanıcı/parola; boşsa doğrulama atlanır.
    MIGROS_WEBHOOK_USER = os.environ.get("MIGROS_WEBHOOK_USER", "")
    MIGROS_WEBHOOK_PASS = os.environ.get("MIGROS_WEBHOOK_PASS", "")

    # Scheduler'ı web süreci içinde başlat (tek instance dev için). Prod'da
    # ayrı worker süreci öneririz → RUN_SCHEDULER=0 yapıp worker.py'yi ayrı çalıştır.
    RUN_SCHEDULER = os.environ.get("RUN_SCHEDULER", "1") == "1"

"""Veritabanı modelleri — çok kullanıcılı SaaS."""
import secrets
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db, login_manager
import security


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name          = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    plan          = db.Column(db.String(20), default="free")   # free | pro
    is_active     = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    # Merkezi Telegram botu bağlama
    telegram_chat_id   = db.Column(db.String(50))                 # /start ile yakalanır
    telegram_link_token = db.Column(db.String(64), unique=True, index=True)

    # WhatsApp (Meta Cloud API) ve kanal tercihi
    whatsapp_number     = db.Column(db.String(30))
    notification_channel = db.Column(db.String(20), default="telegram")  # telegram | whatsapp | both

    integrations = db.relationship("Integration", backref="user", lazy=True, cascade="all, delete-orphan")
    orders       = db.relationship("Order", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def ensure_link_token(self):
        if not self.telegram_link_token:
            self.telegram_link_token = secrets.token_urlsafe(24)
        return self.telegram_link_token

    @property
    def telegram_connected(self) -> bool:
        return bool(self.telegram_chat_id)

    def __repr__(self):
        return f"<User {self.email}>"


class Integration(db.Model):
    """Her kullanıcının her platform için bağlantı bilgileri."""
    __tablename__ = "integrations"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    platform   = db.Column(db.String(30), nullable=False)   # trendyolgo | migros
    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # TrendyolGo (secret'lar şifreli saklanır — _ ile başlayan kolonlar)
    tgo_supplier_id = db.Column(db.String(50))
    _tgo_api_key    = db.Column("tgo_api_key", db.String(512))
    _tgo_api_secret = db.Column("tgo_api_secret", db.String(512))

    # Migros Yemek (webhook tabanlı). Secret key FİRMA bazında olduğu için burada
    # tutulmaz (global config). Burada restoran bazlı api key + store/zincir id.
    _migros_api_key    = db.Column("migros_api_key", db.String(512))
    _migros_secret_key = db.Column("migros_secret_key", db.String(512))  # kullanılmıyor (geriye dönük)
    migros_store_id    = db.Column(db.String(50), index=True)   # webhook eşleştirme anahtarı
    migros_group_id    = db.Column(db.String(50))               # zincir/marka id
    webhook_token      = db.Column(db.String(64), unique=True)

    # Bildirim tercihleri
    notify_new_order      = db.Column(db.Boolean, default=True)
    notify_status_change  = db.Column(db.Boolean, default=True)
    notify_cancel         = db.Column(db.Boolean, default=True)
    notify_daily_report   = db.Column(db.Boolean, default=True)
    notify_weekly_report  = db.Column(db.Boolean, default=True)
    notify_monthly_report = db.Column(db.Boolean, default=True)

    # Son senkron durumu (teşhis için)
    last_sync_at    = db.Column(db.DateTime)
    last_error      = db.Column(db.String(300))

    __table_args__ = (
        db.UniqueConstraint("user_id", "platform", name="uq_user_platform"),
    )

    # --- Şifreli alan erişimcileri ---
    @property
    def tgo_api_key(self):
        return security.decrypt(self._tgo_api_key)

    @tgo_api_key.setter
    def tgo_api_key(self, value):
        self._tgo_api_key = security.encrypt(value)

    @property
    def tgo_api_secret(self):
        return security.decrypt(self._tgo_api_secret)

    @tgo_api_secret.setter
    def tgo_api_secret(self, value):
        self._tgo_api_secret = security.encrypt(value)

    @property
    def migros_api_key(self):
        return security.decrypt(self._migros_api_key)

    @migros_api_key.setter
    def migros_api_key(self, value):
        self._migros_api_key = security.encrypt(value)

    @property
    def migros_secret_key(self):
        return security.decrypt(self._migros_secret_key)

    @migros_secret_key.setter
    def migros_secret_key(self, value):
        self._migros_secret_key = security.encrypt(value)

    def __repr__(self):
        return f"<Integration user={self.user_id} platform={self.platform}>"


class Order(db.Model):
    """Gelen tüm siparişlerin kaydı."""
    __tablename__ = "orders"

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    platform       = db.Column(db.String(30), nullable=False)
    external_id    = db.Column(db.String(100), nullable=False)
    order_number   = db.Column(db.String(50))
    status         = db.Column(db.String(30))
    total_price    = db.Column(db.Float, default=0)
    payment_type   = db.Column(db.String(50))
    app_source     = db.Column(db.String(30))
    customer_note  = db.Column(db.String(500))
    raw_json       = db.Column(db.Text)
    notified_statuses = db.Column(db.String(200), default="")
    created_at     = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at     = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("user_id", "platform", "external_id", name="uq_user_platform_order"),
    )

    def is_status_notified(self, status: str) -> bool:
        return status in (self.notified_statuses or "").split(",")

    def mark_status_notified(self, status: str):
        sent = set(filter(None, (self.notified_statuses or "").split(",")))
        sent.add(status)
        self.notified_statuses = ",".join(sent)

    def __repr__(self):
        return f"<Order {self.platform}#{self.order_number}>"


class AppState(db.Model):
    """Basit anahtar-değer durum saklama (ör. Telegram getUpdates offset)."""
    __tablename__ = "app_state"

    key   = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(255))

    @staticmethod
    def get(key: str, default: str = None) -> str:
        row = db.session.get(AppState, key)
        return row.value if row else default

    @staticmethod
    def set(key: str, value: str):
        row = db.session.get(AppState, key)
        if row:
            row.value = str(value)
        else:
            db.session.add(AppState(key=key, value=str(value)))
        db.session.commit()

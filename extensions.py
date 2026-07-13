"""Flask eklentileri — tek yerde tanımlanır, dairesel import'u önler."""
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Devam etmek için giriş yapın."
login_manager.login_message_category = "warning"

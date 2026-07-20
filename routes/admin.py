"""Admin paneli — sadece ADMIN_EMAILS'teki kullanıcılar erişebilir.

Kullanıcıları, entegrasyonları ve genel istatistikleri görüntüler. Salt-okunur
(yönetim/silme aksiyonları ileride eklenebilir).
"""
from functools import wraps
from flask import Blueprint, render_template, current_app, abort
from flask_login import login_required, current_user

from extensions import db
from models import User, Integration, Order

admin_bp = Blueprint("admin", __name__)


def admin_required(f):
    """Sadece config'teki ADMIN_EMAILS listesindeki kullanıcıya izin verir."""
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        admins = current_app.config.get("ADMIN_EMAILS", [])
        if (current_user.email or "").lower() not in admins:
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def is_admin(user) -> bool:
    """Şablonlarda 'admin linkini göster' kontrolü için."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    admins = current_app.config.get("ADMIN_EMAILS", [])
    return (user.email or "").lower() in admins


@admin_bp.route("/")
@admin_required
def index():
    users = User.query.order_by(User.created_at.desc()).all()

    total_users        = len(users)
    total_integrations = Integration.query.count()
    active_integrations = Integration.query.filter_by(is_active=True).count()
    total_orders       = Order.query.count()
    error_integrations = Integration.query.filter(Integration.last_error.isnot(None)).count()
    telegram_connected = sum(1 for u in users if u.telegram_chat_id)
    whatsapp_connected = sum(1 for u in users if u.whatsapp_number)

    # Her kullanıcı için özet satır verisi
    rows = []
    for u in users:
        intgs = u.integrations
        rows.append({
            "user": u,
            "platforms": ", ".join(sorted({i.platform for i in intgs})) or "—",
            "platform_count": len(intgs),
            "order_count": Order.query.filter_by(user_id=u.id).count(),
            "telegram": bool(u.telegram_chat_id),
            "whatsapp": bool(u.whatsapp_number),
        })

    stats = {
        "total_users": total_users,
        "total_integrations": total_integrations,
        "active_integrations": active_integrations,
        "total_orders": total_orders,
        "error_integrations": error_integrations,
        "telegram_connected": telegram_connected,
        "whatsapp_connected": whatsapp_connected,
    }

    recent_orders = (
        Order.query
        .order_by(Order.created_at.desc())
        .limit(20)
        .all()
    )
    recent_integrations = (
        Integration.query
        .order_by(Integration.updated_at.desc())
        .limit(20)
        .all()
    )
    problem_integrations = (
        Integration.query
        .filter(Integration.last_error.isnot(None))
        .order_by(Integration.updated_at.desc())
        .limit(20)
        .all()
    )

    return render_template(
        "admin/index.html",
        stats=stats,
        rows=rows,
        recent_orders=recent_orders,
        recent_integrations=recent_integrations,
        problem_integrations=problem_integrations,
    )

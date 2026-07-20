"""Admin paneli — sadece ADMIN_EMAILS'teki kullanıcılar erişebilir.

Kullanıcıları, entegrasyonları ve genel istatistikleri görüntüler. Salt-okunur
(yönetim/silme aksiyonları ileride eklenebilir).
"""
from functools import wraps
from flask import Blueprint, render_template, current_app, abort, request
from flask_login import login_required, current_user
from sqlalchemy import func, or_

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
    for u in users[:5]:
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
        .limit(5)
        .all()
    )
    recent_integrations = (
        Integration.query
        .order_by(Integration.updated_at.desc())
        .limit(5)
        .all()
    )
    problem_integrations = (
        Integration.query
        .filter(Integration.last_error.isnot(None))
        .order_by(Integration.updated_at.desc())
        .limit(5)
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


@admin_bp.route("/kullanicilar")
@admin_required
def users():
    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "").strip()
    channel = request.args.get("channel", "").strip()

    query = User.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.name.ilike(like), User.email.ilike(like)))
    if channel:
        query = query.filter(User.notification_channel == channel)

    users_paged = (
        query
        .order_by(User.created_at.desc())
        .paginate(page=page, per_page=25, error_out=False)
    )
    user_ids = [u.id for u in users_paged.items]
    order_counts = {}
    platforms_by_user = {}
    if user_ids:
        counts = (
            db.session.query(Order.user_id, func.count(Order.id))
            .filter(Order.user_id.in_(user_ids))
            .group_by(Order.user_id)
            .all()
        )
        order_counts = {user_id: count for user_id, count in counts}
        platforms_by_user = {
            u.id: ", ".join(sorted({i.platform for i in u.integrations})) or "—"
            for u in users_paged.items
        }

    return render_template(
        "admin/users.html",
        users=users_paged,
        order_counts=order_counts,
        platforms_by_user=platforms_by_user,
        filters={"q": q, "channel": channel},
    )


@admin_bp.route("/siparisler")
@admin_required
def orders():
    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "").strip()
    platform = request.args.get("platform", "").strip()
    status = request.args.get("status", "").strip()

    query = Order.query.join(User)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Order.order_number.ilike(like),
            Order.external_id.ilike(like),
            User.name.ilike(like),
            User.email.ilike(like),
        ))
    if platform:
        query = query.filter(Order.platform == platform)
    if status:
        query = query.filter(Order.status == status)

    orders_paged = (
        query
        .order_by(Order.created_at.desc())
        .paginate(page=page, per_page=25, error_out=False)
    )
    platforms = [p for (p,) in db.session.query(Order.platform).distinct().order_by(Order.platform).all()]
    statuses = [s for (s,) in db.session.query(Order.status).distinct().order_by(Order.status).all() if s]

    return render_template(
        "admin/orders.html",
        orders=orders_paged,
        platforms=platforms,
        statuses=statuses,
        filters={"q": q, "platform": platform, "status": status},
    )


@admin_bp.route("/entegrasyonlar")
@admin_required
def integrations():
    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "").strip()
    platform = request.args.get("platform", "").strip()
    state = request.args.get("state", "").strip()

    query = Integration.query.join(User)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            User.name.ilike(like),
            User.email.ilike(like),
            Integration.platform.ilike(like),
            Integration.tgo_supplier_id.ilike(like),
            Integration.migros_store_id.ilike(like),
            Integration.migros_group_id.ilike(like),
        ))
    if platform:
        query = query.filter(Integration.platform == platform)
    if state == "active":
        query = query.filter(Integration.is_active.is_(True))
    elif state == "inactive":
        query = query.filter(Integration.is_active.is_(False))
    elif state == "error":
        query = query.filter(Integration.last_error.isnot(None))

    integrations_paged = (
        query
        .order_by(Integration.updated_at.desc())
        .paginate(page=page, per_page=25, error_out=False)
    )
    platforms = [p for (p,) in db.session.query(Integration.platform).distinct().order_by(Integration.platform).all()]

    return render_template(
        "admin/integrations.html",
        integrations=integrations_paged,
        platforms=platforms,
        filters={"q": q, "platform": platform, "state": state},
    )

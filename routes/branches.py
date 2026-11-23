"""Şubeler: merkez hesabın şubeleri davet edip toplam satış ve kârı görmesi (/panel/subeler)."""
import re
from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

import branches
import profit_report
from extensions import db
from models import BranchLink, Integration, User

branches_bp = Blueprint("branches", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _back(**kw):
    return redirect(url_for("branches.index", **kw))


def _domain():
    return (current_app.config.get("APP_DOMAIN") or "siparisgeldi.net").removeprefix("https://").removeprefix("http://").rstrip("/")


def _send_invite_email(link, owner):
    try:
        from notifications.email import send_email
        url = f"https://{_domain()}/panel/subeler?davet={link.token}"
        text = (f"Merhaba,\n\n{owner.name} seni SiparişGeldi'de şubesi olarak eklemek istiyor"
                f"{' (' + link.label + ')' if link.label else ''}. Kabul edersen şubenin günlük satış ve kâr özeti "
                f"merkezde toplu görünür; siparişlerin ve ayarların senin hesabında kalır.\n\n"
                f"Daveti görmek için bu e-postayla ({link.email}) SiparişGeldi'ye giriş yap: {url}\n")
        html = (f"<p>Merhaba,</p><p><b>{owner.name}</b> seni SiparişGeldi'de şubesi olarak eklemek istiyor"
                f"{' (' + link.label + ')' if link.label else ''}. Kabul edersen şubenin günlük satış ve kâr özeti "
                f"merkezde toplu görünür; siparişlerin ve ayarların senin hesabında kalır.</p>"
                f"<p><a href=\"{url}\">Daveti gör</a></p>")
        return send_email(link.email, f"{owner.name} seni şubesi olarak ekledi", text, html)
    except Exception as e:  # e-posta gitmese de davet panelde görünür
        print(f"[ŞUBELER] davet e-postası gönderilemedi: {e}")
        return False


@branches_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    group = branches.group_for_owner(current_user.id)
    mine = branches.membership(current_user.id)

    if request.method == "POST":
        action = request.form.get("action")

        # ── Şube tarafı ──
        if action in ("accept", "decline"):
            link = db.session.get(BranchLink, request.form.get("link_id", type=int))
            token_ok = link and request.form.get("token") == link.token
            email_ok = link and link.email.lower() == (current_user.email or "").lower()
            if not link or link.status != "pending" or not (token_ok or email_ok):
                flash("Davet bulunamadı ya da artık geçerli değil.", "warning")
                return _back()
            if action == "decline":
                db.session.delete(link)
                db.session.commit()
                flash("Davet reddedildi.", "info")
                return _back()
            if link.group.owner_id == current_user.id:
                flash("Kendi davetini kabul edemezsin.", "warning")
                return _back()
            if mine:
                flash("Zaten bir merkeze bağlısın; önce oradan ayrıl.", "warning")
                return _back()
            if group and any(l.status == "active" for l in group.links):
                flash("Bu hesap zaten şubeleri olan bir merkez; şube olarak bağlanamaz.", "warning")
                return _back()
            link.branch_id, link.status, link.accepted_at = current_user.id, "active", datetime.utcnow()
            db.session.commit()
            flash(f"{link.group.owner_label or 'Merkez'} hesabına şube olarak bağlandın.", "success")
            return _back()
        if action == "leave" and mine:
            db.session.delete(mine)
            db.session.commit()
            flash("Merkezden ayrıldın; satışların artık orada görünmeyecek.", "success")
            return _back()
        if action == "own_reports":
            on = request.form.get("on") == "1"
            for intg in Integration.query.filter_by(user_id=current_user.id).all():
                intg.notify_daily_report = on
            db.session.commit()
            flash("Gün sonu raporların açıldı." if on else "Gün sonu raporların kapatıldı; toplam merkeze gidiyor.", "success")
            return _back()

        # ── Merkez tarafı ──
        if mine:
            flash("Şube hesabı başka şube ekleyemez.", "warning")
            return _back()
        if action == "invite":
            email = (request.form.get("email") or "").strip().lower()[:120]
            label = (request.form.get("label") or "").strip()[:80]
            if not EMAIL_RE.match(email):
                flash("Şubenin SiparişGeldi hesabındaki e-posta adresini yaz.", "warning")
                return _back()
            if email == (current_user.email or "").lower():
                flash("Kendi hesabın zaten merkez olarak toplamda.", "info")
                return _back()
            group = branches.ensure_group(current_user)
            if any(l.email.lower() == email for l in group.links):
                flash("Bu e-posta zaten eklenmiş.", "info")
                return _back()
            link = BranchLink(group_id=group.id, email=email, label=label or None)
            db.session.add(link)
            db.session.commit()
            existing = User.query.filter(db.func.lower(User.email) == email).first()
            sent = _send_invite_email(link, current_user)
            note = "" if existing else " Bu e-postayla henüz hesap yok; şube kaydolunca daveti görecek."
            flash(f"Davet gönderildi{' (e-posta ile)' if sent else ''}. Şube kabul edince listede görünecek.{note}", "success")
            return _back()
        if not group:
            return _back()
        if action == "remove":
            link = BranchLink.query.filter_by(id=request.form.get("link_id", type=int), group_id=group.id).first()
            if link:
                db.session.delete(link)
                db.session.commit()
                flash(f"{link.label or link.email} şubelerden çıkarıldı.", "success")
            return _back()
        if action == "rename":
            link = BranchLink.query.filter_by(id=request.form.get("link_id", type=int), group_id=group.id).first()
            if link:
                link.label = (request.form.get("label") or "").strip()[:80] or None
                db.session.commit()
            return _back()
        if action == "settings":
            group.daily_summary = request.form.get("daily_summary") == "1"
            group.include_owner = request.form.get("include_owner") == "1"
            group.owner_label = (request.form.get("owner_label") or "").strip()[:80] or current_user.name
            db.session.commit()
            flash("Ayarlar kaydedildi.", "success")
            return _back()
        if action == "copy_costs":
            ids = [l.branch_id for l in group.links if l.status == "active" and l.branch_id]
            result = branches.copy_costs(current_user.id, ids, overwrite=request.form.get("overwrite") == "1")
            flash(f"Maliyetler {len(ids)} şubeye kopyalandı ({sum(result.values())} ürün).", "success")
            return _back()
        return _back()

    # ── GET ──
    invite_token = request.args.get("davet")
    invites = branches.pending_invites(current_user.email)
    if invite_token:
        link = BranchLink.query.filter_by(token=invite_token, status="pending").first()
        if link and link not in invites:
            invites.append(link)
    period = request.args.get("donem", "bugun")
    if period not in dict(branches.PERIODS):
        period = "bugun"
    data = None
    if group and (any(l.status == "active" for l in group.links)):
        start, end = branches.period_range(period)
        data = branches.summary(group, start, end)
    own_reports_on = any(i.notify_daily_report for i in Integration.query.filter_by(user_id=current_user.id).all())
    price = current_app.config.get("PRO_MONTHLY_PRICE", 250)
    from utils import platform_label
    return render_template("dashboard/branches.html", group=group, mine=mine, invites=invites, data=data,
                           period=period, periods=branches.PERIODS, tl=profit_report.tl, price=price,
                           own_reports_on=own_reports_on, platform_label=platform_label)

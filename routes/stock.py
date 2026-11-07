"""Günlük stok sayımı: baristanın telefon ekranı (/s/<token>) ve işletme paneli (/panel/sayim)."""
import csv
import io

from flask import (Blueprint, Response, abort, current_app, flash, make_response, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required
from itsdangerous import BadSignature, URLSafeSerializer
from werkzeug.security import check_password_hash, generate_password_hash

import stock
from extensions import db
from models import StockCategory, StockCount, StockItem, StockSetting

stock_public_bp = Blueprint("stock_public", __name__)
stock_bp = Blueprint("stock", __name__)


def _signer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="stock-count")


# ── Barista ekranı ──────────────────────────────────────────────────────────

def _setting_or_404(token):
    setting = StockSetting.query.filter_by(token=token).first()
    if not setting:
        abort(404)
    return setting


def _pin_ok(setting):
    if not setting.pin_hash:
        return True
    raw = request.cookies.get(f"{stock.COOKIE_PREFIX}{setting.user_id}")
    try:
        data = _signer().loads(raw) if raw else None
    except BadSignature:
        return False
    return isinstance(data, dict) and data.get("u") == setting.user_id and data.get("p") == setting.pin_hash[-12:]


def _owner(setting):
    from models import User
    return db.session.get(User, setting.user_id)


def _count_page(setting, owner, values=None, errors=None, status=200):
    values = values or {}
    prev = stock.last_counted(owner)
    names = [r[0] for r in db.session.query(StockCount.counted_by).filter_by(user_id=owner.id)
             .group_by(StockCount.counted_by).order_by(db.func.max(StockCount.id).desc()).limit(12)]
    return render_template("stock/count.html", setting=setting, owner=owner, groups=stock.categories(owner),
                           prev=prev, fmt=stock.fmt, values=values, errors=errors or {}, names=names,
                           recv_on=any(k.startswith("r_") and v for k, v in values.items()),
                           today=stock.today_local().isoformat()), status


@stock_public_bp.route("/s/<token>", methods=["GET", "POST"])
def count_form(token):
    setting = _setting_or_404(token)
    owner = _owner(setting)
    if not _pin_ok(setting):
        return render_template("stock/pin.html", setting=setting, owner=owner)
    if request.method == "GET":
        return _count_page(setting, owner)

    form = request.form
    values, errors, entries = dict(form), {}, {}
    who = stock.clean(form.get("counted_by"), 60)
    day = stock.parse_day(form.get("count_date"))
    if len(who) < 2:
        errors["counted_by"] = "Adını yaz."
    if not day:
        errors["count_date"] = "Geçerli bir tarih seç (ileri tarih olamaz)."
    filled = 0
    for _cat, items in stock.categories(owner):
        for item in items:
            entry = {}
            for key, field in (("counted", f"c_{item.id}"), ("received", f"r_{item.id}")):
                try:
                    entry[key] = stock.parse_qty(form.get(field))
                except ValueError:
                    errors[field] = "Sayı yaz (ör. 2 ya da 2,5)."
            entry["note"] = form.get(f"n_{item.id}", "")
            if entry.get("counted") is not None:
                filled += 1
            entries[item.id] = entry
    if not errors and filled == 0:
        errors["_form"] = "Hiç ürün sayılmamış. En az bir ürünün miktarını yaz."
    if errors:
        if "_form" not in errors:
            errors["_form"] = "Bazı alanlar eksik ya da hatalı; kırmızı işaretli yerleri düzelt."
        return _count_page(setting, owner, values, errors, 400)
    count = stock.save_count(owner, who, day, entries, form.get("note", ""))
    response = make_response(redirect(url_for("stock_public.done", token=token, key=_signer().dumps(count.id))))
    response.set_cookie("sg_sayim_ad", who, max_age=180 * 24 * 3600, samesite="Lax",
                        secure=bool(current_app.config.get("SESSION_COOKIE_SECURE")))
    return response


@stock_public_bp.post("/s/<token>/pin")
def pin_login(token):
    setting = _setting_or_404(token)
    pin = (request.form.get("pin") or "").strip()
    if not setting.pin_hash or not check_password_hash(setting.pin_hash, pin):
        return render_template("stock/pin.html", setting=setting, owner=_owner(setting), error="PIN yanlış."), 400
    response = make_response(redirect(url_for("stock_public.count_form", token=token)))
    response.set_cookie(f"{stock.COOKIE_PREFIX}{setting.user_id}",
                        _signer().dumps({"u": setting.user_id, "p": setting.pin_hash[-12:]}),
                        max_age=60 * 24 * 3600, httponly=True, samesite="Lax",
                        secure=bool(current_app.config.get("SESSION_COOKIE_SECURE")))
    return response


@stock_public_bp.get("/s/<token>/tamam/<key>")
def done(token, key):
    setting = _setting_or_404(token)
    try:
        count_id = _signer().loads(key)
    except BadSignature:
        abort(404)
    count = StockCount.query.filter_by(id=count_id, user_id=setting.user_id).first_or_404()
    return render_template("stock/done.html", setting=setting, owner=_owner(setting), count=count,
                           s=stock.summarize(count), fmt=stock.fmt, signed=stock.signed,
                           can_edit=stock.can_staff_edit(count), key=key,
                           edited=request.args.get("duzeltildi") == "1")


def _edit_page(count, owner, action, back, values=None, errors=None, status=200, staff=False):
    groups = stock.grouped_lines(count)
    return render_template("stock/edit.html", count=count, owner=owner, groups=groups, fmt=stock.fmt,
                           values=values, errors=errors or {}, action=action, back=back, staff=staff,
                           today=stock.today_local().isoformat()), status


def _save_edit(count, editor, action, back, owner, staff):
    """Düzeltme formunu kaydeder; hata varsa formu yeniden gösterir, yoksa None döner."""
    form = request.form
    ids = [l.id for l in count.lines.all()]
    entries, errors = stock.parse_entries(form, ids)
    day = stock.parse_day(form.get("count_date")) if form.get("count_date") else None
    if form.get("count_date") and not day:
        errors["count_date"] = "Geçerli bir tarih seç (ileri tarih olamaz)."
    if not any(e.get("counted") is not None for e in entries.values()) and not errors:
        errors["_form"] = "Hiç ürün sayılmamış görünüyor. Sayımın tamamı yanlışsa silebilirsin."
    if errors:
        errors.setdefault("_form", "Bazı alanlar hatalı; kırmızı işaretli yerleri düzelt.")
        return _edit_page(count, owner, action, back, dict(form), errors, 400, staff)
    changed = stock.update_count(count, entries, editor, counted_by=form.get("counted_by"), count_date=day,
                                 note=form.get("note"))
    return changed


@stock_public_bp.route("/s/<token>/duzelt/<key>", methods=["GET", "POST"])
def staff_edit(token, key):
    setting = _setting_or_404(token)
    owner = _owner(setting)
    if not _pin_ok(setting):
        return render_template("stock/pin.html", setting=setting, owner=owner)
    try:
        count_id = _signer().loads(key)
    except BadSignature:
        abort(404)
    count = StockCount.query.filter_by(id=count_id, user_id=setting.user_id).first_or_404()
    done_url = url_for("stock_public.done", token=token, key=key)
    if not stock.can_staff_edit(count):
        return render_template("stock/edit.html", count=count, owner=owner, expired=True, back=done_url,
                               hours=stock.EDIT_WINDOW_HOURS)
    action = url_for("stock_public.staff_edit", token=token, key=key)
    if request.method == "GET":
        return _edit_page(count, owner, action, done_url, staff=True)
    result = _save_edit(count, count.counted_by, action, done_url, owner, staff=True)
    if not isinstance(result, int):
        return result
    return redirect(done_url + "?duzeltildi=1")


# ── İşletme paneli ──────────────────────────────────────────────────────────

def _cat(cat_id):
    return StockCategory.query.filter_by(id=cat_id, user_id=current_user.id).first_or_404()


def _back(anchor=""):
    return redirect(url_for("stock.items") + (f"#{anchor}" if anchor else ""))


@stock_bp.route("")
@login_required
def index():
    setting = stock.get_setting(current_user, create=True)
    counts = (StockCount.query.filter_by(user_id=current_user.id)
              .order_by(StockCount.count_date.desc(), StockCount.id.desc()).limit(40).all())
    rows = [(c, stock.summarize(c)) for c in counts]
    item_count = StockItem.query.filter_by(user_id=current_user.id, is_active=True).count()
    return render_template("stock/index.html", setting=setting, rows=rows, latest=rows[0] if rows else None,
                           item_count=item_count, fmt=stock.fmt, signed=stock.signed,
                           link=url_for("stock_public.count_form", token=setting.token, _external=True))


@stock_bp.get("/<int:count_id>")
@login_required
def detail(count_id):
    count = StockCount.query.filter_by(id=count_id, user_id=current_user.id).first_or_404()
    return render_template("stock/detail.html", count=count, groups=stock.grouped_lines(count),
                           s=stock.summarize(count), fmt=stock.fmt, signed=stock.signed,
                           only=request.args.get("goster", ""))


@stock_bp.get("/<int:count_id>.csv")
@login_required
def export_csv(count_id):
    count = StockCount.query.filter_by(id=count_id, user_id=current_user.id).first_or_404()
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["Tarih", count.count_date.strftime("%d.%m.%Y"), "Sayımı yapan", count.counted_by])
    w.writerow(["Kategori", "Ürün", "Birim", "Min. stok", "Önceki sayım", "Bugün gelen", "Sayılan",
                "Fark (öncekine göre)", "Kullanılan / fire", "Durum", "Not"])
    for line in count.lines.all():
        status = "SİPARİŞ VER" if line.needs_order else ("Yeterli" if line.counted is not None else "Sayılmadı")
        w.writerow([line.category_name, line.item_name, line.unit, stock.fmt(line.min_stock), stock.fmt(line.prev_qty),
                    stock.fmt(line.received), stock.fmt(line.counted), stock.signed(line.diff), stock.fmt(line.used),
                    status, line.note or ""])
    body = "﻿" + out.getvalue()   # Excel Türkçe karakterleri doğru açsın
    name = f"sayim-{count.count_date.isoformat()}.csv"
    return Response(body, mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@stock_bp.route("/<int:count_id>/duzelt", methods=["GET", "POST"])
@login_required
def edit_count(count_id):
    count = StockCount.query.filter_by(id=count_id, user_id=current_user.id).first_or_404()
    action = url_for("stock.edit_count", count_id=count.id)
    back = url_for("stock.detail", count_id=count.id)
    if request.method == "GET":
        return _edit_page(count, current_user, action, back)
    result = _save_edit(count, current_user.name or "Yönetici", action, back, current_user, staff=False)
    if not isinstance(result, int):
        return result
    flash(f"Sayım düzeltildi ({result} ürün değişti). Fark ve sipariş listesi yeniden hesaplandı." if result
          else "Değişiklik yok; sayım aynı kaldı.", "success")
    return redirect(back)


@stock_bp.post("/<int:count_id>/sil")
@login_required
def delete_count(count_id):
    count = StockCount.query.filter_by(id=count_id, user_id=current_user.id).first_or_404()
    db.session.delete(count)
    db.session.flush()
    stock.refresh_prev(current_user.id)
    db.session.commit()
    flash("Sayım silindi.", "success")
    return redirect(url_for("stock.index"))


@stock_bp.post("/ayarlar")
@login_required
def settings():
    setting = stock.get_setting(current_user, create=True)
    action = request.form.get("action")
    if action == "pin":
        pin = (request.form.get("pin") or "").strip()
        if not (pin.isdigit() and 4 <= len(pin) <= 6):
            flash("PIN 4–6 haneli rakam olmalı.", "danger")
        else:
            setting.pin_hash = generate_password_hash(pin)
            flash("PIN kaydedildi. Baristalar ilk girişte bu PIN'i yazacak.", "success")
    elif action == "pin_off":
        setting.pin_hash = None
        flash("PIN kaldırıldı; bağlantıyı bilen herkes sayım girebilir.", "success")
    elif action == "new_link":
        setting.token = stock.new_token()
        flash("Yeni bağlantı oluşturuldu. Eski bağlantı artık çalışmaz; yenisini baristalarla paylaş.", "success")
    db.session.commit()
    return redirect(url_for("stock.index") + "#baglanti")


@stock_bp.get("/urunler")
@login_required
def items():
    groups = stock.categories(current_user, with_inactive=True)
    return render_template("stock/items.html", groups=groups, fmt=stock.fmt, units=stock.UNITS)


@stock_bp.post("/kategori")
@login_required
def add_category():
    name = stock.clean(request.form.get("name"), 60)
    if len(name) < 2:
        flash("Kategori adı yaz.", "danger")
        return _back()
    cat = StockCategory(user_id=current_user.id, name=name, sort=stock.next_sort(StockCategory, user_id=current_user.id))
    db.session.add(cat)
    db.session.commit()
    flash(f"{name} kategorisi eklendi. Şimdi ürünlerini ekleyebilirsin.", "success")
    return _back(f"k{cat.id}")


@stock_bp.post("/kategori/<int:cat_id>/ad")
@login_required
def rename_category(cat_id):
    cat = _cat(cat_id)
    name = stock.clean(request.form.get("name"), 60)
    if len(name) >= 2:
        cat.name = name
        db.session.commit()
        flash("Kategori adı güncellendi.", "success")
    return _back(f"k{cat.id}")


@stock_bp.post("/kategori/<int:cat_id>/tasi")
@login_required
def move_category(cat_id):
    cat = _cat(cat_id)
    cats = StockCategory.query.filter_by(user_id=current_user.id).order_by(StockCategory.sort, StockCategory.id).all()
    i = cats.index(cat)
    j = i - 1 if request.form.get("yon") == "yukari" else i + 1
    if 0 <= j < len(cats):
        cats[i], cats[j] = cats[j], cats[i]
        for n, c in enumerate(cats):
            c.sort = (n + 1) * 10
        db.session.commit()
    return _back(f"k{cat.id}")


@stock_bp.post("/kategori/<int:cat_id>/sil")
@login_required
def delete_category(cat_id):
    cat = _cat(cat_id)
    name, n = cat.name, cat.items.count()
    db.session.delete(cat)
    db.session.commit()
    flash(f"{name} kategorisi ve içindeki {n} ürün silindi. Eski sayımlar etkilenmez.", "success")
    return _back()


@stock_bp.post("/kategori/<int:cat_id>/urunler")
@login_required
def save_items(cat_id):
    """Kategorideki ürünleri toplu kaydet (ad, birim, min. stok, aktif) ve yeni ürün ekle."""
    cat = _cat(cat_id)
    errors = 0
    for item in cat.items.all():
        p = f"i{item.id}_"
        if p + "name" not in request.form:
            continue
        name = stock.clean(request.form.get(p + "name"), 80)
        if name:
            item.name = name
        item.unit = stock.clean(request.form.get(p + "unit"), 20) or item.unit
        try:
            item.min_stock = stock.parse_qty(request.form.get(p + "min"))
        except ValueError:
            errors += 1
        item.is_active = request.form.get(p + "active") == "1"
    new_name = stock.clean(request.form.get("new_name"), 80)
    if new_name:
        try:
            new_min = stock.parse_qty(request.form.get("new_min"))
        except ValueError:
            new_min, errors = None, errors + 1
        db.session.add(StockItem(user_id=current_user.id, category_id=cat.id, name=new_name,
                                 unit=stock.clean(request.form.get("new_unit"), 20) or "adet", min_stock=new_min,
                                 sort=stock.next_sort(StockItem, category_id=cat.id)))
    db.session.commit()
    if errors:
        flash("Bazı min. stok değerleri sayı olmadığı için kaydedilmedi.", "warning")
    else:
        flash(f"{cat.name} kaydedildi." + (f" {new_name} eklendi." if new_name else ""), "success")
    return _back(f"k{cat.id}")


@stock_bp.post("/urun/<int:item_id>/tasi")
@login_required
def move_item(item_id):
    item = StockItem.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    items_ = item.category.items.all()
    i = items_.index(item)
    j = i - 1 if request.form.get("yon") == "yukari" else i + 1
    if 0 <= j < len(items_):
        items_[i], items_[j] = items_[j], items_[i]
        for n, it in enumerate(items_):
            it.sort = (n + 1) * 10
        db.session.commit()
    return _back(f"k{item.category_id}")


@stock_bp.post("/urun/<int:item_id>/kategori")
@login_required
def change_item_category(item_id):
    item = StockItem.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    cat = _cat(request.form.get(f"mv_{item_id}", type=int) or 0)
    item.category_id, item.sort = cat.id, stock.next_sort(StockItem, category_id=cat.id)
    db.session.commit()
    flash(f"{item.name} → {cat.name} kategorisine taşındı.", "success")
    return _back(f"k{cat.id}")


@stock_bp.post("/urun/<int:item_id>/sil")
@login_required
def delete_item(item_id):
    item = StockItem.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    cat_id, name = item.category_id, item.name
    db.session.delete(item)
    db.session.commit()
    flash(f"{name} silindi. Eski sayımlarda görünmeye devam eder.", "success")
    return _back(f"k{cat_id}")


@stock_bp.post("/ornek-liste")
@login_required
def seed():
    added = stock.seed_default(current_user)
    flash(f"Örnek kafe listesinden {added} ürün eklendi. Min. stokları kendine göre düzenleyebilirsin.", "success")
    return _back()


@stock_bp.post("/ice-aktar")
@login_required
def import_file():
    upload = request.files.get("file")
    if not upload or not upload.filename.lower().endswith(".xlsx"):
        flash("Excel (.xlsx) dosyası seç.", "danger")
        return _back()
    try:
        added = stock.import_xlsx(current_user, upload.stream)
    except Exception as exc:  # noqa: BLE001 — bozuk dosya kullanıcıya anlaşılır dönsün
        db.session.rollback()
        flash(f"Dosya okunamadı: {exc}", "danger")
        return _back()
    flash(f"Excel'den {added} ürün eklendi (aynı adlı ürünler atlandı).", "success")
    return _back()

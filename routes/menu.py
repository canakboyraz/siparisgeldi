"""QR menü: müşterinin masadaki ekranı (/m/<kod>) ve işletme paneli (/panel/menu)."""
import json
import secrets
from datetime import datetime, timedelta

from flask import (Blueprint, Response, abort, current_app, flash, jsonify, make_response, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required
from itsdangerous import BadSignature, URLSafeSerializer

import menu
from extensions import db
from models import MenuCategory, MenuImage, MenuItem, MenuSetting, MenuTable, TableCall, TableOrder

menu_public_bp = Blueprint("menu_public", __name__)
menu_bp = Blueprint("menu", __name__)
DEVICE_COOKIE = "sg_menu_cihaz"


def _signer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="table-order")


def _wants_json():
    return request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"


# ── Müşteri ekranı ──────────────────────────────────────────────────────────

def _resolve(code):
    """Masa kodu -> (masa, ayar); menü bağlantısı -> (None, ayar)."""
    table = MenuTable.query.filter_by(code=code, is_active=True).first()
    if table:
        setting = MenuSetting.query.filter_by(user_id=table.user_id).first()
        if setting:
            return table, setting
    setting = MenuSetting.query.filter_by(token=code).first()
    if not setting:
        abort(404)
    return None, setting


def _owner(setting):
    from models import User
    return db.session.get(User, setting.user_id)


@menu_public_bp.get("/m/<code>")
def public_menu(code):
    table, setting = _resolve(code)
    owner = _owner(setting)
    groups = menu.categories(owner, public=True)
    data = [{"id": c.id, "name": c.name, "items": [
        {"id": i.id, "name": i.name, "desc": i.description or "", "price": float(i.price or 0),
         "priceText": menu.tl(i.price), "available": bool(i.is_available), "opts": menu.item_options(i),
         "img": url_for("menu_public.image", image_id=i.image_id) if i.image_id else ""} for i in items]}
        for c, items in groups]
    response = make_response(render_template(
        "menu/public.html", setting=setting, owner=owner, table=table, groups=groups, data=data,
        can_order=bool(table and setting.ordering_open), can_call=bool(table and setting.calls_open is not False),
        tl=menu.tl))
    if table and not request.cookies.get(DEVICE_COOKIE):
        response.set_cookie(DEVICE_COOKIE, secrets.token_hex(12), max_age=365 * 24 * 3600, httponly=True,
                            samesite="Lax", secure=bool(current_app.config.get("SESSION_COOKIE_SECURE")))
    return response


@menu_public_bp.post("/m/<code>/siparis")
def place_order(code):
    table, _setting = _resolve(code)
    if not table:
        abort(404)
    payload = request.get_json(silent=True) or {}
    try:
        order = menu.create_order(table, payload, request.cookies.get(DEVICE_COOKIE))
    except menu.OrderError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    key = _signer().dumps(order.id)
    return jsonify({"ok": True, "order": order.id,
                    "url": url_for("menu_public.order_status", code=code, key=key)})


@menu_public_bp.get("/m/<code>/siparis/<key>")
def order_status(code, key):
    table, setting = _resolve(code)
    try:
        order_id = _signer().loads(key)
    except BadSignature:
        abort(404)
    order = TableOrder.query.filter_by(id=order_id, user_id=setting.user_id).first_or_404()
    if request.args.get("json"):
        response = jsonify({"status": order.status, "label": menu.CUSTOMER_LABEL[order.status],
                            "text": menu.CUSTOMER_STATUS[order.status]})
        response.headers["Cache-Control"] = "no-store"
        return response
    return render_template("menu/status.html", setting=setting, owner=_owner(setting), table=table, order=order,
                           can_call=bool(table and setting.calls_open is not False),
                           code=code, tl=menu.tl, status_text=menu.CUSTOMER_STATUS[order.status],
                           status_label=menu.CUSTOMER_LABEL[order.status])


def _call_signer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="table-call")


@menu_public_bp.post("/m/<code>/garson")
def call_waiter(code):
    table, _setting = _resolve(code)
    if not table:
        abort(404)
    try:
        call, _created = menu.create_call(table, request.cookies.get(DEVICE_COOKIE))
    except menu.OrderError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    key = _call_signer().dumps(call.id)
    return jsonify({"ok": True, "status": call.status,
                    "url": url_for("menu_public.call_status", code=code, key=key)})


def _call_from_key(code, key):
    table, setting = _resolve(code)
    try:
        call_id = _call_signer().loads(key)
    except BadSignature:
        abort(404)
    return TableCall.query.filter_by(id=call_id, user_id=setting.user_id).first_or_404()


@menu_public_bp.get("/m/<code>/garson/<key>")
def call_status(code, key):
    call = _call_from_key(code, key)
    response = jsonify({"status": call.status})
    response.headers["Cache-Control"] = "no-store"
    return response


@menu_public_bp.post("/m/<code>/garson/<key>/iptal")
def call_cancel(code, key):
    call = _call_from_key(code, key)
    menu.close_call(call, "cancelled")
    return jsonify({"ok": True, "status": call.status})


@menu_public_bp.get("/m/img/<int:image_id>.webp")
def image(image_id):
    img = db.session.get(MenuImage, image_id) or abort(404)
    response = Response(img.data, mimetype=img.mime)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


# ── Panel: siparişler ───────────────────────────────────────────────────────

def _today_start_utc():
    import pytz
    tz = pytz.timezone("Europe/Istanbul")
    start = tz.localize(datetime.combine(datetime.now(tz).date(), datetime.min.time()))
    return start.astimezone(pytz.utc).replace(tzinfo=None)


@menu_bp.route("")
@login_required
def orders():
    setting = menu.get_setting(current_user, create=True)
    durum = request.args.get("durum", "aktif")
    q = TableOrder.query.filter(TableOrder.user_id == current_user.id, TableOrder.created_at >= _today_start_utc())
    counts = {
        "aktif": q.filter(TableOrder.status.in_(("new", "preparing"))).count(),
        "served": q.filter_by(status="served").count(),
        "cancelled": q.filter_by(status="cancelled").count(),
    }
    if durum == "aktif":
        q = q.filter(TableOrder.status.in_(("new", "preparing")))
    elif durum in ("served", "cancelled"):
        q = q.filter_by(status=durum)
    rows = q.order_by(TableOrder.id.desc()).limit(200).all()
    today_total = sum((o.total for o in TableOrder.query.filter(
        TableOrder.user_id == current_user.id, TableOrder.created_at >= _today_start_utc(),
        TableOrder.status != "cancelled")), start=0)
    has_menu = MenuItem.query.filter_by(user_id=current_user.id).first() is not None
    has_tables = MenuTable.query.filter_by(user_id=current_user.id).first() is not None
    calls = (TableCall.query.filter_by(user_id=current_user.id, status="open")
             .order_by(TableCall.id.asc()).all())
    accounts = menu.open_accounts(current_user.id, _today_start_utc())
    return render_template("menu/orders.html", setting=setting, rows=rows, durum=durum, counts=counts, calls=calls,
                           accounts=accounts,
                           status=menu.STATUS, tl=menu.tl, today_total=today_total,
                           has_menu=has_menu, has_tables=has_tables,
                           adisyo_on=menu.adisyo_connection(current_user) is not None)


@menu_bp.get("/yeni.json")
@login_required
def new_orders_json():
    rows = (TableOrder.query.filter_by(user_id=current_user.id, status="new")
            .order_by(TableOrder.id.asc()).limit(10).all())
    calls = (TableCall.query.filter_by(user_id=current_user.id, status="open")
             .order_by(TableCall.id.asc()).limit(10).all())
    response = jsonify({"items": [menu.order_json(o) for o in rows], "calls": [menu.call_json(c) for c in calls]})
    response.headers["Cache-Control"] = "no-store"
    return response


@menu_bp.post("/cagri/<int:call_id>/tamam")
@login_required
def call_done(call_id):
    call = TableCall.query.filter_by(id=call_id, user_id=current_user.id).first_or_404()
    menu.close_call(call)
    if _wants_json():
        return jsonify({"ok": True})
    return redirect(request.form.get("next") if (request.form.get("next") or "").startswith("/panel/")
                    else url_for("menu.orders"))


@menu_bp.post("/siparis/<int:order_id>/<status>")
@login_required
def change_status(order_id, status):
    order = TableOrder.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    if status not in menu.STATUS:
        abort(404)
    sending = False   # Adisyo'ya artık masa hesabı kapanırken (Ödeme alındı) tek sipariş olarak yazılıyor
    menu.set_status(order, status)
    adisyo = None
    if sending:
        ok, message = menu.send_to_adisyo(order)
        adisyo = {"ok": ok, "message": message}
    if _wants_json():
        return jsonify({"ok": True, "status": status, "adisyo": adisyo})
    if adisyo:
        flash(adisyo["message"] if adisyo["ok"] else f"Adisyo'ya yazılamadı: {adisyo['message']}",
              "success" if adisyo["ok"] else "warning")
    return redirect(request.form.get("next") if (request.form.get("next") or "").startswith("/panel/")
                    else url_for("menu.orders"))


@menu_bp.post("/siparis/<int:order_id>/adisyo")
@login_required
def send_adisyo(order_id):
    order = TableOrder.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    ok, message = menu.send_to_adisyo(order)
    if _wants_json():
        return jsonify({"ok": ok, "message": message})
    flash(message if ok else f"Adisyo'ya yazılamadı: {message}", "success" if ok else "warning")
    return redirect(request.form.get("next") if (request.form.get("next") or "").startswith("/panel/")
                    else url_for("menu.orders"))


@menu_bp.post("/hesap/<int:table_id>/kapat")
@login_required
def close_account(table_id):
    """Ödeme alındı: masanın açık siparişleri kapanır, istenirse Adisyo'ya tek sipariş yazılır."""
    setting = menu.get_setting(current_user, create=True)
    write = (request.form.get("adisyo") == "1" and setting.adisyo_send == "accept"
             and menu.adisyo_connection(current_user) is not None)
    ok, message = menu.close_account(current_user, table_id, _today_start_utc(), write)
    if _wants_json():
        return jsonify({"ok": ok, "message": message})
    flash(message if ok else f"Hesap kapatılamadı: {message}", "success" if ok else "warning")
    return redirect(request.form.get("next") if (request.form.get("next") or "").startswith("/panel/")
                    else url_for("menu.orders"))


# ── Panel: menü düzenleme ───────────────────────────────────────────────────

def _cat(cat_id):
    return MenuCategory.query.filter_by(id=cat_id, user_id=current_user.id).first_or_404()


def _item(item_id):
    return MenuItem.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()


def _back(anchor=""):
    return redirect(url_for("menu.items") + (f"#{anchor}" if anchor else ""))


@menu_bp.get("/urunler")
@login_required
def items():
    setting = menu.get_setting(current_user, create=True)
    from models import Integration
    adisyo = Integration.query.filter_by(user_id=current_user.id, platform="adisyo", is_active=True).first()
    return render_template("menu/items.html", setting=setting, groups=menu.categories(current_user), tl=menu.tl,
                           has_adisyo=bool(adisyo and adisyo.adisyo_connection),
                           has_tgo=bool(_tgo_store_id()),
                           view_url=url_for("menu_public.public_menu", code=setting.token, _external=True))


@menu_bp.post("/kategori")
@login_required
def add_category():
    name = menu.clean(request.form.get("name"), 60)
    if len(name) < 2:
        flash("Kategori adı yaz.", "danger")
        return _back()
    cat = MenuCategory(user_id=current_user.id, name=name, sort=menu.next_sort(MenuCategory, user_id=current_user.id))
    db.session.add(cat)
    db.session.commit()
    flash(f"{name} eklendi. Şimdi ürünlerini ekleyebilirsin.", "success")
    return _back(f"k{cat.id}")


@menu_bp.post("/kategori/<int:cat_id>/duzenle")
@login_required
def edit_category(cat_id):
    cat = _cat(cat_id)
    name = menu.clean(request.form.get("name"), 60)
    if len(name) >= 2:
        cat.name = name
    cat.is_active = request.form.get("is_active") == "1"
    db.session.commit()
    flash("Kategori kaydedildi.", "success")
    return _back(f"k{cat.id}")


@menu_bp.post("/kategori/<int:cat_id>/tasi")
@login_required
def move_category(cat_id):
    cat = _cat(cat_id)
    cats = MenuCategory.query.filter_by(user_id=current_user.id).order_by(MenuCategory.sort, MenuCategory.id).all()
    i = cats.index(cat)
    j = i - 1 if request.form.get("yon") == "yukari" else i + 1
    if 0 <= j < len(cats):
        cats[i], cats[j] = cats[j], cats[i]
        for n, c in enumerate(cats):
            c.sort = (n + 1) * 10
        db.session.commit()
    return _back(f"k{cat.id}")


@menu_bp.post("/kategori/<int:cat_id>/sil")
@login_required
def delete_category(cat_id):
    cat = _cat(cat_id)
    for item in cat.items.all():
        menu.delete_image(item.image_id)
    name, n = cat.name, cat.items.count()
    db.session.delete(cat)
    db.session.commit()
    flash(f"{name} ve içindeki {n} ürün silindi.", "success")
    return _back()


@menu_bp.post("/kategori/<int:cat_id>/hizli")
@login_required
def quick_save(cat_id):
    """Kategorideki ürünlerin fiyat ve 'tükendi' durumunu toplu kaydet."""
    cat = _cat(cat_id)
    errors = 0
    for item in cat.items.all():
        raw = request.form.get(f"p{item.id}")
        if raw is None:
            continue
        try:
            item.price = menu.money(raw)
        except ValueError:
            errors += 1
        item.is_available = request.form.get(f"a{item.id}") == "1"
        item.is_active = request.form.get(f"v{item.id}") == "1"
    db.session.commit()
    flash("Bazı fiyatlar sayı olmadığı için kaydedilmedi." if errors else f"{cat.name} kaydedildi.",
          "warning" if errors else "success")
    return _back(f"k{cat.id}")


@menu_bp.route("/urun/yeni", methods=["GET", "POST"])
@menu_bp.route("/urun/<int:item_id>", methods=["GET", "POST"])
@login_required
def item_form(item_id=None):
    item = _item(item_id) if item_id else None
    cats = MenuCategory.query.filter_by(user_id=current_user.id).order_by(MenuCategory.sort, MenuCategory.id).all()
    if not cats:
        flash("Önce bir kategori ekle.", "warning")
        return _back()
    if request.method == "POST":
        form = request.form
        name = menu.clean(form.get("name"), 80)
        cat = _cat(form.get("category_id", type=int) or 0)
        error = None
        try:
            price = menu.money(form.get("price") or "0")
        except ValueError:
            price, error = None, "Fiyatı sayı olarak yaz (ör. 85 ya da 85,50)."
        if len(name) < 2:
            error = "Ürün adını yaz."
        options_json = None
        if not error:
            try:
                groups = menu.parse_options(form.get("options", ""))
                options_json = json.dumps(groups, ensure_ascii=False) if groups else None
            except ValueError as exc:
                error = str(exc)
        upload = request.files.get("photo")
        if not error and upload and upload.filename:
            try:
                new_image = menu.save_image(current_user, upload.stream)
            except ValueError as exc:
                error = str(exc)
            else:
                if item:
                    menu.delete_image(item.image_id)
                image_id = new_image.id
        else:
            image_id = item.image_id if item else None
        if error:
            db.session.rollback()
            return render_template("menu/item_form.html", item=item, cats=cats, form=form, error=error, tl=menu.tl,
                                   options_text=form.get("options", ""), all_groups=menu.categories(current_user)), 400
        if form.get("remove_photo") == "1" and not (upload and upload.filename):
            menu.delete_image(image_id)
            image_id = None
        if not item:
            item = MenuItem(user_id=current_user.id, sort=menu.next_sort(MenuItem, category_id=cat.id))
            db.session.add(item)
        elif item.category_id != cat.id:
            item.sort = menu.next_sort(MenuItem, category_id=cat.id)
        item.name, item.category_id, item.price, item.image_id = name, cat.id, price, image_id
        item.description = menu.clean(form.get("description"), 300) or None
        item.is_active = form.get("is_active") == "1"
        item.is_available = form.get("is_available") == "1"
        item.options = options_json
        others = [i for i in (form.getlist("apply_to", type=int) or []) if i != item.id]
        copied = 0
        if others:
            copied = (MenuItem.query.filter(MenuItem.user_id == current_user.id, MenuItem.id.in_(others))
                      .update({"options": options_json}, synchronize_session=False))
        db.session.commit()
        flash(f"{item.name} kaydedildi." + (f" Seçenekler {copied} ürüne daha uygulandı." if copied else ""), "success")
        return _back(f"k{cat.id}")
    form = {"category_id": request.args.get("kategori", type=int)} if not item else {}
    return render_template("menu/item_form.html", item=item, cats=cats, form=form, error=None, tl=menu.tl,
                           options_text=menu.options_text(item) if item else "", all_groups=menu.categories(current_user))


@menu_bp.post("/urun/<int:item_id>/sil")
@login_required
def delete_item(item_id):
    item = _item(item_id)
    cat_id, name = item.category_id, item.name
    menu.delete_image(item.image_id)
    db.session.delete(item)
    db.session.commit()
    flash(f"{name} silindi.", "success")
    return _back(f"k{cat_id}")


@menu_bp.post("/urun/<int:item_id>/tasi")
@login_required
def move_item(item_id):
    item = _item(item_id)
    siblings = item.category.items.all()
    i = siblings.index(item)
    j = i - 1 if request.form.get("yon") == "yukari" else i + 1
    if 0 <= j < len(siblings):
        siblings[i], siblings[j] = siblings[j], siblings[i]
        for n, it in enumerate(siblings):
            it.sort = (n + 1) * 10
        db.session.commit()
    return _back(f"k{item.category_id}")


@menu_bp.post("/ayarlar")
@login_required
def settings():
    setting = menu.get_setting(current_user, create=True)
    if request.form.get("action") == "adisyo_send":
        setting.adisyo_send = "accept" if request.form.get("value") == "accept" else "off"
        flash("Masa hesabı \"Ödeme alındı\" ile kapanınca siparişler Adisyo'ya tek sipariş olarak yazılacak."
              if setting.adisyo_send == "accept" else "Adisyo'ya yazma kapatıldı.", "success")
    elif request.form.get("action") == "calls":
        setting.calls_open = setting.calls_open is False
        flash("\"Garson çağır\" düğmesi " + ("açıldı." if setting.calls_open else "kapatıldı; müşteriler göremez."), "success")
    elif request.form.get("action") == "toggle":
        setting.ordering_open = not setting.ordering_open
        flash("Masadan sipariş alımı " + ("açıldı." if setting.ordering_open else "kapatıldı; menü sadece görüntülenir."),
              "success")
    else:
        setting.title = menu.clean(request.form.get("title"), 80) or setting.title
        setting.welcome = menu.clean(request.form.get("welcome"), 200) or None
        flash("Menü ayarları kaydedildi.", "success")
    db.session.commit()
    return redirect(request.form.get("next") if (request.form.get("next") or "").startswith("/panel/")
                    else url_for("menu.items"))


@menu_bp.post("/adisyo-aktar")
@login_required
def adisyo_import():
    from integrations.adisyo import AdisyoError
    from models import Integration
    integration = Integration.query.filter_by(user_id=current_user.id, platform="adisyo", is_active=True).first()
    connection = integration.adisyo_connection if integration else None
    if not connection:
        flash("Önce Adisyo bağlantısını kur (Yemek platformları → Adisyo).", "warning")
        return _back()
    try:
        data = menu.fetch_adisyo_products(connection)
        added, updated, skipped = menu.import_adisyo(current_user, data)
    except (AdisyoError, ValueError) as exc:
        db.session.rollback()
        flash(f"Adisyo'dan ürünler alınamadı: {exc}", "danger")
        return _back()
    msg = f"Adisyo'dan {added} yeni ürün eklendi, {updated} ürünün adı/fiyatı güncellendi."
    if skipped:
        msg += f" Satışta fiyatı olmayan {skipped} ürün atlandı."
    flash(msg + " Fotoğraf ve açıklamaları sen ekleyebilirsin.", "success")
    return _back()


def _tgo_store_id():
    from models import Integration
    intg = Integration.query.filter_by(user_id=current_user.id, platform="trendyolgo").first()
    return (intg.tgo_store_id or "").strip() if intg else ""


@menu_bp.post("/trendyol-aktar")
@login_required
def tgo_import():
    store_id = _tgo_store_id()
    if not store_id:
        flash("Önce Trendyol Go bağlantısını kur (Yemek platformları → Trendyol Go).", "warning")
        return _back()
    mode = request.form.get("mode", "media")
    try:
        data = menu.fetch_tgo_menu(store_id)
        if mode == "full":
            added, updated, images = menu.import_menu(current_user, data)
        else:
            matched, images, unmatched = menu.import_menu_media(current_user, data)
    except menu.MenuImportError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return _back()
    menu.attach_images_async(current_app._get_current_object(), current_user.id, images)
    if mode == "full":
        msg = f"Trendyol Go menüsünden {added} yeni ürün eklendi, {updated} ürünün fiyatı/açıklaması güncellendi."
    else:
        msg = f"Trendyol Go'daki ürünlerle {matched} menü ürünün eşleşti; fiyat ve ürünlere dokunulmadı."
        if unmatched:
            shown = ", ".join(unmatched[:12]) + (" …" if len(unmatched) > 12 else "")
            msg += f" Eşleşmeyen {len(unmatched)} Trendyol ürünü: {shown}."
    if images:
        msg += f" {len(images)} ürün görseli arka planda ekleniyor; 1-2 dakika sonra sayfayı yenile."
    flash(msg, "success")
    return _back()


# ── Panel: masalar ve QR ────────────────────────────────────────────────────

def _table(table_id):
    return MenuTable.query.filter_by(id=table_id, user_id=current_user.id).first_or_404()


@menu_bp.get("/masalar")
@login_required
def tables():
    setting = menu.get_setting(current_user, create=True)
    rows = MenuTable.query.filter_by(user_id=current_user.id).order_by(MenuTable.sort, MenuTable.id).all()
    return render_template("menu/tables.html", setting=setting, rows=rows,
                           adisyo_on=menu.adisyo_connection(current_user) is not None,
                           adisyo_rows=menu.saved_adisyo_tables(setting),
                           url=lambda t: url_for("menu_public.public_menu", code=t.code, _external=True))


@menu_bp.post("/masalar")
@login_required
def add_tables():
    prefix = menu.clean(request.form.get("prefix"), 30) or "Masa"
    start = max(1, min(500, request.form.get("start", type=int) or 1))
    end = max(start, min(start + 99, request.form.get("end", type=int) or start))
    added = menu.add_tables(current_user, prefix, start, end)
    flash(f"{added} masa eklendi." if added else "Bu adlarda masalar zaten var.", "success" if added else "warning")
    return redirect(url_for("menu.tables"))


@menu_bp.post("/masa/<int:table_id>/<action>")
@login_required
def table_action(table_id, action):
    table = _table(table_id)
    if action == "ad":
        name = menu.clean(request.form.get("name"), 40)
        if len(name) >= 1:
            table.name = name
    elif action == "yenile":
        table.code = menu._token(8, MenuTable, "code")
        flash(f"{table.name} için yeni QR oluşturuldu; eskisini yenisiyle değiştir.", "success")
    elif action == "sil":
        db.session.delete(table)
        flash(f"{table.name} silindi.", "success")
    else:
        abort(404)
    db.session.commit()
    return redirect(url_for("menu.tables"))


@menu_bp.post("/adisyo-masalar")
@login_required
def adisyo_tables():
    from integrations.adisyo import AdisyoError
    connection = menu.adisyo_connection(current_user)
    if not connection:
        flash("Önce Adisyo bağlantısını kur (Yemek platformları → Adisyo).", "warning")
        return redirect(url_for("menu.tables"))
    try:
        rows = menu.fetch_adisyo_tables(connection)
        matched, added = menu.sync_adisyo_tables(current_user, rows,
                                                 create_missing=request.form.get("action") == "create")
    except AdisyoError as exc:
        db.session.rollback()
        flash(f"Adisyo masaları alınamadı: {exc}", "danger")
        return redirect(url_for("menu.tables"))
    msg = f"Adisyo'da {len(rows)} masa bulundu. {matched} masa adıyla eşleşti"
    msg += f", {added} masa eklendi." if added else "."
    flash(msg + " Eşleşmeyenleri aşağıdan seçebilirsin.", "success")
    return redirect(url_for("menu.tables"))


@menu_bp.post("/masa/<int:table_id>/adisyo")
@login_required
def table_adisyo(table_id):
    table = _table(table_id)
    setting = menu.get_setting(current_user, create=True)
    value = request.form.get("adisyo_table_id", type=int)
    valid = {r["id"] for r in menu.saved_adisyo_tables(setting)}
    table.adisyo_table_id = value if value in valid else None
    db.session.commit()
    flash(f"{table.name} eşleştirmesi kaydedildi.", "success")
    return redirect(url_for("menu.tables") + f"#masa{table.id}")


@menu_bp.get("/masalar/yazdir")
@login_required
def print_tables():
    setting = menu.get_setting(current_user, create=True)
    ids = [int(x) for x in request.args.getlist("masa") if x.isdigit()]
    q = MenuTable.query.filter_by(user_id=current_user.id, is_active=True)
    if ids:
        q = q.filter(MenuTable.id.in_(ids))
    rows = q.order_by(MenuTable.sort, MenuTable.id).all()
    return render_template("menu/print.html", setting=setting, rows=rows,
                           url=lambda t: url_for("menu_public.public_menu", code=t.code, _external=True))

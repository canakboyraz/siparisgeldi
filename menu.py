"""QR menü ve masadan sipariş: kurallar ve yardımcılar.

- Her masanın kendine özel QR kodu var (/m/<masa kodu>). Okutan müşteri fotoğraflı menüyü görür,
  sepete ekler, en sona not yazar ve siparişi gönderir; sipariş panelde "Masa 3" olarak düşer.
- Fiyatlar her zaman sunucuda, menüdeki güncel fiyattan hesaplanır (telefondan gelen fiyata güvenilmez).
- Ödeme masada / kasada yapılır; sistem online ödeme almaz.
"""
import io
import logging
import secrets
import threading
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from flask import current_app

from extensions import db
from models import MenuCategory, MenuImage, MenuItem, MenuSetting, MenuTable, TableOrder, TableOrderLine

log = logging.getLogger("menu")

STATUS = {
    "new": ("Yeni", "red"),
    "preparing": ("Hazırlanıyor", "amber"),
    "served": ("Teslim edildi", "green"),
    "cancelled": ("İptal", "gray"),
}
CUSTOMER_LABEL = {"new": "Siparişin alındı", "preparing": "Hazırlanıyor", "served": "Masana geldi",
                  "cancelled": "İptal edildi"}
CUSTOMER_STATUS = {
    "new": "Birazdan hazırlanmaya başlayacak.",
    "preparing": "Siparişin hazırlanıyor.",
    "served": "Siparişin masana geldi. Afiyet olsun!",
    "cancelled": "Sipariş iptal edildi. Bir sorun varsa kasaya sorabilirsin.",
}
MAX_LINES, MAX_QTY = 30, 20
DEVICE_COOLDOWN = timedelta(seconds=20)
TABLE_LIMIT = (8, timedelta(minutes=10))     # bir masadan 10 dakikada en fazla 8 sipariş


class OrderError(Exception):
    pass


# ── Biçim ───────────────────────────────────────────────────────────────────

def money(value) -> Decimal:
    try:
        return Decimal(str(value).replace(" ", "").replace(",", ".")).quantize(Decimal("0.01"), ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError("geçersiz fiyat") from None


def tl(value) -> str:
    """85 -> '85 TL', 85.5 -> '85,50 TL', 1250 -> '1.250 TL'."""
    value = Decimal(value or 0).quantize(Decimal("0.01"))
    whole, frac = divmod(value, 1)
    text = f"{int(whole):,}".replace(",", ".")
    return f"{text},{int(frac * 100):02d} TL" if frac else f"{text} TL"


def clean(text, limit):
    return " ".join((text or "").split())[:limit]


# ── Ayar, masa ──────────────────────────────────────────────────────────────

def _token(n=10, model=None, field="token"):
    while True:
        token = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:n]
        if len(token) == n and not (model and model.query.filter(getattr(model, field) == token).first()):
            return token


def get_setting(user, create=False):
    setting = MenuSetting.query.filter_by(user_id=user.id).first()
    if not setting and create:
        setting = MenuSetting(user_id=user.id, token=_token(10, MenuSetting), title=(user.name or "")[:80])
        db.session.add(setting)
        db.session.commit()
    return setting


def add_tables(user, prefix, start, end):
    """'Masa', 1, 12 -> Masa 1 … Masa 12 (aynı adlı masa varsa atlanır)."""
    existing = {t.name.casefold() for t in MenuTable.query.filter_by(user_id=user.id)}
    sort = (db.session.query(db.func.max(MenuTable.sort)).filter_by(user_id=user.id).scalar() or 0)
    added = 0
    for n in range(start, end + 1):
        name = clean(f"{prefix} {n}", 40)
        if name.casefold() in existing:
            continue
        sort += 10
        db.session.add(MenuTable(user_id=user.id, name=name, code=_token(8, MenuTable, "code"), sort=sort))
        existing.add(name.casefold())
        added += 1
    db.session.commit()
    return added


# ── Menü ────────────────────────────────────────────────────────────────────

def next_sort(model, **filters):
    return (db.session.query(db.func.max(model.sort)).filter_by(**filters).scalar() or 0) + 10


def categories(user, public=False):
    q = MenuCategory.query.filter_by(user_id=user.id)
    if public:
        q = q.filter_by(is_active=True)
    out = []
    for cat in q.order_by(MenuCategory.sort, MenuCategory.id).all():
        items = cat.items.all()
        if public:
            items = [i for i in items if i.is_active]
            if not items:
                continue
        out.append((cat, items))
    return out


def save_image(user, stream):
    """Yüklenen fotoğrafı döndür, 1000 px'e küçült, WebP olarak kaydet. MenuImage döner."""
    from PIL import Image, ImageOps
    raw = stream.read(12 * 1024 * 1024 + 1)
    if len(raw) > 12 * 1024 * 1024:
        raise ValueError("Fotoğraf 12 MB'tan büyük olamaz.")
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
    except Exception:  # noqa: BLE001
        raise ValueError("Fotoğraf okunamadı; JPG, PNG ya da WebP yükle.") from None
    img = img.convert("RGB")
    img.thumbnail((1000, 1000))
    out = io.BytesIO()
    img.save(out, "WEBP", quality=80, method=4)
    image = MenuImage(user_id=user.id, data=out.getvalue(), mime="image/webp")
    db.session.add(image)
    db.session.flush()
    return image


def delete_image(image_id):
    if image_id:
        MenuImage.query.filter_by(id=image_id).delete()


# ── Sipariş ─────────────────────────────────────────────────────────────────

def create_order(table, payload, device):
    """payload: {"items": [{"id": 3, "qty": 2}], "note": "...", "name": "..."}"""
    user_id = table.user_id
    setting = MenuSetting.query.filter_by(user_id=user_id).first()
    if not setting or not setting.ordering_open:
        raise OrderError("Şu an menüden sipariş alınmıyor. Siparişini kasaya söyleyebilirsin.")
    raw = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(raw, list) or not raw:
        raise OrderError("Sepetin boş.")
    if len(raw) > MAX_LINES:
        raise OrderError("Bir siparişte en fazla 30 farklı ürün olabilir.")
    wanted = {}
    for row in raw:
        try:
            item_id, qty = int(row.get("id")), int(row.get("qty"))
        except (TypeError, ValueError, AttributeError):
            raise OrderError("Sepette geçersiz bir ürün var.") from None
        if qty < 1:
            continue
        wanted[item_id] = min(MAX_QTY, wanted.get(item_id, 0) + qty)
    if not wanted:
        raise OrderError("Sepetin boş.")
    items = {i.id: i for i in MenuItem.query.filter(MenuItem.user_id == user_id, MenuItem.id.in_(wanted)).all()}
    gone = [i.name for iid, i in items.items() if not (i.is_active and i.is_available and i.category.is_active)]
    if len(items) != len(wanted) or gone:
        names = ", ".join(gone) if gone else "bazı ürünler"
        raise OrderError(f"{names} şu an yok. Sepetini güncelleyip tekrar dene.")
    now = datetime.utcnow()
    if device:
        last = (TableOrder.query.filter_by(user_id=user_id, device=device)
                .order_by(TableOrder.id.desc()).first())
        if last and now - last.created_at < DEVICE_COOLDOWN:
            raise OrderError("Siparişin az önce gönderildi. Bir şey eklemek istersen birkaç saniye sonra tekrar dene.")
    recent = TableOrder.query.filter(TableOrder.table_id == table.id,
                                     TableOrder.created_at > now - TABLE_LIMIT[1]).count()
    if recent >= TABLE_LIMIT[0]:
        raise OrderError("Bu masadan çok sayıda sipariş geldi. Lütfen kasaya söyle.")
    order = TableOrder(user_id=user_id, table_id=table.id, table_name=table.name, status="new",
                       note=clean(payload.get("note"), 300) or None,
                       customer_name=clean(payload.get("name"), 40) or None, device=(device or "")[:32] or None)
    total = Decimal("0")
    for item_id, qty in wanted.items():
        item = items[item_id]
        price = Decimal(item.price or 0)
        total += price * qty
        order.lines.append(TableOrderLine(item_id=item.id, name=item.name, price=price, quantity=qty))
    order.total = total
    db.session.add(order)
    db.session.commit()
    notify_owner(order)
    return order


def set_status(order, status):
    if status not in STATUS:
        raise ValueError(status)
    order.status, order.updated_at = status, datetime.utcnow()
    db.session.commit()


def order_text(order) -> str:
    lines = [f"🍽 {order.table_name} · yeni sipariş"]
    lines += [f"{l.quantity}× {l.name}" for l in order.lines]
    if order.note:
        lines.append(f"Not: {order.note}")
    if order.customer_name:
        lines.append(f"Ad: {order.customer_name}")
    lines.append(f"Toplam: {tl(order.total)}")
    return "\n".join(lines)


def notify_owner(order):
    """Telegram bağlıysa sahibine kısa mesaj (arka planda; hata siparişi bozmasın)."""
    try:
        from models import User
        user = db.session.get(User, order.user_id)
        token = current_app.config.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = getattr(user, "telegram_chat_id", None)
        if not token or not chat_id or current_app.config.get("TESTING"):
            return
        from notifications import telegram
        text = order_text(order)
        threading.Thread(target=lambda: telegram.send_message(token, chat_id, text), daemon=True).start()
    except Exception:  # noqa: BLE001
        log.exception("[MENU] Telegram bildirimi gönderilemedi order=%s", order.id)


def order_json(order):
    label, tone = STATUS.get(order.status, (order.status, "gray"))
    return {
        "id": order.id, "table": order.table_name, "status": order.status, "label": label, "tone": tone,
        "note": order.note or "", "name": order.customer_name or "", "total": tl(order.total),
        "lines": [{"name": l.name, "qty": l.quantity, "price": tl(l.price)} for l in order.lines],
        "age": int((datetime.utcnow() - order.created_at).total_seconds()) if order.created_at else 0,
    }


# ── Adisyo'dan ürün aktarma ────────────────────────────────────────────────

def _adisyo_price(product):
    """Varsayılan birimin masa fiyatı (orderType 1); yoksa ilk aktif fiyat."""
    units = product.get("productUnits") or []
    unit = next((u for u in units if u.get("isDefault")), units[0] if units else None)
    if not unit:
        return None, None
    prices = unit.get("prices") or []
    active = [p for p in prices if p.get("isActive")]
    chosen = (next((p for p in active if p.get("orderType") == 1), None)
              or (active[0] if active else None))
    if not chosen:
        return None, unit.get("productUnitId")
    return chosen.get("price"), unit.get("productUnitId")


def fetch_adisyo_products(connection):
    import requests
    from integrations.adisyo import BASE_URL, AdisyoError, remote_message
    try:
        response = requests.get(
            current_app.config.get("ADISYO_API_BASE", BASE_URL).rstrip("/") + "/Products",
            headers={"x-api-key": connection.api_key, "x-api-secret": connection.api_secret,
                     "x-api-consumer": connection.consumer},
            timeout=(5, 25), allow_redirects=False)
    except requests.RequestException:
        raise AdisyoError("Adisyo bağlantısı kurulamadı.") from None
    if response.status_code != 200:
        raise AdisyoError(f"Adisyo HTTP {response.status_code}: {remote_message(response, connection)}")
    data = response.json()
    if not isinstance(data, dict) or str(data.get("status")) != "100" or not isinstance(data.get("data"), list):
        raise AdisyoError("Adisyo ürün listesi alınamadı; API yetkisini kontrol edin.")
    return data["data"]


def import_adisyo(user, categories_data):
    """Adisyo kategorileri/ürünleri menüye aktarır. Fotoğraf ve açıklamaya dokunmaz; ad ve fiyatı günceller.

    Dönüş: (eklenen, güncellenen, atlanan)."""
    added = updated = skipped = 0
    for cat_data in categories_data:
        cat_name = clean(str(cat_data.get("categoryName") or ""), 60) or "Diğer"
        cat_id = cat_data.get("categoryId")
        cat = (MenuCategory.query.filter_by(user_id=user.id, adisyo_category_id=cat_id).first() if cat_id else None) \
            or next((c for c in MenuCategory.query.filter_by(user_id=user.id) if c.name.casefold() == cat_name.casefold()), None)
        products = cat_data.get("products") or []
        if not cat:
            cat = MenuCategory(user_id=user.id, name=cat_name, adisyo_category_id=cat_id,
                               sort=next_sort(MenuCategory, user_id=user.id))
            db.session.add(cat)
            db.session.flush()
        elif cat_id and not cat.adisyo_category_id:
            cat.adisyo_category_id = cat_id
        for p in products:
            price, unit_id = _adisyo_price(p)
            name = clean(str(p.get("productName") or ""), 80)
            if price is None or not name:
                skipped += 1
                continue
            item = MenuItem.query.filter_by(user_id=user.id, adisyo_product_id=p.get("productId")).first() \
                if p.get("productId") else None
            if item:
                item.name, item.price, item.adisyo_unit_id = name, money(price), unit_id
                updated += 1
            else:
                db.session.add(MenuItem(user_id=user.id, category_id=cat.id, name=name, price=money(price),
                                        adisyo_product_id=p.get("productId"), adisyo_unit_id=unit_id,
                                        sort=next_sort(MenuItem, category_id=cat.id) + added * 10))
                added += 1
    setting = get_setting(user, create=True)
    setting.adisyo_synced_at = datetime.utcnow()
    db.session.commit()
    return added, updated, skipped


# ── Adisyo'ya masa siparişi yazma (açık hesap) ─────────────────────────────

ADISYO_OK = "100"
ADISYO_DUPLICATE = "713"     # aynı WebOrderId daha önce kaydedilmiş


def adisyo_connection(user):
    from models import Integration
    integration = Integration.query.filter_by(user_id=user.id, platform="adisyo", is_active=True).first()
    return integration.adisyo_connection if integration else None


def _adisyo_call(connection, method, path, payload=None):
    import requests
    from integrations.adisyo import BASE_URL, AdisyoError, remote_message
    url = current_app.config.get("ADISYO_API_BASE", BASE_URL).rstrip("/") + path
    headers = {"x-api-key": connection.api_key, "x-api-secret": connection.api_secret,
               "x-api-consumer": connection.consumer}
    try:
        response = requests.request(method, url, headers=headers, json=payload, timeout=(5, 20),
                                    allow_redirects=False)
    except requests.Timeout:
        raise AdisyoError("Adisyo zamanında yanıt vermedi.") from None
    except requests.RequestException:
        raise AdisyoError("Adisyo bağlantısı kurulamadı.") from None
    try:
        data = response.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise AdisyoError(f"Adisyo HTTP {response.status_code}: {remote_message(response, connection)}")
    return data


def _norm_name(text):
    return " ".join(str(text or "").replace("-", " ").split()).casefold()


def fetch_adisyo_tables(connection):
    """Adisyo'daki bölge ve masalar → [{"id", "name", "area"}]."""
    from integrations.adisyo import AdisyoError
    data = _adisyo_call(connection, "GET", "/AreasWithTables")
    if str(data.get("status")) != ADISYO_OK or not isinstance(data.get("data"), list):
        raise AdisyoError(f"Adisyo masa listesi alınamadı ({data.get('status')}: {clean(str(data.get('message') or ''), 80)}).")
    rows = []
    for area in data["data"]:
        for t in (area.get("tables") or []):
            if isinstance(t.get("id"), int) and t.get("name"):
                rows.append({"id": t["id"], "name": clean(str(t["name"]), 40), "area": clean(str(area.get("name") or ""), 40)})
    return rows


def saved_adisyo_tables(setting):
    import json
    try:
        return json.loads(setting.adisyo_tables or "[]")
    except ValueError:
        return []


def sync_adisyo_tables(user, adisyo_rows, create_missing=False):
    """Masa listesini kaydeder, aynı adlı masaları eşleştirir; istenirse eksik masaları oluşturur.

    Dönüş: (eşleşen, eklenen)."""
    import json
    setting = get_setting(user, create=True)
    setting.adisyo_tables = json.dumps(adisyo_rows, ensure_ascii=False)
    tables = MenuTable.query.filter_by(user_id=user.id).order_by(MenuTable.sort, MenuTable.id).all()
    used = {t.adisyo_table_id for t in tables if t.adisyo_table_id}
    by_name = {}
    for row in adisyo_rows:
        by_name.setdefault(_norm_name(row["name"]), row)
    matched = added = 0
    for t in tables:
        row = by_name.get(_norm_name(t.name))
        if not t.adisyo_table_id and row and row["id"] not in used:
            t.adisyo_table_id = row["id"]
            used.add(row["id"])
            matched += 1
    if create_missing:
        names = {_norm_name(t.name) for t in tables}
        sort = next_sort(MenuTable, user_id=user.id)
        for row in adisyo_rows:
            if row["id"] in used or _norm_name(row["name"]) in names:
                continue
            db.session.add(MenuTable(user_id=user.id, name=row["name"], code=_token(8, MenuTable, "code"),
                                     sort=sort + added * 10, adisyo_table_id=row["id"]))
            used.add(row["id"])
            added += 1
    db.session.commit()
    return matched, added


def adisyo_payload(order, table):
    from integrations.adisyo import AdisyoError
    items = {i.id: i for i in MenuItem.query.filter(
        MenuItem.user_id == order.user_id, MenuItem.id.in_([l.item_id for l in order.lines if l.item_id]))}
    details, missing = [], []
    for line in order.lines:
        item = items.get(line.item_id)
        if not item or not item.adisyo_unit_id:
            missing.append(line.name)
            continue
        details.append({"ProductUnitId": item.adisyo_unit_id, "Quantity": line.quantity,
                        "Name": line.name, "IsMenu": False})
    if missing:
        raise AdisyoError("Adisyo'da karşılığı olmayan ürün: " + ", ".join(missing[:4])
                          + ". Ürünü Adisyo'dan aktar ya da Adisyo'ya elle gir.")
    note = f"QR menü · {order.table_name}"
    if order.customer_name:
        note += f" · {order.customer_name}"
    if order.note:
        note += f" · Not: {order.note}"
    return {
        "CustomerName": order.customer_name or order.table_name, "CustomerSurname": "",
        "CustomerId": f"sg-masa-{order.table_id or 0}", "CustomerPhone": "", "CustomerPhone2": "",
        "Address": "", "AddressDescription": "", "Region": "", "City": "",
        "PaymentNote": "QR menü · ödeme kasada", "Discount": 0,
        "OrderNote": note[:300], "WebOrderId": f"sg-qr-{order.id}",
        "OrderTotal": float(order.total), "TableId": table.adisyo_table_id,
        "DeliveryFee": 0, "ServiceCharge": 0, "OrderDetails": details,
    }


def send_to_adisyo(order):
    """Siparişi Adisyo'da masanın hesabına yazar. Aynı sipariş iki kez gönderilmez.

    Dönüş: (ok, mesaj)."""
    from integrations.adisyo import AdisyoError
    if order.adisyo_state == "sent":
        return True, "Bu sipariş zaten Adisyo'da."
    if order.status == "cancelled":
        return False, "İptal edilen sipariş Adisyo'ya gönderilmez."
    from models import User
    owner = db.session.get(User, order.user_id)
    connection = adisyo_connection(owner)
    table = db.session.get(MenuTable, order.table_id) if order.table_id else None
    if not connection:
        return False, "Adisyo bağlantısı yok."
    if not table or not table.adisyo_table_id:
        return False, f"{order.table_name} Adisyo'daki bir masayla eşleşmemiş (Masalar ve QR → Adisyo eşleştirme)."
    # Çift tıklama / iki sekme: sadece bir istek gönderilsin
    claimed = (TableOrder.query.filter(TableOrder.id == order.id,
                                       db.or_(TableOrder.adisyo_state.is_(None), TableOrder.adisyo_state == "error"))
               .update({"adisyo_state": "sending"}, synchronize_session=False))
    db.session.commit()
    if not claimed:
        db.session.refresh(order)
        return order.adisyo_state == "sent", "Sipariş şu an Adisyo'ya gönderiliyor."
    db.session.refresh(order)
    try:
        data = _adisyo_call(connection, "POST", "/SaveOrder", adisyo_payload(order, table))
        code = str(data.get("status"))
        if code not in (ADISYO_OK, ADISYO_DUPLICATE):
            raise AdisyoError(f"Adisyo kaydetmedi ({code}: {clean(str(data.get('message') or ''), 120)})")
    except AdisyoError as exc:
        order.adisyo_state, order.adisyo_error = "error", clean(str(exc), 200)
        db.session.commit()
        log.warning("Adisyo SaveOrder hatası order=%s: %s", order.id, exc)
        return False, order.adisyo_error
    order.adisyo_state, order.adisyo_error, order.adisyo_sent_at = "sent", None, datetime.utcnow()
    order.adisyo_order_id = str(data.get("orderId") or "")[:40] or None
    db.session.commit()
    return True, f"{order.table_name} siparişi Adisyo'da masanın hesabına eklendi."

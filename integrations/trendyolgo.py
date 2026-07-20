"""TrendyolGo API istemcisi — çok kullanıcılı.

Kanıtlanmış tek-kullanıcılı bottan uyarlanmıştır (auth başlığı, endpoint'ler,
mesaj formatları). Her çağrı kullanıcının kendi credential'larıyla yapılır.
"""
import base64
import requests

PROD_BASE = "https://api.tgoapis.com"

# Yeni sipariş için tam detay bildirimi verilecek statüler
NEW_ORDER_STATUSES = {"Created", "Picking"}
# Kısa statü-değişim bildirimi verilecek statüler
STATUS_NOTIFY = {"Picking", "Invoiced", "Shipped", "Delivered", "Cancelled", "UnSupplied"}


def _headers(supplier_id: str, api_key: str, api_secret: str) -> dict:
    cred = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
    return {
        "Authorization": f"Basic {cred}",
        "User-Agent": f"{supplier_id} - SelfIntegration",
        "x-agentname": "SiparisGeldi",
        "x-executor-user": "integration@siparisgeldi.net",
        "Content-Type": "application/json",
    }


def test_connection(supplier_id: str, api_key: str, api_secret: str):
    """API bağlantısını test eder. (ok: bool, mesaj: str, stores: list) döner."""
    url = f"{PROD_BASE}/integrator/store/meal/suppliers/{supplier_id}/stores"
    try:
        r = requests.get(url, headers=_headers(supplier_id, api_key, api_secret),
                         params={"page": 0, "size": 10}, timeout=15)
        if r.status_code == 401:
            return False, "API bilgileri hatalı. Supplier ID, API Key ve Secret'ı kontrol edin.", []
        r.raise_for_status()
        stores = r.json().get("restaurants", [])
        return True, f"{len(stores)} restoran bulundu.", stores
    except requests.exceptions.RequestException as e:
        return False, f"Bağlantı hatası: {e}", []


def get_orders(supplier_id: str, api_key: str, api_secret: str,
               statuses="Created,Picking,Invoiced,Shipped") -> list:
    """Aktif siparişleri çeker. Hata olursa boş liste döner."""
    url = f"{PROD_BASE}/integrator/order/meal/suppliers/{supplier_id}/packages"
    r = requests.get(url, headers=_headers(supplier_id, api_key, api_secret),
                     params={"packageStatuses": statuses, "page": 0, "size": 50},
                     timeout=15)
    r.raise_for_status()
    return r.json().get("content", [])


# ── Mesaj formatlama ────────────────────────────────────────────────────────

def summarize_items(order: dict, max_items: int = 4) -> str:
    """Sipariş satırlarını WhatsApp şablonuna sığacak şekilde detaylı özetler."""
    lines = order.get("lines") or []
    parts = []
    for ln in lines[:max_items]:
        qty = _line_quantity(ln)
        item = f"{ln.get('name', '?')} x{qty}"
        details = _line_detail_parts(ln)
        if details:
            item += " (" + "; ".join(details) + ")"
        parts.append(item)
    s = ", ".join(parts) if parts else "-"
    more = len(lines) - max_items
    if more > 0:
        s += f" +{more} urun"
    note = order.get("customerNote", "") or ""
    if note:
        s += f" | Siparis notu: {note}"
    return s[:900]


def _clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _line_quantity(line: dict) -> int:
    for key in ("quantity", "amount", "count"):
        value = line.get(key)
        if isinstance(value, (int, float)) and value:
            return int(value)
    return len(line.get("items", []) or []) or 1


def _name_from_dict(data: dict) -> str:
    for key in ("name", "productName", "itemName", "title"):
        value = _clean_text(data.get(key))
        if value:
            return value
    return ""


def _note_parts(data: dict) -> list:
    parts = []
    for key, label in (
        ("note", "Not"),
        ("productNote", "Urun notu"),
        ("specialNote", "Ozel not"),
    ):
        value = _clean_text(data.get(key))
        if value:
            parts.append(f"{label}: {value}")
    return parts


def _modifier_parts(modifiers) -> list:
    parts = []
    for modifier in modifiers or []:
        if not isinstance(modifier, dict):
            name = _clean_text(modifier)
            if name:
                parts.append(name)
            continue

        name = _name_from_dict(modifier)
        if not name:
            continue

        group = _clean_text(
            modifier.get("groupName")
            or modifier.get("categoryName")
            or modifier.get("headerName")
            or modifier.get("modifierGroupName")
        )
        qty = modifier.get("quantity") or modifier.get("amount") or modifier.get("count")
        suffix = f" x{int(qty)}" if isinstance(qty, (int, float)) and qty and qty != 1 else ""
        removed = any(bool(modifier.get(k)) for k in ("excluded", "removed", "isRemoved", "isExcluded"))

        if removed:
            parts.append(f"Cikarilacak: {name}{suffix}")
        elif group and group != name:
            parts.append(f"{group}: {name}{suffix}")
        else:
            parts.append(f"{name}{suffix}")

        for child_key in ("subOptions", "subItems", "children", "modifierProducts", "options"):
            parts.extend(_modifier_parts(modifier.get(child_key)))
    return parts


def _line_detail_parts(line: dict) -> list:
    parts = []
    parts.extend(_note_parts(line))
    for key in (
        "modifierProducts",
        "options",
        "optionProducts",
        "removedIngredients",
        "excludedProducts",
        "extraIngredients",
        "ingredients",
    ):
        parts.extend(_modifier_parts(line.get(key)))

    for item in line.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        item_name = _name_from_dict(item)
        if item_name and item_name != line.get("name"):
            parts.append(item_name)
        parts.extend(_note_parts(item))
        for key in (
            "modifierProducts",
            "options",
            "optionProducts",
            "removedIngredients",
            "excludedProducts",
            "extraIngredients",
            "ingredients",
        ):
            parts.extend(_modifier_parts(item.get(key)))

    unique = []
    seen = set()
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            unique.append(part)
    return unique


def format_new_order_message(order: dict) -> str:
    order_number = order.get("orderNumber", "N/A")
    order_code   = order.get("orderCode", "N/A")
    total_price  = order.get("totalPrice", 0) or 0
    eta          = order.get("eta", "-")
    note         = order.get("customerNote", "") or ""
    app_raw      = (order.get("userInformation") or {}).get("appName", "")
    app_map      = {"Trendyol": "Trendyol", "TrendyolGo": "Trendyol Go", "Galaxy": "Getir Yemek"}
    app          = app_map.get(app_raw, app_raw or "-")

    payment   = order.get("payment", {}) or {}
    pay_raw   = payment.get("paymentType", "")
    pay_map   = {"PAY_WITH_CARD": "💳 Online Kart",
                 "PAY_WITH_ON_DELIVERY": "🚪 Kapıda Ödeme",
                 "PAY_WITH_MEAL_CARD": "🍽️ Yemek Kartı"}
    pay_label = pay_map.get(pay_raw, pay_raw or "-")

    delivery_map = {"GO": "🛵 TGo Kuryesi", "STORE": "🏪 Restoran Kuryesi"}
    delivery     = delivery_map.get(order.get("deliveryType", ""), "-")

    items_text = ""
    for ln in order.get("lines", []):
        qty = _line_quantity(ln)
        items_text += f"  • {ln.get('name', '?')} x{qty}\n"
        for detail in _line_detail_parts(ln):
            if detail.startswith("Cikarilacak:"):
                items_text += f"    ❌ {detail.replace('Cikarilacak:', 'Çıkarılacak:', 1)}\n"
            elif detail.startswith("Urun notu:"):
                items_text += f"    📝 {detail.replace('Urun notu:', 'Ürün notu:', 1)}\n"
            elif detail.startswith("Not:") or detail.startswith("Ozel not:"):
                items_text += f"    📝 {detail.replace('Ozel not:', 'Özel not:', 1)}\n"
            else:
                items_text += f"    ↳ {detail}\n"
    if not items_text:
        items_text = "  (Ürün bilgisi yok)\n"

    msg = (
        f"🆕 <b>YENİ SİPARİŞ — Trendyol Go</b>\n"
        f"{'━'*28}\n"
        f"📋 <b>Sipariş No:</b> #{order_number}\n"
        f"🔑 <b>Kod:</b> {order_code}\n"
        f"📱 <b>Kaynak:</b> {app}\n"
        f"{'━'*28}\n"
        f"🛍️ <b>Ürünler:</b>\n{items_text}"
        f"{'━'*28}\n"
        f"💰 <b>Toplam:</b> {total_price:.2f} ₺\n"
        f"💳 <b>Ödeme:</b> {pay_label}\n"
        f"🚀 <b>Teslimat:</b> {delivery}\n"
        f"⏱️ <b>Süre:</b> {eta}\n"
    )
    if note:
        msg += f"📝 <b>Not:</b> {note}\n"
    return msg


def format_status_message(order: dict, new_status: str) -> str:
    order_number = order.get("orderNumber", "N/A")
    total_price  = order.get("totalPrice", 0) or 0

    status_map = {
        "Picking":    ("✅", "SİPARİŞ KABUL EDİLDİ",  "Restoran hazırlamaya başladı."),
        "Invoiced":   ("👨‍🍳", "SİPARİŞ HAZIRLANDI",   "Kurye bekleniyor."),
        "Shipped":    ("🛵", "SİPARİŞ YOLA ÇIKTI",    "Kurye teslimatta."),
        "Delivered":  ("🎉", "TESLİM EDİLDİ",         "Sipariş müşteriye ulaştı."),
        "Cancelled":  ("❌", "SİPARİŞ İPTAL EDİLDİ",  ""),
        "UnSupplied": ("🚫", "RESTORAN İPTAL ETTİ",   ""),
    }
    emoji, title, desc = status_map.get(new_status, ("ℹ️", new_status, ""))

    msg = (
        f"{emoji} <b>{title}</b>\n"
        f"{'━'*28}\n"
        f"📋 <b>Sipariş No:</b> #{order_number}\n"
        f"💰 <b>Tutar:</b> {total_price:.2f} ₺\n"
    )
    if desc:
        msg += f"ℹ️ {desc}\n"

    cancel_info = order.get("cancelInfo") or {}
    reason_code = cancel_info.get("reasonCode")
    reason_map  = {621: "Tedarik problemi", 622: "Mağaza kapalı", 623: "Hazırlayamıyor",
                   624: "Yüksek yoğunluk", 625: "Kabul edilmedi", 626: "Alan dışı",
                   627: "Sipariş karışıklığı", 604: "Müşteri iptal etti", 605: "Sipariş gecikti"}
    if reason_code and new_status in ("Cancelled", "UnSupplied"):
        msg += f"📌 <b>Neden:</b> {reason_map.get(reason_code, f'Kod: {reason_code}')}\n"
    return msg

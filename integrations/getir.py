"""Getir Yemek helpers for webhook payloads and API calls."""
import html

import requests


DEFAULT_BASE = "https://food-external-api-gateway.getirapi.com"
TEST_BASE = "https://food-external-api-gateway.development.getirapi.com"

STATUS_MAP = {
    325: "Scheduled",
    350: "ScheduledApproved",
    400: "New",
    500: "Picking",
    550: "Prepared",
    600: "Shipped",
    700: "Shipped",
    800: "OnDelivery",
    900: "Delivered",
    1500: "AdminCancelled",
    1600: "AutoCancelled",
}

PAYMENT_MAP = {
    1: "Masterpass",
    2: "BKM",
    3: "Kredi / Banka Kartı",
    4: "Nakit",
    5: "Multinet Kart",
    6: "Sodexo Kart",
    7: "Sodexo Çeki",
    8: "Ticket Kart",
    9: "Ticket Çeki",
    10: "Setcard Kart",
    11: "Metropol Kart",
    12: "Paye Kart",
    15: "MobileExpress",
    16: "Getir Finance",
    17: "Sodexo Pass Mobil Uygulama",
    19: "Sodexo Online",
    21: "Token Flex",
    22: "Ticket Online Ödeme",
    24: "Multinet Online Ödeme",
    26: "Online Ödeme",
    27: "Multinet QR Kod",
    28: "Ticket Restaurant QR Kod",
    29: "Setcard QR Kod",
    30: "Metropol QR Kod",
    31: "Paye QR Kod",
    32: "TokenFlex QR Kod",
}


def _clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _first(data: dict, *keys):
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _nested(data: dict, *keys):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def status_code(payload: dict):
    return _as_int(_first(payload, "status", "statusCode", "orderStatus", "orderStatusCode"))


def status_value(payload: dict) -> str:
    code = status_code(payload)
    if code in STATUS_MAP:
        return STATUS_MAP[code]
    raw = _first(payload, "statusText", "statusName", "status")
    return _clean(raw) or "New"


def order_id(payload: dict) -> str:
    return _clean(_first(payload, "_id", "id", "orderId", "foodOrderId"))


def order_number(payload: dict) -> str:
    return _clean(_first(payload, "confirmationId", "orderNumber", "orderNo", "checkoutId")) or order_id(payload)


def restaurant_id(payload: dict) -> str:
    restaurant = payload.get("restaurant") or payload.get("restaurantInfo") or {}
    return _clean(
        _first(payload, "restaurantId", "restaurant_id")
        or _first(restaurant, "_id", "id", "restaurantId")
    )


def restaurant_name(payload: dict) -> str:
    restaurant = payload.get("restaurant") or payload.get("restaurantInfo") or {}
    return _clean(_first(payload, "restaurantName") or _first(restaurant, "name", "restaurantName"))


def restaurant_secret_key(payload: dict) -> str:
    restaurant = payload.get("restaurant") or payload.get("restaurantInfo") or {}
    return _clean(
        _first(payload, "restaurantSecretKey", "restaurant_secret_key")
        or _first(restaurant, "restaurantSecretKey", "secretKey")
    )


def _walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def restaurant_info_from_login_response(payload: dict) -> dict:
    """Getir test/canli cevaplarinda restoran bilgisi farkli seviyelerde gelebilir."""
    if not isinstance(payload, dict):
        return {}
    for data in _walk_dicts(payload):
        rid = restaurant_id(data)
        name = restaurant_name(data)
        if rid or name:
            return {"restaurant_id": rid, "restaurant_name": name}
    return {}


def total_price(payload: dict) -> float:
    value = _first(payload, "totalDiscountedPrice", "totalPrice", "total", "price")
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def payment_label(payload: dict) -> str:
    text = _first(payload, "paymentMethodText", "paymentText", "paymentMethodName")
    if isinstance(text, dict):
        text = text.get("tr") or text.get("en")
    if text:
        return _clean(text)
    method = _as_int(_first(payload, "paymentMethod", "paymentType"))
    return PAYMENT_MAP.get(method, _clean(method) or "-")


def delivery_label(payload: dict) -> str:
    delivery_type = _as_int(_first(payload, "deliveryType", "deliveryProvider"))
    if delivery_type == 1:
        return "Getir Kuryesi"
    if delivery_type == 2:
        return "Restoran Kuryesi"
    return _clean(_first(payload, "deliveryTypeText", "deliveryType")) or "-"


def customer_name(payload: dict) -> str:
    client = payload.get("client") or payload.get("customer") or {}
    return _clean(
        _first(payload, "clientName", "customerName")
        or _first(client, "name", "fullName")
    )


def customer_note(payload: dict) -> str:
    return _clean(_first(payload, "clientNote", "customerNote", "note", "checkoutNote"))


def address_text(payload: dict) -> str:
    address = payload.get("deliveryAddress") or payload.get("address") or {}
    if isinstance(address, str):
        return _clean(address)
    if not isinstance(address, dict):
        return ""
    for key in ("fullAddress", "address", "description", "text"):
        if address.get(key):
            return _clean(address.get(key))
    parts = [
        address.get("neighborhood"),
        address.get("street"),
        address.get("buildingNo"),
        address.get("floor"),
        address.get("doorNo") or address.get("doorNumber"),
        address.get("district"),
        address.get("city"),
    ]
    return " ".join(_clean(part) for part in parts if _clean(part))


def address_direction(payload: dict) -> str:
    address = payload.get("deliveryAddress") or payload.get("address") or {}
    if not isinstance(address, dict):
        return ""
    return _clean(_first(address, "directions", "direction", "description"))


def products(payload: dict) -> list:
    for key in ("products", "items", "lines"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def product_name(item: dict) -> str:
    product = item.get("product") if isinstance(item.get("product"), dict) else {}
    return _clean(_first(item, "name", "productName", "displayName") or _first(product, "name", "productName")) or "Ürün"


def product_id(item: dict) -> str:
    product = item.get("product") if isinstance(item.get("product"), dict) else {}
    return _clean(_first(item, "productId", "_id", "id") or _first(product, "_id", "id"))


def product_quantity(item: dict) -> int:
    qty = _first(item, "count", "quantity", "amount")
    try:
        return int(qty or 1)
    except (TypeError, ValueError):
        return 1


def _option_parts(value) -> list:
    parts = []
    if isinstance(value, dict):
        name = _clean(_first(value, "name", "optionName", "productName", "title"))
        qty = _first(value, "count", "quantity", "amount")
        if name:
            suffix = f" x{int(qty)}" if isinstance(qty, (int, float)) and qty not in (0, 1) else ""
            parts.append(f"{name}{suffix}")
        for key in ("options", "optionProducts", "subOptions", "children", "items"):
            parts.extend(_option_parts(value.get(key)))
    elif isinstance(value, list):
        for item in value:
            parts.extend(_option_parts(item))
    elif value:
        parts.append(_clean(value))
    return parts


def item_detail_parts(item: dict) -> list:
    parts = []
    note = _clean(_first(item, "note", "productNote", "clientNote"))
    if note:
        parts.append(f"Ürün notu: {note}")
    for key in ("optionCategories", "options", "optionProducts", "ingredients", "removedIngredients"):
        parts.extend(_option_parts(item.get(key)))
    unique = []
    seen = set()
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            unique.append(part)
    return unique


def extract_order_fields(payload: dict) -> dict:
    return {
        "external_id": order_id(payload),
        "order_number": order_number(payload),
        "status": status_value(payload),
        "total_price": total_price(payload),
        "payment_type": payment_label(payload),
        "app_source": "Getir Yemek",
        "customer_note": customer_note(payload),
    }


def summarize_items(payload: dict, max_items: int = 4) -> str:
    parts = []
    for item in products(payload)[:max_items]:
        if not isinstance(item, dict):
            continue
        text = f"{product_name(item)} x{product_quantity(item)}"
        details = item_detail_parts(item)
        if details:
            text += " (" + "; ".join(details[:4]) + ")"
        parts.append(text)
    result = ", ".join(parts) if parts else "-"
    more = len(products(payload)) - max_items
    if more > 0:
        result += f" +{more} ürün"
    note = customer_note(payload)
    if note:
        result += f" | Sipariş notu: {note}"
    return result[:900]


def format_order_created(payload: dict) -> str:
    items_text = ""
    for item in products(payload):
        if not isinstance(item, dict):
            continue
        items_text += f"  • {html.escape(product_name(item))} x{product_quantity(item)}\n"
        for detail in item_detail_parts(item):
            items_text += f"    ↳ {html.escape(detail)}\n"
    if not items_text:
        items_text = "  (Ürün bilgisi yok)\n"

    msg = (
        "🆕 <b>YENİ SİPARİŞ — Getir Yemek</b>\n"
        f"{'━'*28}\n"
        f"📋 <b>Sipariş No:</b> #{html.escape(order_number(payload) or '-')}\n"
        f"🏪 <b>Şube:</b> {html.escape(restaurant_name(payload) or '-')}\n"
        f"👤 <b>Müşteri:</b> {html.escape(customer_name(payload) or '-')}\n"
        f"{'━'*28}\n"
        f"🛍️ <b>Ürünler:</b>\n{items_text}"
        f"{'━'*28}\n"
        f"💰 <b>Tutar:</b> {total_price(payload):.2f} TL\n"
        f"💳 <b>Ödeme:</b> {html.escape(payment_label(payload))}\n"
        f"🚀 <b>Teslimat:</b> {html.escape(delivery_label(payload))}\n"
    )
    address = address_text(payload)
    if address:
        msg += f"📍 <b>Adres:</b> {html.escape(address)}\n"
    note = customer_note(payload)
    if note:
        msg += f"🗒️ <b>Not:</b> {html.escape(note)}\n"
    return msg


def format_order_canceled(payload: dict, original_payload: dict = None) -> str:
    source = original_payload or payload
    reason = _clean(
        _first(payload, "cancelNote", "cancelReason", "cancelReasonText")
        or _nested(payload, "cancelReason", "message")
        or _nested(payload, "cancelReason", "name")
    )
    msg = (
        "❌ <b>SİPARİŞ İPTAL EDİLDİ — Getir Yemek</b>\n"
        f"{'━'*28}\n"
        f"📋 <b>Sipariş No:</b> #{html.escape(order_number(source) or order_id(payload) or '-')}\n"
        f"💰 <b>Tutar:</b> {total_price(source):.2f} TL\n"
    )
    if reason:
        msg += f"📌 <b>Neden:</b> {html.escape(reason)}\n"
    else:
        msg += "ℹ️ Sipariş iptal/reddedildi.\n"
    return msg


def format_courier_status(payload: dict) -> str:
    status = _clean(_first(payload, "courierStatus", "courierStatusText", "status"))
    pickup = payload.get("pickup") if isinstance(payload.get("pickup"), dict) else {}
    pickup_min = _clean(pickup.get("min"))
    pickup_max = _clean(pickup.get("max"))
    eta = _clean(_first(payload, "eta", "courierEta", "arrivalTime", "calculationDate"))
    msg = (
        "🚚 <b>GETİR KURYE DURUMU</b>\n"
        f"{'━'*28}\n"
        f"📋 <b>Sipariş No:</b> #{html.escape(order_number(payload) or order_id(payload) or '-')}\n"
        f"ℹ️ <b>Durum:</b> {html.escape(status or 'Kurye durumu güncellendi')}\n"
    )
    if pickup_min or pickup_max:
        msg += f"Kurye restorana varış: {html.escape(pickup_min or '-')} - {html.escape(pickup_max or '-')}\n"
    if eta:
        msg += f"⏱️ <b>Tahmini varış:</b> {html.escape(eta)}\n"
    return msg


def format_restaurant_status(payload: dict) -> str:
    status = _clean(_first(payload, "status", "restaurantStatus", "posStatus"))
    return (
        "🏪 <b>GETİR RESTORAN DURUMU</b>\n"
        f"{'━'*28}\n"
        f"🏪 <b>Şube:</b> {html.escape(restaurant_name(payload) or restaurant_id(payload) or '-')}\n"
        f"ℹ️ <b>Durum:</b> {html.escape(status or 'Durum güncellendi')}\n"
    )


def api_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def login(app_secret_key: str, restaurant_secret_key: str, base_url: str = None):
    base = (base_url or DEFAULT_BASE).rstrip("/")
    payload = {"appSecretKey": app_secret_key, "restaurantSecretKey": restaurant_secret_key}
    response = requests.post(f"{base}/auth/login", json=payload, timeout=15)
    response.raise_for_status()
    return response.json()

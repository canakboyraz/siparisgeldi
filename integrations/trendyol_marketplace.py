"""Trendyol Pazaryeri order polling helpers."""
import base64
import html
import re
from datetime import datetime, timedelta

import requests


DEFAULT_BASE = "https://apigw.trendyol.com/integration"
STAGE_BASE = "https://stageapigw.trendyol.com/integration"
PLATFORM = "trendyol_marketplace"

STATUS_NOTIFY = {
    "Picking",
    "Invoiced",
    "Shipped",
    "Delivered",
    "Cancelled",
    "UnDelivered",
    "UnSupplied",
    "Returned",
    "Refunded",
    "AtCollectionPoint",
    "UnPacked",
}

STATUS_ALIASES = {
    "CREATED": "Created",
    "PICKING": "Picking",
    "INVOICED": "Invoiced",
    "SHIPPED": "Shipped",
    "CANCELLED": "Cancelled",
    "DELIVERED": "Delivered",
    "UNDELIVERED": "UnDelivered",
    "RETURNED": "Returned",
    "UNSUPPLIED": "UnSupplied",
    "AWAITING": "Awaiting",
    "UNPACKED": "UnPacked",
    "AT_COLLECTION_POINT": "AtCollectionPoint",
    "VERIFIED": "Verified",
}


def auth_token(api_key: str, api_secret: str) -> str:
    raw = f"{api_key}:{api_secret}".encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _headers(supplier_id: str, api_key: str, api_secret: str) -> dict:
    return {
        "Authorization": f"Basic {auth_token(api_key, api_secret)}",
        "Content-Type": "application/json",
        "User-Agent": f"{supplier_id} - SelfIntegration",
    }


def _request(path: str, supplier_id: str, api_key: str, api_secret: str,
             base_url: str = DEFAULT_BASE, params: dict = None):
    response = requests.get(
        f"{(base_url or DEFAULT_BASE).rstrip('/')}{path}",
        headers=_headers(supplier_id, api_key, api_secret),
        params=params or {},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def get_orders(supplier_id: str, api_key: str, api_secret: str,
               base_url: str = DEFAULT_BASE, days_back: int = 7, size: int = 200,
               since: datetime = None) -> list:
    end = datetime.utcnow()
    start = since or (end - timedelta(days=days_back))
    params = {
        "startDate": int(start.timestamp() * 1000),
        "endDate": int(end.timestamp() * 1000),
        "orderByField": "PackageLastModifiedDate",
        "orderByDirection": "DESC",
        "size": size,
        "page": 0,
    }
    data = _request(f"/order/sellers/{supplier_id}/v2/orders", supplier_id, api_key, api_secret, base_url, params)
    if isinstance(data, dict) and isinstance(data.get("content"), list):
        return data["content"]
    if isinstance(data, list):
        return data
    return []


def test_connection(supplier_id: str, api_key: str, api_secret: str, base_url: str = DEFAULT_BASE):
    try:
        orders = get_orders(supplier_id, api_key, api_secret, base_url, days_back=1, size=1)
        return True, f"Baglanti dogrulandi ({len(orders)} kayit okundu).", orders
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        if code in (401, 403):
            return False, "API Key/API Secret veya Satici ID yetkisiz (401/403).", None
        return False, f"Trendyol API hatasi: HTTP {code}", None
    except requests.exceptions.RequestException as e:
        return False, f"Baglanti hatasi: {e}", None


def order_id(order: dict) -> str:
    return str(order.get("shipmentPackageId") or order.get("id") or order.get("packageId") or "").strip()


def order_number(order: dict) -> str:
    return str(order.get("orderNumber") or order.get("orderCode") or order_id(order)).strip()


def status(order: dict) -> str:
    raw = str(order.get("status") or order.get("packageStatus") or "Created").strip()
    return STATUS_ALIASES.get(raw.upper(), raw)


def total_price(order: dict) -> float:
    value = (
        order.get("totalPrice")
        or order.get("packageTotalPrice")
        or order.get("grossAmount")
        or order.get("packageGrossAmount")
        or order.get("totalDiscountedPrice")
        or order.get("totalAmount")
        or 0
    )
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def customer_name(order: dict) -> str:
    first = str(order.get("customerFirstName") or order.get("shipmentAddress", {}).get("firstName") or "").strip()
    last = str(order.get("customerLastName") or order.get("shipmentAddress", {}).get("lastName") or "").strip()
    full = " ".join(part for part in (first, last) if part)
    return full or str(order.get("customerName") or order.get("shipmentAddress", {}).get("fullName") or "").strip()


def lines(order: dict) -> list:
    value = order.get("lines") or order.get("items") or []
    return value if isinstance(value, list) else []


def _text(value) -> str:
    return str(value or "").strip()


def _first_text(data: dict, *keys: str) -> str:
    for key in keys:
        value = _text(data.get(key))
        if value:
            return value
    return ""


def _clean_product_name(name: str, line: dict) -> str:
    result = _text(name)
    details = [
        _first_text(line, "stockCode", "merchantSku", "sku"),
        _first_text(line, "productSize", "size", "variantValue"),
        _first_text(line, "barcode"),
    ]
    changed = True
    while changed:
        changed = False
        for detail in details:
            if not detail:
                continue
            cleaned = re.sub(rf"\s*,?\s*{re.escape(detail)}\s*$", "", result, flags=re.IGNORECASE).strip()
            if cleaned != result:
                result = cleaned
                changed = True
    result = re.sub(r"\s{2,}", " ", result).strip(" ,-")
    return result or _text(name) or "Urun"


def line_name(line: dict) -> str:
    return _clean_product_name(line.get("productName") or line.get("name") or line.get("barcode") or "Urun", line)


def line_quantity(line: dict) -> int:
    try:
        return int(line.get("quantity") or line.get("amount") or 1)
    except (TypeError, ValueError):
        return 1


def line_details(line: dict) -> list:
    parts = []
    stock_code = _first_text(line, "stockCode", "merchantSku", "sku")
    option = _first_text(line, "productSize", "size", "variantValue")
    color = _first_text(line, "productColor", "color")
    barcode = _first_text(line, "barcode")

    if stock_code:
        parts.append(f"Stok kodu: {stock_code}")
    if option:
        parts.append(f"Seçenek: {option}")
    if color:
        parts.append(f"Renk: {color}")
    if barcode and not stock_code:
        parts.append(f"Barkod: {barcode}")

    for key, label in (
        ("productOrigin", "Menşei"),
        ("deliveryType", "Teslimat"),
    ):
        value = _text(line.get(key))
        if value:
            parts.append(f"{label}: {value}")
    return parts


def summarize_items(order: dict, max_items: int = 4) -> str:
    parts = []
    for line in lines(order)[:max_items]:
        if isinstance(line, dict):
            parts.append(f"{line_name(line)} x{line_quantity(line)}")
    result = ", ".join(parts) if parts else "-"
    more = len(lines(order)) - max_items
    if more > 0:
        result += f" +{more} urun"
    return result[:900]


def detailed_items_summary(order: dict, max_items: int = 4, max_length: int = 900) -> str:
    parts = []
    for line in lines(order)[:max_items]:
        if not isinstance(line, dict):
            continue
        block = [f"- {line_name(line)} x{line_quantity(line)}"]
        for detail in line_details(line):
            block.append(f"  {detail}")
        parts.append("\n".join(block))

    if not parts:
        result = "-"
    else:
        result = "\n".join(parts)
        more = len(lines(order)) - max_items
        if more > 0:
            result += f"\n+{more} urun"

    cargo = cargo_label(order)
    if cargo and cargo != "-":
        result += f"\nKargo: {cargo}"

    deadline = agreed_delivery_text(order)
    if deadline:
        result += f"\nSon kargoya verme: {deadline}"

    return result[:max_length]


def address_text(order: dict) -> str:
    address = order.get("shipmentAddress") or order.get("invoiceAddress") or {}
    if not isinstance(address, dict):
        return ""
    for key in ("fullAddress", "address1", "address", "description"):
        if address.get(key):
            return str(address.get(key)).strip()
    parts = [
        address.get("neighborhood"),
        address.get("district"),
        address.get("city"),
        address.get("postalCode"),
    ]
    return " ".join(str(part).strip() for part in parts if part)


def cargo_label(order: dict) -> str:
    return str(
        order.get("cargoProviderName")
        or order.get("cargoSenderNumber")
        or order.get("cargoTrackingNumber")
        or "-"
    ).strip()


def package_number(order: dict) -> str:
    return _first_text(order, "shipmentPackageId", "packageId", "id")


def _format_timestamp_ms(value) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    try:
        return (datetime.utcfromtimestamp(number / 1000) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def agreed_delivery_text(order: dict) -> str:
    return (
        _format_timestamp_ms(order.get("agreedDeliveryDate"))
        or _format_timestamp_ms(order.get("agreedDeliveryExtensionEndDate"))
        or _text(order.get("agreedDeliveryDate"))
    )


def extract_order_fields(order: dict) -> dict:
    return {
        "external_id": order_id(order),
        "order_number": order_number(order),
        "status": status(order),
        "total_price": total_price(order),
        "payment_type": str(order.get("paymentType") or order.get("paymentMethod") or "Trendyol").strip(),
        "app_source": "Trendyol Pazaryeri",
        "customer_note": str(order.get("customerNote") or order.get("giftBoxNote") or "").strip(),
    }


def format_new_order_message(order: dict) -> str:
    items = ""
    for line in lines(order):
        if not isinstance(line, dict):
            continue
        items += f"  • {html.escape(line_name(line))} x{line_quantity(line)}\n"
        for detail in line_details(line):
            items += f"    ↳ {html.escape(detail)}\n"
    if not items:
        items = "  (Urun bilgisi yok)\n"

    msg = (
        "🛒 <b>YENI PAZARYERI SIPARISI — Trendyol</b>\n"
        f"{'━'*28}\n"
        f"📋 <b>Siparis No:</b> #{html.escape(order_number(order) or '-')}\n"
        f"📦 <b>Paket No:</b> {html.escape(package_number(order) or '-')}\n"
        f"👤 <b>Musteri:</b> {html.escape(customer_name(order) or '-')}\n"
        f"{'━'*28}\n"
        f"📦 <b>Urunler:</b>\n{items}"
        f"{'━'*28}\n"
        f"💰 <b>Tutar:</b> {total_price(order):.2f} TL\n"
        f"🚚 <b>Kargo:</b> {html.escape(cargo_label(order))}\n"
    )
    deadline = agreed_delivery_text(order)
    if deadline:
        msg += f"⏱️ <b>Son kargoya verme:</b> {html.escape(deadline)}\n"
    address = address_text(order)
    if address:
        msg += f"📍 <b>Adres:</b> {html.escape(address)}\n"
    note = extract_order_fields(order).get("customer_note")
    if note:
        msg += f"🗒️ <b>Not:</b> {html.escape(note)}\n"
    return msg


def format_status_message(order: dict, current_status: str) -> str:
    return (
        f"🔄 <b>Trendyol Pazaryeri durum güncellendi</b>\n"
        f"{'━'*28}\n"
        f"📋 <b>Siparis No:</b> #{html.escape(order_number(order) or '-')}\n"
        f"📦 <b>Paket No:</b> {html.escape(package_number(order) or '-')}\n"
        f"ℹ️ <b>Durum:</b> {html.escape(current_status or '-')}\n"
        f"📦 <b>Urunler:</b>\n{html.escape(detailed_items_summary(order))}\n"
        f"💰 <b>Tutar:</b> {total_price(order):.2f} TL\n"
    )

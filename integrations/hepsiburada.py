"""Hepsiburada marketplace order polling helpers."""
import html
from datetime import datetime, timedelta

import requests


PLATFORM = "hepsiburada"
TEST_BASE = "https://oms-external-sit.hepsiburada.com"
LIVE_BASE = "https://oms-external.hepsiburada.com"
TEST_STUB_BASE = "https://oms-stub-external-sit.hepsiburada.com"
USER_AGENT = "SiparisGeldi-Hepsiburada-Integration"

STATUS_NOTIFY = {
    "Created",
    "Picking",
    "Shipped",
    "Delivered",
    "Undelivered",
    "Unpacked",
    "Cancelled",
}


def base_url(environment: str = "live", override: str = None) -> str:
    if override:
        return override.rstrip("/")
    return TEST_BASE if (environment or "").lower() == "test" else LIVE_BASE


def _headers() -> dict:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }


def _get(path: str, merchant_id: str, username: str, service_key: str,
         environment: str = "live", override_base: str = None, params: dict = None):
    response = requests.get(
        f"{base_url(environment, override_base)}{path}",
        headers=_headers(),
        auth=(username, service_key),
        params=params or {},
        timeout=20,
    )
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


def _recent_params(since: datetime = None, days_back: int = 3, limit: int = 100) -> dict:
    end = datetime.utcnow()
    start = since or (end - timedelta(days=days_back))
    return {
        "begindate": start.strftime("%Y-%m-%d %H:%M:%S"),
        "enddate": end.strftime("%Y-%m-%d %H:%M:%S"),
        "offset": "0",
        "limit": str(min(max(int(limit or 100), 1), 100)),
    }


def _items_from_response(data) -> list:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("items", "data", "content", "list"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _group_by_order(items: list, fallback_status: str = "Created") -> list:
    grouped = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        number = str(item.get("orderNumber") or item.get("orderNo") or item.get("packageNumber") or item.get("id") or "").strip()
        if not number:
            continue
        bucket = grouped.setdefault(number, {
            "orderNumber": number,
            "id": number,
            "merchantId": item.get("merchantId"),
            "orderDate": item.get("orderDate") or item.get("createdDate") or item.get("lastStatusUpdateDate"),
            "customerName": item.get("customerName") or "",
            "status": _normalize_status(item.get("status") or fallback_status),
            "items": [],
            "shippingAddress": item.get("shippingAddress"),
            "invoice": item.get("invoice"),
            "cargoCompanyModel": item.get("cargoCompanyModel") or {},
            "packageNumber": item.get("packageNumber"),
            "cancelReasonCode": item.get("cancelReasonCode"),
            "cancelledBy": item.get("cancelledBy"),
        })
        bucket["items"].append(item)
        if not bucket.get("customerName") and item.get("customerName"):
            bucket["customerName"] = item.get("customerName")
        if item.get("shippingAddress"):
            bucket["shippingAddress"] = item.get("shippingAddress")
        if item.get("cargoCompanyModel"):
            bucket["cargoCompanyModel"] = item.get("cargoCompanyModel")
    return list(grouped.values())


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip()
    aliases = {
        "Open": "Created",
        "Created": "Created",
        "Unpacked": "Unpacked",
        "Shipped": "Shipped",
        "Delivered": "Delivered",
        "Undelivered": "Undelivered",
        "Cancelled": "Cancelled",
        "Canceled": "Cancelled",
    }
    return aliases.get(raw, raw or "Created")


def get_open_orders(merchant_id: str, username: str, service_key: str,
                    environment: str = "live", since: datetime = None,
                    override_base: str = None) -> list:
    data = _get(
        f"/orders/merchantid/{merchant_id}",
        merchant_id,
        username,
        service_key,
        environment,
        override_base,
        _recent_params(since),
    )
    return _group_by_order(_items_from_response(data), "Created")


def get_cancelled_orders(merchant_id: str, username: str, service_key: str,
                         environment: str = "live", since: datetime = None,
                         override_base: str = None) -> list:
    data = _get(
        f"/orders/merchantid/{merchant_id}/cancelled",
        merchant_id,
        username,
        service_key,
        environment,
        override_base,
        _recent_params(since),
    )
    orders = _group_by_order(_items_from_response(data), "Cancelled")
    for order in orders:
        order["status"] = "Cancelled"
    return orders


def get_packages(merchant_id: str, username: str, service_key: str,
                 environment: str = "live", since: datetime = None,
                 override_base: str = None) -> list:
    params = _recent_params(since)
    params["timespan"] = "24"
    data = _get(
        f"/packages/merchantid/{merchant_id}",
        merchant_id,
        username,
        service_key,
        environment,
        override_base,
        params,
    )
    return _group_by_order(_items_from_response(data), "Picking")


def test_connection(merchant_id: str, username: str, service_key: str,
                    environment: str = "live", override_base: str = None):
    try:
        since = datetime.utcnow() - timedelta(days=1)
        orders = get_open_orders(merchant_id, username, service_key, environment, since, override_base)
        return True, f"Baglanti dogrulandi ({len(orders)} siparis okundu).", orders
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        if code in (401, 403):
            return False, "Kullanici adi, servis anahtari veya Magaza ID yetkisiz (401/403).", None
        return False, f"Hepsiburada API hatasi: HTTP {code}", None
    except requests.exceptions.RequestException as e:
        return False, f"Baglanti hatasi: {e}", None


def order_id(order: dict) -> str:
    return str(order.get("orderNumber") or order.get("id") or "").strip()


def order_number(order: dict) -> str:
    return str(order.get("orderNumber") or order_id(order)).strip()


def status(order: dict) -> str:
    return _normalize_status(order.get("status"))


def lines(order: dict) -> list:
    value = order.get("items") or []
    return value if isinstance(value, list) else []


def _money_amount(value) -> float:
    if isinstance(value, dict):
        value = value.get("amount") or value.get("Amount") or 0
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def total_price(order: dict) -> float:
    total = 0.0
    for item in lines(order):
        total += _money_amount(item.get("totalPrice") or item.get("price") or item.get("unitPrice"))
    return total


def line_name(line: dict) -> str:
    return str(
        line.get("productName")
        or line.get("name")
        or line.get("merchantSku")
        or line.get("sku")
        or "Urun"
    ).strip()


def line_quantity(line: dict) -> int:
    try:
        return int(line.get("quantity") or line.get("qty") or 1)
    except (TypeError, ValueError):
        return 1


def line_details(line: dict) -> list:
    parts = []
    for key, label in (
        ("sku", "HBSKU"),
        ("merchantSku", "Stok kodu"),
        ("deliveryType", "Teslimat"),
        ("slot", "Teslim saati"),
        ("pickUpTime", "Kargo teslim"),
        ("customizedText01", "Ozel alan 1"),
        ("customizedText02", "Ozel alan 2"),
        ("customizedText03", "Ozel alan 3"),
        ("customizedText04", "Ozel alan 4"),
    ):
        value = str(line.get(key) or "").strip()
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


def customer_name(order: dict) -> str:
    return str(order.get("customerName") or "").strip()


def address_text(order: dict) -> str:
    address = order.get("shippingAddress") or {}
    if not isinstance(address, dict):
        return ""
    for key in ("address", "fullAddress", "description"):
        if address.get(key):
            base = str(address.get(key)).strip()
            parts = [address.get("district"), address.get("town"), address.get("city")]
            suffix = " ".join(str(part).strip() for part in parts if part)
            return f"{base} {suffix}".strip()
    parts = [address.get("district"), address.get("town"), address.get("city")]
    return " ".join(str(part).strip() for part in parts if part)


def cargo_label(order: dict) -> str:
    cargo = order.get("cargoCompanyModel") or {}
    if isinstance(cargo, dict):
        return str(cargo.get("name") or cargo.get("shortName") or "-").strip()
    return str(order.get("cargoCompany") or "-").strip()


def extract_order_fields(order: dict) -> dict:
    return {
        "external_id": order_id(order),
        "order_number": order_number(order),
        "status": status(order),
        "total_price": total_price(order),
        "payment_type": "Hepsiburada",
        "app_source": "Hepsiburada",
        "customer_note": str(order.get("customerNote") or order.get("note") or "").strip(),
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
        "🛒 <b>YENI SIPARIS — Hepsiburada</b>\n"
        f"{'━'*28}\n"
        f"📋 <b>Siparis No:</b> #{html.escape(order_number(order) or '-')}\n"
        f"👤 <b>Musteri:</b> {html.escape(customer_name(order) or '-')}\n"
        f"{'━'*28}\n"
        f"📦 <b>Urunler:</b>\n{items}"
        f"{'━'*28}\n"
        f"💰 <b>Tutar:</b> {total_price(order):.2f} TL\n"
        f"🚚 <b>Kargo:</b> {html.escape(cargo_label(order))}\n"
    )
    address = address_text(order)
    if address:
        msg += f"📍 <b>Adres:</b> {html.escape(address)}\n"
    return msg


def format_status_message(order: dict, current_status: str) -> str:
    return (
        f"🔄 <b>Hepsiburada durum guncellendi</b>\n"
        f"{'━'*28}\n"
        f"📋 <b>Siparis No:</b> #{html.escape(order_number(order) or '-')}\n"
        f"ℹ️ <b>Durum:</b> {html.escape(current_status or '-')}\n"
        f"📦 <b>Urunler:</b> {html.escape(summarize_items(order))}\n"
        f"💰 <b>Tutar:</b> {total_price(order):.2f} TL\n"
    )


def format_cancel_message(order: dict) -> str:
    reason = str(order.get("cancelReasonCode") or order.get("cancelledBy") or "").strip()
    msg = (
        f"❌ <b>SIPARIS IPTAL — Hepsiburada</b>\n"
        f"{'━'*28}\n"
        f"📋 <b>Siparis No:</b> #{html.escape(order_number(order) or '-')}\n"
        f"📦 <b>Urunler:</b> {html.escape(summarize_items(order))}\n"
        f"💰 <b>Tutar:</b> {total_price(order):.2f} TL\n"
    )
    if reason:
        msg += f"ℹ️ <b>Neden:</b> {html.escape(reason)}\n"
    return msg

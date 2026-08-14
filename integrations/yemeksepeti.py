"""Yemeksepeti sipariş webhook ve Partner API yardımcıları."""
import html
import time
from datetime import datetime, timedelta

import requests


PLATFORM = "yemeksepeti"
LIVE_BASE = "https://yemeksepeti.partner.deliveryhero.io"
SANDBOX_BASE = "https://sandbox.partner.deliveryhero.io"
STATUS_RECEIVED = "RECEIVED"
STATUS_READY = "READY_FOR_PICKUP"
STATUS_DISPATCHED = "DISPATCHED"
STATUS_CANCELLED = "CANCELLED"
STATUS_DELIVERED = "DELIVERED"
STATUS_NOTIFY = {STATUS_RECEIVED, STATUS_READY, STATUS_DISPATCHED, STATUS_CANCELLED, STATUS_DELIVERED}

_TOKEN_CACHE = {}


def _text(value) -> str:
    return str(value or "").strip()


def client(payload: dict) -> dict:
    value = payload.get("client") or {}
    return value if isinstance(value, dict) else {}


def store_id(payload: dict) -> str:
    return _text(client(payload).get("store_id") or payload.get("store_id"))


def webhook_match_keys(payload: dict) -> set:
    """Return all store identifiers that may be present in a webhook."""
    data = client(payload)
    values = {
        data.get("store_id"),
        data.get("external_partner_config_id"),
        payload.get("store_id"),
        payload.get("external_partner_config_id"),
    }
    return {_text(value) for value in values if _text(value)}


def chain_id(payload: dict) -> str:
    return _text(client(payload).get("chain_id") or payload.get("chain_id"))


def order_id(payload: dict) -> str:
    return _text(payload.get("order_id") or payload.get("external_order_id") or payload.get("order_code"))


def order_number(payload: dict) -> str:
    return _text(payload.get("order_code") or payload.get("external_order_id") or order_id(payload))


def status(payload: dict) -> str:
    raw = _text(payload.get("status")).upper().replace(" ", "_")
    aliases = {
        "RECEIVED": STATUS_RECEIVED,
        "READY_FOR_PICKUP": STATUS_READY,
        "DISPATCHED": STATUS_DISPATCHED,
        "CANCELED": STATUS_CANCELLED,
        "CANCELLED": STATUS_CANCELLED,
        "DELIVERED": STATUS_DELIVERED,
    }
    return aliases.get(raw, raw or STATUS_RECEIVED)


def items(payload: dict) -> list:
    value = payload.get("items") or []
    return value if isinstance(value, list) else []


def item_quantity(item: dict) -> float:
    pricing = item.get("pricing") or {}
    value = pricing.get("quantity") or item.get("quantity") or 1
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return 1


def item_name(item: dict) -> str:
    return _text(item.get("name") or item.get("sku") or item.get("_id") or "Ürün")


def item_price(item: dict) -> float:
    pricing = item.get("pricing") or {}
    value = pricing.get("total_price")
    if value is None:
        value = (pricing.get("unit_price") or 0) * item_quantity(item)
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def item_price_text(item: dict) -> str:
    return f"{item_price(item):.2f} TL"


def _money_text(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return f"{float(value):.2f} TL"
    except (TypeError, ValueError):
        return _text(value)


def _option_rows(value, parent_header: str = "") -> list:
    if not isinstance(value, list):
        return []
    rows = []
    for option in value:
        if not isinstance(option, dict):
            continue
        name = _text(
            option.get("name")
            or option.get("title")
            or option.get("label")
            or option.get("item_name")
            or option.get("itemNames")
        )
        header = _text(
            option.get("header")
            or option.get("headerName")
            or option.get("category")
            or option.get("group")
            or parent_header
        )
        quantity = option.get("quantity") or option.get("amount") or 1
        price = option.get("price")
        if price is None:
            price = option.get("total_price")
        if price is None:
            price = option.get("unit_price")
        children = []
        for key in ("options", "modifiers", "choices", "children", "subOptions", "items"):
            children.extend(_option_rows(option.get(key), header))
        if name:
            rows.append({
                "name": name,
                "header": header,
                "quantity": quantity,
                "price": _money_text(price),
                "excluded": bool(option.get("excluded") or option.get("removed") or option.get("is_removed")),
                "children": children,
            })
        else:
            rows.extend(children)
    return rows


def item_options(item: dict) -> list:
    rows = []
    for key in ("options", "modifiers", "choices", "selected_options", "additions"):
        rows.extend(_option_rows(item.get(key)))
    return rows


def item_details(item: dict) -> list:
    details = []
    if _text(item.get("instructions")):
        details.append(f"Not: {_text(item['instructions'])}")
    for promotion in item.get("promotion") or []:
        if not isinstance(promotion, dict):
            continue
        name = _text(promotion.get("name"))
        if name:
            details.append(f"Promosyon: {name}")
    item_status = _text(item.get("status")).upper()
    if item_status in {"NOT_FOUND", "REPLACED"}:
        details.append(
            "Ürün durumu: bulunamadı"
            if item_status == "NOT_FOUND"
            else "Ürün durumu: değiştirildi"
        )
    return details


def total_price(payload: dict) -> float:
    payment = payload.get("payment") or {}
    value = payment.get("order_total")
    if value is None:
        value = payment.get("total") or payment.get("sub_total") or 0
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def payment_type(payload: dict) -> str:
    return _text((payload.get("payment") or {}).get("type")) or "-"


def customer_name(payload: dict) -> str:
    customer = payload.get("customer") or {}
    return " ".join(
        part for part in (_text(customer.get("first_name")), _text(customer.get("last_name"))) if part
    ) or "-"


def address_text(payload: dict) -> str:
    address = (payload.get("customer") or {}).get("delivery_address") or {}
    if not isinstance(address, dict):
        return ""
    if address.get("formattedAddress"):
        return _text(address["formattedAddress"])
    parts = [
        address.get("street"),
        address.get("number"),
        address.get("building"),
        address.get("apartment"),
        address.get("floor"),
        address.get("city"),
        address.get("zipcode"),
        address.get("country"),
    ]
    return " ".join(_text(part) for part in parts if _text(part))


def address_instructions(payload: dict) -> str:
    address = (payload.get("customer") or {}).get("delivery_address") or {}
    return _text(address.get("instructions")) if isinstance(address, dict) else ""


def delivery_label(payload: dict) -> str:
    values = {
        "LOGISTICS_DELIVERY": "Yemeksepeti Kuryesi",
        "VENDOR_DELIVERY": "Restoran Kuryesi",
        "DELIVERY": "Teslimat",
        "PICKUP": "Restorandan teslim",
    }
    raw = _text(payload.get("transport_type") or payload.get("order_type")).upper()
    return values.get(raw, raw or "-")


def promised_for(payload: dict) -> str:
    value = _text(payload.get("promised_for"))
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return value


def cancellation_reason(payload: dict) -> str:
    cancellation = payload.get("cancellation") or {}
    return _text(cancellation.get("reason") or cancellation.get("cancelled_by"))


def summarize_items(payload: dict, max_items: int = 4, max_length: int = 850) -> str:
    parts = []
    for item in items(payload)[:max_items]:
        if not isinstance(item, dict):
            continue
        text = f"{item_quantity(item)} x {item_name(item)}"
        details = item_details(item)
        if details:
            text += f" ({'; '.join(details)})"
        parts.append(text)
    result = ", ".join(parts) if parts else "-"
    more = len(items(payload)) - max_items
    if more > 0:
        result += f" +{more} ürün"
    return result[:max_length]


def extract_order_fields(payload: dict) -> dict:
    return {
        "external_id": order_id(payload),
        "order_number": order_number(payload),
        "status": status(payload),
        "total_price": total_price(payload),
        "payment_type": payment_type(payload),
        "app_source": "Yemeksepeti",
        "customer_note": _text(payload.get("comment") or address_instructions(payload)),
    }


def format_order_created(payload: dict) -> str:
    p = extract_order_fields(payload)
    lines = []
    for item in items(payload):
        if not isinstance(item, dict):
            continue
        lines.append(f"  • {html.escape(item_name(item))} x{item_quantity(item)}")
        for detail in item_details(item):
            lines.append(f"    ↳ {html.escape(detail)}")
    item_text = "\n".join(lines) or "  (ürün bilgisi yok)"
    msg = (
        "🍔 <b>YENİ SİPARİŞ — Yemeksepeti</b>\n"
        f"{'━' * 28}\n"
        f"📋 <b>Sipariş No:</b> #{html.escape(p['order_number'] or '-')}\n"
        f"👤 <b>Müşteri:</b> {html.escape(customer_name(payload))}\n"
        f"{'━' * 28}\n"
        f"🛍️ <b>Ürünler:</b>\n{item_text}\n"
        f"{'━' * 28}\n"
        f"💰 <b>Tutar:</b> {p['total_price']:.2f} ₺\n"
        f"💳 <b>Ödeme:</b> {html.escape(p['payment_type'])}\n"
        f"🚚 <b>Teslimat:</b> {html.escape(delivery_label(payload))}\n"
    )
    address = address_text(payload)
    if address:
        msg += f"📍 <b>Adres:</b> {html.escape(address)}\n"
    instructions = address_instructions(payload)
    if instructions:
        msg += f"🧭 <b>Adres tarifi:</b> {html.escape(instructions)}\n"
    if p["customer_note"] and p["customer_note"] != instructions:
        msg += f"🗒️ <b>Sipariş notu:</b> {html.escape(p['customer_note'])}\n"
    promised = promised_for(payload)
    if promised:
        msg += f"⏱️ <b>Vaat edilen teslimat:</b> {html.escape(promised)}\n"
    if payload.get("isPreorder"):
        msg += "📅 <b>Ön sipariş</b>\n"
    return msg


def format_status(payload: dict) -> str:
    p = extract_order_fields(payload)
    return (
        f"🔄 <b>Yemeksepeti sipariş durumu</b>\n"
        f"{'━' * 28}\n"
        f"📋 <b>Sipariş No:</b> #{html.escape(p['order_number'] or '-')}\n"
        f"ℹ️ <b>Durum:</b> {html.escape(p['status'])}\n"
        f"🛍️ <b>Ürünler:</b> {html.escape(summarize_items(payload))}\n"
        f"💰 <b>Tutar:</b> {p['total_price']:.2f} ₺\n"
    )


def format_cancelled(payload: dict) -> str:
    p = extract_order_fields(payload)
    msg = (
        f"❌ <b>SİPARİŞ İPTAL — Yemeksepeti</b>\n"
        f"{'━' * 28}\n"
        f"📋 <b>Sipariş No:</b> #{html.escape(p['order_number'] or '-')}\n"
        f"🛍️ <b>Ürünler:</b> {html.escape(summarize_items(payload))}\n"
        f"💰 <b>Tutar:</b> {p['total_price']:.2f} ₺\n"
    )
    reason = cancellation_reason(payload)
    if reason:
        msg += f"📌 <b>Neden:</b> {html.escape(reason)}\n"
    return msg


def api_base(environment: str = "live") -> str:
    return SANDBOX_BASE if (environment or "").lower() == "sandbox" else LIVE_BASE


def _token_cache_key(environment: str, client_id: str) -> tuple:
    return ((environment or "live").lower(), client_id or "")


def clear_token_cache(environment: str = None, client_id: str = None):
    if environment is None and client_id is None:
        _TOKEN_CACHE.clear()
        return
    _TOKEN_CACHE.pop(_token_cache_key(environment or "live", client_id or ""), None)


def get_access_token(client_id: str, client_secret: str, environment: str = "live") -> str:
    client_id = _text(client_id)
    client_secret = _text(client_secret)
    if not client_id or not client_secret:
        raise ValueError("Yemeksepeti client_id/client_secret eksik.")

    key = _token_cache_key(environment, client_id)
    cached = _TOKEN_CACHE.get(key)
    now = time.time()
    if cached and cached.get("expires_at", 0) > now + 60:
        return cached["access_token"]

    response = requests.post(
        f"{api_base(environment)}/v2/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Yemeksepeti token cevabında access_token yok.")
    expires_in = int(data.get("expires_in") or 7200)
    _TOKEN_CACHE[key] = {"access_token": token, "expires_at": now + expires_in}
    return token


def api_request(method: str, path: str, client_id: str, client_secret: str,
                environment: str = "live", json_body: dict = None, params: dict = None):
    token = get_access_token(client_id, client_secret, environment)
    response = requests.request(
        method,
        f"{api_base(environment)}{path}",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        json=json_body,
        params=params or {},
        timeout=25,
    )
    if response.status_code == 401:
        clear_token_cache(environment, client_id)
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


def test_connection(chain_id: str, vendor_id: str, client_id: str, client_secret: str,
                    environment: str = "live"):
    try:
        data = get_vendor_status(chain_id, vendor_id, client_id, client_secret, environment)
        status_value = data.get("status") or "-"
        return True, f"Bağlantı doğrulandı. Restoran durumu: {status_value}", data
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        if code in (401, 403):
            return False, "Yemeksepeti OAuth bilgileri yetkisiz veya hatalı (401/403).", None
        if code == 404:
            return False, "Chain ID veya Vendor ID bulunamadı (404).", None
        return False, f"Yemeksepeti API hatası: HTTP {code}", None
    except requests.exceptions.RequestException as e:
        return False, f"Yemeksepeti bağlantı hatası: {e}", None
    except Exception as e:
        return False, f"Yemeksepeti doğrulama hatası: {e}", None


def get_order(chain_id: str, order_id_value: str, client_id: str, client_secret: str,
              environment: str = "live"):
    return api_request(
        "GET",
        f"/v2/chains/{chain_id}/orders/{order_id_value}",
        client_id,
        client_secret,
        environment,
    )


def get_vendor_orders(chain_id: str, vendor_id: str, client_id: str, client_secret: str,
                      environment: str = "live", start_time: datetime = None,
                      end_time: datetime = None, page: int = 1, page_size: int = 50):
    end_time = end_time or datetime.utcnow()
    start_time = start_time or (end_time - timedelta(days=1))
    params = {
        "start_time": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "end_time": end_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "page": max(1, int(page or 1)),
        "page_size": min(max(int(page_size or 50), 1), 100),
    }
    return api_request(
        "GET",
        f"/v2/chains/{chain_id}/vendors/{vendor_id}/orders",
        client_id,
        client_secret,
        environment,
        params=params,
    )


def update_order(chain_id: str, order_id_value: str, body: dict, client_id: str,
                 client_secret: str, environment: str = "live"):
    return api_request(
        "PUT",
        f"/v2/chains/{chain_id}/orders/{order_id_value}",
        client_id,
        client_secret,
        environment,
        json_body=body,
    )


def get_vendor_status(chain_id: str, vendor_id: str, client_id: str, client_secret: str,
                      environment: str = "live"):
    return api_request(
        "GET",
        f"/v2/chains/{chain_id}/vendors/{vendor_id}/status",
        client_id,
        client_secret,
        environment,
    )


def update_vendor_status(chain_id: str, vendor_id: str, body: dict, client_id: str,
                         client_secret: str, environment: str = "live"):
    return api_request(
        "PUT",
        f"/v2/chains/{chain_id}/vendors/{vendor_id}/status",
        client_id,
        client_secret,
        environment,
        json_body=body,
    )


def fulfillment_status(payload: dict) -> str:
    return STATUS_DISPATCHED if _text(payload.get("transport_type")).upper() == "VENDOR_DELIVERY" else STATUS_READY


def build_order_update_payload(payload: dict, target_status: str, cancel_reason: str = None) -> dict:
    update_items = []
    for item in items(payload):
        if not isinstance(item, dict):
            continue
        update_items.append({
            "_id": _text(item.get("_id")) or None,
            "sku": _text(item.get("sku")) or None,
            "pricing": item.get("pricing") or {},
            "status": "NOT_FOUND" if target_status == STATUS_CANCELLED else "IN_CART",
        })
    body = {
        "order_id": order_id(payload),
        "items": [{k: v for k, v in item.items() if v not in (None, "")} for item in update_items],
        "status": "CANCELLED" if target_status == STATUS_CANCELLED else target_status,
    }
    if target_status == STATUS_CANCELLED:
        body["cancellation"] = {"reason": cancel_reason or "TOO_BUSY"}
    return body

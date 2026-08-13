"""TrendyolGo API istemcisi — çok kullanıcılı.

Kanıtlanmış tek-kullanıcılı bottan uyarlanmıştır (auth başlığı, endpoint'ler,
mesaj formatları). Her çağrı kullanıcının kendi credential'larıyla yapılır.
"""
import base64
from datetime import datetime, timedelta
import requests

PROD_BASE = "https://api.tgoapis.com"
SERVICE_MEAL = "meal"
SERVICE_GROCERY = "grocery"

# Yeni sipariş için tam detay bildirimi verilecek statüler
NEW_ORDER_STATUSES = {"Created", "Picking"}
# Kısa statü-değişim bildirimi verilecek statüler
STATUS_NOTIFY = {"Picking", "Invoiced", "Shipped", "Delivered", "Cancelled", "UnSupplied", "Returned"}
CANCEL_STATUSES = {"Cancelled", "UnSupplied"}
REFUND_STATUSES = {"Returned", "Refunded", "Refund", "Accepted", "WaitingInAction", "Unresolved"}
ORDER_POLL_STATUSES = "Created,Picking,Invoiced,Shipped,Delivered,Cancelled,UnSupplied"
CLAIM_STATUSES = ("Created", "WaitingInAction", "Accepted", "Rejected", "Cancelled", "Unresolved")


def _headers(supplier_id: str, api_key: str, api_secret: str) -> dict:
    cred = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
    return {
        "Authorization": f"Basic {cred}",
        "User-Agent": f"{supplier_id} - SelfIntegration",
        "x-agentname": "SiparisGeldi",
        "x-executor-user": "integration@siparisgeldi.net",
        "Content-Type": "application/json",
    }


def _service(service: str = SERVICE_MEAL) -> str:
    return SERVICE_GROCERY if (service or "").lower() == SERVICE_GROCERY else SERVICE_MEAL


def test_connection(supplier_id: str, api_key: str, api_secret: str, service: str = SERVICE_MEAL):
    """API bağlantısını test eder. (ok: bool, mesaj: str, stores: list) döner."""
    service = _service(service)
    url = f"{PROD_BASE}/integrator/store/{service}/suppliers/{supplier_id}/stores"
    try:
        r = requests.get(url, headers=_headers(supplier_id, api_key, api_secret),
                         params={"page": 0, "size": 10}, timeout=15)
        if r.status_code == 401:
            return False, "API bilgileri hatalı. Supplier ID, API Key ve Secret'ı kontrol edin.", []
        r.raise_for_status()
        data = r.json()
        stores = data.get("restaurants") or data.get("stores") or data.get("content") or []
        return True, f"{len(stores)} restoran bulundu.", stores
    except requests.exceptions.RequestException as e:
        return False, f"Bağlantı hatası: {e}", []


def _timestamp_ms(value: datetime = None) -> int:
    return int(value.timestamp() * 1000) if value else None


def _status_values(statuses) -> list:
    if isinstance(statuses, str):
        return [s.strip() for s in statuses.split(",") if s.strip()]
    return [str(s).strip() for s in (statuses or []) if str(s).strip()]


def _package_params(statuses, since: datetime = None, repeated_status: bool = False):
    now = datetime.utcnow()
    params = [("page", 0), ("size", 200), ("sortDirection", "DESC")]
    if since:
        params.extend([("startDate", _timestamp_ms(since)), ("endDate", _timestamp_ms(now))])
    values = _status_values(statuses)
    if repeated_status:
        params.extend(("status", status) for status in values)
    elif values:
        params.append(("packageStatuses", ",".join(values)))
    return params


def get_orders(supplier_id: str, api_key: str, api_secret: str,
               statuses=ORDER_POLL_STATUSES, service: str = SERVICE_MEAL,
               since: datetime = None) -> list:
    """Aktif siparişleri çeker. Hata olursa boş liste döner."""
    service = _service(service)
    url = f"{PROD_BASE}/integrator/order/{service}/suppliers/{supplier_id}/packages"
    attempts = (
        _package_params(statuses, since),
        _package_params(statuses, since, repeated_status=True),
        _package_params(statuses, None),
    )
    last_error = None
    for params in attempts:
        try:
            r = requests.get(url, headers=_headers(supplier_id, api_key, api_secret),
                             params=params,
                             timeout=15)
            r.raise_for_status()
            return r.json().get("content", [])
        except requests.exceptions.HTTPError as exc:
            last_error = exc
            if exc.response is None or exc.response.status_code not in (400, 404):
                raise
    if last_error:
        raise last_error
    return []


def get_claims(supplier_id: str, api_key: str, api_secret: str, since: datetime = None,
               service: str = SERVICE_MEAL) -> list:
    """Trendyol Go Market iade kayıtlarını çeker."""
    service = _service(service)
    url = f"{PROD_BASE}/integrator/claim/{service}/suppliers/{supplier_id}/claims"
    now = datetime.utcnow()
    since = since or (now - timedelta(days=1))
    start_ms = int(since.timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)
    claims = []
    seen = set()
    for status in CLAIM_STATUSES:
        r = requests.get(
            url,
            headers=_headers(supplier_id, api_key, api_secret),
            params={
                "claimItemStatus": status,
                "startDate": start_ms,
                "endDate": end_ms,
                "page": 0,
                "size": 50,
            },
            timeout=15,
        )
        r.raise_for_status()
        for claim in r.json().get("content", []) or []:
            claim_id = str(claim.get("id") or "")
            key = claim_id or f"{claim.get('orderNumber')}-{status}"
            if key and key not in seen:
                seen.add(key)
                claims.append(claim)
    return claims


def _request(method: str, endpoint: str, supplier_id: str, api_key: str, api_secret: str,
             json_body: dict = None):
    url = f"{PROD_BASE}{endpoint}"
    kwargs = {"headers": _headers(supplier_id, api_key, api_secret), "timeout": 15}
    if json_body is not None:
        kwargs["json"] = json_body
    response = requests.request(method, url, **kwargs)
    response.raise_for_status()
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {}


def update_package_status(supplier_id: str, api_key: str, api_secret: str, package_id,
                          action: str, total_price=None, service: str = SERVICE_MEAL):
    service = _service(service)
    body = None
    if service == SERVICE_MEAL:
        endpoints = {
            "pick": f"/integrator/order/{service}/suppliers/{supplier_id}/packages/picked",
            "invoice": f"/integrator/order/{service}/suppliers/{supplier_id}/packages/invoiced",
            "ship": f"/integrator/order/{service}/suppliers/{supplier_id}/packages/{package_id}/manual-shipped",
            "deliver": f"/integrator/order/{service}/suppliers/{supplier_id}/packages/{package_id}/manual-delivered",
        }
        endpoint = endpoints.get(action)
        if action == "pick":
            body = {"packageId": str(package_id), "preparationTime": 30}
        elif action == "invoice":
            body = {"packageId": str(package_id), "actualDate": _timestamp_ms(datetime.utcnow())}
        elif action in {"ship", "deliver"}:
            body = {"actualDate": _timestamp_ms(datetime.utcnow())}
    else:
        endpoints = {
            "pick": f"/integrator/order/{service}/suppliers/{supplier_id}/packages/{package_id}/picked",
            "invoice": f"/integrator/order/{service}/suppliers/{supplier_id}/packages/{package_id}/invoiced",
        }
        endpoint = endpoints.get(action)
        if action == "invoice":
            amount = _as_float(total_price)
            body = {
                "invoiceAmount": amount,
                "bagCount": None,
                "receiptLink": None,
                "invoiceTaxAmount": 0.0,
            }
    if not endpoint:
        raise ValueError("Gecersiz Trendyol Go siparis aksiyonu")
    return _request("PUT", endpoint, supplier_id, api_key, api_secret, body)


def set_store_working_status(supplier_id: str, store_id: str, api_key: str, api_secret: str,
                             working_status: str, service: str = SERVICE_MEAL):
    service = _service(service)
    status = str(working_status or "").strip().upper()
    if status not in {"OPEN", "CLOSED"}:
        raise ValueError("Gecersiz Trendyol Go restoran durumu")
    if service == SERVICE_GROCERY:
        endpoint = f"/integrator/store/{service}/suppliers/{supplier_id}/stores/{store_id}/working-status"
        return _request("PUT", endpoint, supplier_id, api_key, api_secret, {"workingStatus": status})
    endpoint = f"/integrator/store/{service}/suppliers/{supplier_id}/stores/{store_id}/status"
    return _request("PUT", endpoint, supplier_id, api_key, api_secret, {"status": status})


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


def _as_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


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
    total_price  = _as_float(order.get("totalPrice", 0))
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
    total_price  = _as_float(order.get("totalPrice", 0))

    status_map = {
        "Picking":    ("✅", "SİPARİŞ KABUL EDİLDİ",  "Restoran hazırlamaya başladı."),
        "Invoiced":   ("👨‍🍳", "SİPARİŞ HAZIRLANDI",   "Kurye bekleniyor."),
        "Shipped":    ("🛵", "SİPARİŞ YOLA ÇIKTI",    "Kurye teslimatta."),
        "Delivered":  ("🎉", "TESLİM EDİLDİ",         "Sipariş müşteriye ulaştı."),
        "Cancelled":  ("❌", "SİPARİŞ İPTAL EDİLDİ",  ""),
        "UnSupplied": ("🚫", "RESTORAN İPTAL ETTİ",   ""),
        "Returned":   ("↩️", "SİPARİŞ İADE EDİLDİ",   ""),
        "Refunded":   ("↩️", "SİPARİŞ İADE EDİLDİ",   ""),
        "Refund":     ("↩️", "SİPARİŞ İADE EDİLDİ",   ""),
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


def claim_status(claim: dict) -> str:
    for item in claim.get("claimItems") or []:
        if not isinstance(item, dict):
            continue
        status = item.get("claimItemStatus") or {}
        name = status.get("name") if isinstance(status, dict) else status
        if _clean_text(name):
            return _clean_text(name)
    return _clean_text(claim.get("claimItemStatus") or claim.get("status") or "Refunded")


def claim_order_number(claim: dict) -> str:
    return _clean_text(claim.get("orderNumber") or claim.get("order_number"))


def claim_external_id(claim: dict) -> str:
    return _clean_text(claim.get("id") or claim_order_number(claim))


def claim_customer_note(claim: dict) -> str:
    notes = []
    for item in claim.get("claimItems") or []:
        if not isinstance(item, dict):
            continue
        for key in ("customerNote", "note"):
            value = _clean_text(item.get(key))
            if value and value not in notes:
                notes.append(value)
    return " | ".join(notes)


def claim_total_price(claim: dict, original_order: dict = None, fallback: float = 0.0) -> float:
    for key in ("claimTotalPrice", "refundAmount", "totalPrice", "totalAmount", "amount", "price"):
        try:
            value = float(claim.get(key) or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value:
            return value

    total = 0.0
    for item in claim.get("claimItems") or []:
        if not isinstance(item, dict):
            continue
        for key in ("claimAmount", "refundAmount", "totalPrice", "amount", "price"):
            try:
                total += float(item.get(key) or 0)
            except (TypeError, ValueError):
                pass
    if total:
        return total

    line_item_ids = {
        _clean_text(item.get("orderLineItemId"))
        for item in claim.get("claimItems") or []
        if isinstance(item, dict) and _clean_text(item.get("orderLineItemId"))
    }
    if original_order and line_item_ids:
        for line in original_order.get("lines") or []:
            if not isinstance(line, dict):
                continue
            for order_item in line.get("items") or []:
                if not isinstance(order_item, dict):
                    continue
                if _clean_text(order_item.get("id")) != "" and _clean_text(order_item.get("id")) in line_item_ids:
                    try:
                        total += float(order_item.get("price") or order_item.get("amount") or 0)
                    except (TypeError, ValueError):
                        pass
        if total:
            return total

    try:
        return float(fallback or 0)
    except (TypeError, ValueError):
        return 0.0


def claim_items_summary(claim: dict, max_items: int = 4) -> str:
    parts = []
    for item in (claim.get("claimItems") or [])[:max_items]:
        if not isinstance(item, dict):
            continue
        reason = item.get("customerClaimItemReason") or item.get("trendyolClaimItemReason") or {}
        reason_name = reason.get("name") if isinstance(reason, dict) else ""
        item_id = item.get("orderLineItemId") or item.get("id")
        label = f"Kalem {item_id}" if item_id else "İade kalemi"
        if reason_name:
            label += f" ({reason_name})"
        parts.append(label)
    result = ", ".join(parts) if parts else "-"
    more = len(claim.get("claimItems") or []) - max_items
    if more > 0:
        result += f" +{more} kalem"
    return result[:900]


def format_claim_message(claim: dict) -> str:
    order_number = claim_order_number(claim) or "N/A"
    status = claim_status(claim)
    items = claim_items_summary(claim)
    return (
        "↩️ <b>TRENDYOL GO İADE BİLDİRİMİ</b>\n"
        f"{'━'*28}\n"
        f"📋 <b>Sipariş No:</b> #{order_number}\n"
        f"ℹ️ <b>İade durumu:</b> {status}\n"
        f"🛍️ <b>Kalemler:</b> {items}\n"
    )

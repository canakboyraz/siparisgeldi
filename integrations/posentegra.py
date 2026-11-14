"""PosEntegra (FastSipariş) üzerinden Yemeksepeti siparişleri.

Doküman: https://posentegra.com/docs  ·  API: https://api.v1.fastsiparis.com/web-api/v1
- Kimlik: hesap düzeyinde tek API anahtarı (Authorization: Bearer <anahtar>).
- Webhook: {"olay": "siparis.olusturuldu" | "siparis.durum_degisti" | "siparis.iptal_edildi" |
  "entegrasyon.durum_degisti", "veri": {...}}. İstekler imzalanmaz; Authorization başlığında
  API anahtarı gelir.
- Hız sınırı: uç nokta başına dakikada 5 istek (429'da üstel bekleme önerilir).

Dokümanda sipariş durum kodlarının anlamı yok (örneklerde 500 → 600, iptal 1600). Bu yüzden
kendi durum akışımızı tutuyoruz: RECEIVED → (verify) ACCEPTED → PREPARED → DISPATCHED → DELIVERED.
Gelen sipariş, mevcut Yemeksepeti koduyla (rapor, bildirim, sipariş ekranı) aynı biçime
dönüştürülür; PosEntegra'nın ham verisi "_pe" altında saklanır.
"""
import time
from datetime import datetime

import requests

from integrations import yemeksepeti as ys

SOURCE = "posentegra"
DEFAULT_BASE = "https://api.v1.fastsiparis.com"
API_PREFIX = "/web-api/v1"
TIMEOUT = (5, 15)

EVENT_CREATED = "siparis.olusturuldu"
EVENT_STATUS = "siparis.durum_degisti"
EVENT_CANCELLED = "siparis.iptal_edildi"
EVENT_INTEGRATION = "entegrasyon.durum_degisti"

CANCELLED_CODES = {1600}
# Kabul sonrası adımlar: PosEntegra change-status her çağrıda bir sonraki duruma geçirir
# (hazırlanıyor → yolda → teslim). Butonlar bu sırayla gösterilir.
NEXT_STEP = {
    ys.STATUS_ACCEPTED: (ys.STATUS_PREPARED, "Hazırlanıyor"),
    ys.STATUS_PREPARED: (ys.STATUS_DISPATCHED, "Yola çıktı"),
    ys.STATUS_DISPATCHED: (ys.STATUS_DELIVERED, "Teslim edildi"),
}


class PosEntegraError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


# ── HTTP ───────────────────────────────────────────────────────────────────

def api_base(configured: str = "") -> str:
    return (configured or DEFAULT_BASE).rstrip("/")


def request(method: str, path: str, api_key: str, base: str = "", json_body=None, params=None,
            retries: int = 1):
    """API çağrısı. 429/5xx'te kısa beklemeyle `retries` kez daha dener. `data` döner."""
    if not api_key:
        raise PosEntegraError("PosEntegra API anahtarı tanımlı değil.")
    url = f"{api_base(base)}{API_PREFIX}{path}"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(retries + 1):
        try:
            response = requests.request(method, url, headers=headers, json=json_body, params=params,
                                        timeout=TIMEOUT, allow_redirects=False)
        except requests.Timeout:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise PosEntegraError("PosEntegra zamanında yanıt vermedi.") from None
        except requests.RequestException:
            raise PosEntegraError("PosEntegra bağlantısı kurulamadı.") from None
        if response.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(3 * (attempt + 1))
            continue
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code >= 400 or not isinstance(body, dict) or body.get("success") is False:
            message = (body or {}).get("message") if isinstance(body, dict) else ""
            hint = {401: "API anahtarı geçersiz.", 403: "Restorana paket atanmamış ya da erişim yok.",
                    404: "Kayıt bulunamadı.", 429: "PosEntegra istek sınırı aşıldı (dakikada 5)."}.get(
                response.status_code, "")
            raise PosEntegraError(
                f"PosEntegra HTTP {response.status_code}: {(message or hint or 'beklenmeyen yanıt')[:180]}",
                response.status_code)
        return body.get("data")
    raise PosEntegraError("PosEntegra isteği tamamlanamadı.")


def get_order(api_key, order_id, base=""):
    return request("GET", f"/orders/{order_id}", api_key, base, retries=1) or {}


def verify_order(api_key, order_id, base=""):
    return request("POST", f"/orders/verify/{order_id}", api_key, base, json_body={}) or {}


def change_status(api_key, order_id, base=""):
    return request("POST", f"/orders/change-status/{order_id}", api_key, base, json_body={}) or {}


def cancel_order(api_key, order_id, reason="", note="", base=""):
    body = {"reason": reason} if reason else {}
    if note:
        body["note"] = note
    return request("POST", f"/orders/cancel/{order_id}", api_key, base, json_body=body) or {}


def cancel_reasons(api_key, order_id, base=""):
    data = request("GET", f"/orders/reasons/{order_id}", api_key, base) or {}
    rows = data.get("reasons") if isinstance(data, dict) else data
    out = []
    for r in rows or []:
        if isinstance(r, dict) and r.get("id"):
            out.append({"id": str(r["id"]), "name": _tr(r.get("name")) or str(r["id"])})
    return out


def mark_reported(api_key, provider_order_id, base=""):
    return request("POST", "/orders/reports/mark", api_key, base,
                   json_body={"providerOrderId": provider_order_id}) or {}


def restaurant_integrations(api_key, restaurant_id, base=""):
    return request("GET", f"/restaurants/{restaurant_id}/integrations", api_key, base)


# ── Webhook ────────────────────────────────────────────────────────────────

def webhook_event(payload: dict):
    """(olay, veri) döner. Gövde doğrudan sipariş de olabilir."""
    if not isinstance(payload, dict):
        return "", {}
    event = str(payload.get("olay") or payload.get("event") or "").strip()
    data = payload.get("veri") if isinstance(payload.get("veri"), dict) else None
    if data is None and isinstance(payload.get("data"), dict):
        data = payload["data"]
    if data is None:
        data = payload
    return event, data


def restaurant_id(data: dict) -> str:
    rest = data.get("restaurant") if isinstance(data.get("restaurant"), dict) else {}
    return str(data.get("restaurantId") or rest.get("id") or "").strip()


def internal_id(data: dict) -> str:
    """PosEntegra'nın kendi sipariş kimliği (24 karakter hex, ör. 6af824c9e60c5d0bab26ad6b).
    Sipariş API'leri (verify/change-status/cancel) bu kimliği bekler, Yemeksepeti numarasını değil."""
    import re
    if not isinstance(data, dict):
        return ""
    for key in ("_id", "orderId", "order_id", "id", "posentegraOrderId"):
        value = data.get(key)
        if isinstance(value, dict):
            value = value.get("$oid") or value.get("id")
        value = str(value or "").strip()
        if re.fullmatch(r"[0-9a-fA-F]{24}", value):
            return value
    return ""


def provider_order_id(data: dict) -> str:
    return str(data.get("providerOrderId") or data.get("pid") or data.get("shortCode") or "").strip()


def has_details(data: dict) -> bool:
    return isinstance(data.get("products"), list) and bool(data.get("products"))


# ── Dönüştürme ─────────────────────────────────────────────────────────────

def _tr(value) -> str:
    if isinstance(value, dict):
        return str(value.get("tr") or value.get("en") or "").strip()
    return str(value or "").strip()


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _date(value) -> str:
    if isinstance(value, dict):
        value = value.get("$date")
    return str(value or "").strip()


def _options(product: dict) -> list:
    rows = []
    for cat in product.get("optionCategories") or []:
        if not isinstance(cat, dict):
            continue
        header = _tr(cat.get("name") or cat.get("title"))
        for opt in cat.get("options") or cat.get("items") or []:
            if isinstance(opt, dict) and _tr(opt.get("name")):
                rows.append({"name": _tr(opt.get("name")), "header": header,
                             "price": opt.get("price"), "quantity": opt.get("count") or 1})
    for extra in product.get("extraIngredients") or []:
        name = _tr(extra.get("name")) if isinstance(extra, dict) else _tr(extra)
        if name:
            rows.append({"name": name, "header": "Ekstra",
                         "price": extra.get("price") if isinstance(extra, dict) else None})
    for removed in product.get("removedIngredients") or []:
        name = _tr(removed.get("name")) if isinstance(removed, dict) else _tr(removed)
        if name:
            rows.append({"name": name, "header": "Çıkarılan", "excluded": True})
    return rows


def _address(client: dict) -> tuple:
    addr = client.get("deliveryAddress") if isinstance(client.get("deliveryAddress"), dict) else {}
    parts = [addr.get("address"), addr.get("building"),
             f"Kat: {addr['floor']}" if addr.get("floor") else "",
             f"Daire: {addr['doorNo']}" if addr.get("doorNo") else "",
             addr.get("district") or addr.get("deliveryMainArea"), addr.get("city")]
    text = ", ".join(str(p).strip() for p in parts if p and str(p).strip())
    return text, str(addr.get("description") or "").strip()


def status_from(data: dict, current: str = "") -> str:
    code = data.get("statusCode", data.get("status"))
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None
    if code in CANCELLED_CODES or data.get("cancelReason"):
        return ys.STATUS_CANCELLED
    if current and current != ys.STATUS_RECEIVED:
        return current                       # kendi ilerlettiğimiz durumu koru
    if data.get("isConfirm") or data.get("verify"):
        return ys.STATUS_ACCEPTED            # PosEntegra panelinde otomatik onay açık
    return current or ys.STATUS_RECEIVED


def normalize(data: dict, current_status: str = "") -> dict:
    """PosEntegra siparişini SiparişGeldi'nin Yemeksepeti biçimine çevirir."""
    client = data.get("client") if isinstance(data.get("client"), dict) else {}
    address, directions = _address(client)
    products = []
    for p in data.get("products") or []:
        if not isinstance(p, dict):
            continue
        qty = _num(p.get("count"), 1) or 1
        total = _num(p.get("totalPriceWithOption", p.get("totalPrice")), _num(p.get("price")) * qty)
        products.append({
            "name": _tr(p.get("name")) or "Ürün",
            "pricing": {"quantity": int(qty) if float(qty).is_integer() else qty,
                        "total_price": total, "unit_price": _num(p.get("priceWithOption", p.get("price")))},
            "instructions": str(p.get("note") or "").strip(),
            "options": _options(p),
            "sku": str(p.get("product") or p.get("id") or ""),
        })
    total = data.get("totalDiscountedPrice")
    if total in (None, ""):
        total = data.get("totalPrice")
    payment = str(data.get("posPaymentMethod") or _tr(data.get("paymentMethodText")) or "").strip()
    loc = client.get("location") if isinstance(client.get("location"), dict) else {}
    pid = provider_order_id(data)
    return {
        "token": pid,
        "code": str(data.get("shortCode") or pid),
        "status": status_from(data, current_status),
        "products": products,
        "price": {"grandTotal": _num(total)},
        "payment": {"type": payment or "-", "online": bool(data.get("is_payment_online"))},
        "customer": {"firstName": str(client.get("name") or "").strip(),
                     "mobilePhone": str(client.get("clientPhoneNumber") or client.get("contactPhoneNumber") or "")},
        "delivery": {"address": {"formattedAddress": address, "instructions": directions,
                                 "latitude": loc.get("lat"), "longitude": loc.get("lon")}},
        "comments": {"customerComment": str(data.get("clientNote") or "").strip()},
        "createdAt": _date(data.get("created_at") or data.get("createdAt")),
        "isPreorder": bool(data.get("isScheduled")),
        "_source": SOURCE,
        "_pe": {
            "id": internal_id(data) or str(data.get("id") or pid), "internalId": internal_id(data),
            "providerOrderId": pid,
            "restaurantId": restaurant_id(data),
            "restaurantName": (data.get("restaurant") or {}).get("name") if isinstance(data.get("restaurant"), dict) else "",
            "statusCode": data.get("statusCode", data.get("status")),
            "deliveryType": data.get("deliveryType"), "courier": data.get("courier"),
            "cancelReason": data.get("cancelReason"), "cancelNote": data.get("cancelNote"),
            "doNotKnock": data.get("doNotKnock"), "isEcoFriendly": data.get("isEcoFriendly"),
            "receivedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        },
    }


def is_posentegra(raw: dict) -> bool:
    return isinstance(raw, dict) and raw.get("_source") == SOURCE

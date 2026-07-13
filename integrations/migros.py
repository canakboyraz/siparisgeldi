"""Migros Yemek (Gourmet) entegrasyonu.

İki yön vardır:
  1. TERS AKIŞ (webhook) — Migros bize düz JSON POST eder (sipariş oluştu / iptal /
     kurye durumu). Notifier'ın çekirdeği budur; şifreleme YOKTUR.
  2. İLERİ AKIŞ (API) — biz Migros'a istek atarız (mağaza listesi, sipariş onay).
     GetDefinedActiveRestaurantApiKeys hariç tüm POST gövdeleri AES-256-ECB ile
     şifrelenip {"value": "<base64>"} olarak gönderilir. XApiKey header'ı = restoran
     api key. Bu kısım "sipariş onaylama" gibi ileri özellikler için hazırdır.

Doküman: MIGROS YEMEK API DOKUMANTASYONU.pdf
Test base:  https://test.gourmet.migrosonline.com
Canlı base: https://gourmet.migrosonline.com
"""
import base64
import json
import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

DEFAULT_BASE = "https://gourmet.migrosonline.com"


# ── Rijndael / AES-256-ECB + PKCS7 (C# RijndaelManaged ECB ile birebir) ──────

def aes_encrypt(plaintext: str, secret_key: str) -> str:
    """UTF-8 metni AES-256-ECB + PKCS7 ile şifreler, base64 döner."""
    key = secret_key.encode("utf-8")
    padder = padding.PKCS7(128).padder()
    data = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    ct = enc.update(data) + enc.finalize()
    return base64.b64encode(ct).decode("ascii")


def aes_decrypt(b64_ciphertext: str, secret_key: str) -> str:
    """base64 AES-256-ECB şifreli metni çözer, UTF-8 döner."""
    key = secret_key.encode("utf-8")
    ct = base64.b64decode(b64_ciphertext)
    dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    pt = dec.update(ct) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(pt) + unpadder.finalize()).decode("utf-8")


# ── İleri akış API istemcisi (opsiyonel/gelecek özellikler) ──────────────────

def _headers(api_key: str) -> dict:
    return {"XApiKey": api_key, "Content-Type": "application/json"}


def api_get(endpoint: str, api_key: str, base_url: str = DEFAULT_BASE, params: dict = None):
    r = requests.get(f"{base_url}{endpoint}", headers=_headers(api_key),
                     params=params or {}, timeout=15)
    r.raise_for_status()
    return r.json()


def api_post(endpoint: str, body: dict, api_key: str, secret_key: str,
             base_url: str = DEFAULT_BASE) -> dict:
    """Şifreli POST: gövde AES ile şifrelenip {'value':...} olarak gönderilir.
    Yanıt da şifreliyse çözülür."""
    payload = {"value": aes_encrypt(json.dumps(body), secret_key)}
    r = requests.post(f"{base_url}{endpoint}", headers=_headers(api_key),
                      json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    # Yanıt {"value": "<şifreli>"} biçimindeyse çöz
    if isinstance(data, dict) and set(data.keys()) == {"value"} and isinstance(data["value"], str):
        try:
            return json.loads(aes_decrypt(data["value"], secret_key))
        except Exception:
            return data
    return data


def test_connection(api_key: str, secret_key: str = "", base_url: str = DEFAULT_BASE):
    """Restoran API key'ini doğrular (GetStoreGroups — şifreleme gerektirmez).
    (ok: bool, mesaj: str, data) döner."""
    try:
        data = api_get("/Store/GetStoreGroups", api_key, base_url)
        groups = data.get("data", data) if isinstance(data, dict) else data
        n = len(groups) if isinstance(groups, list) else "?"
        return True, f"Bağlantı doğrulandı ({n} marka/zincir bulundu).", groups
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        if code in (401, 403):
            return False, "API Key geçersiz veya yetkisiz (401/403).", None
        return False, f"Migros API hatası: HTTP {code}", None
    except requests.exceptions.RequestException as e:
        return False, f"Bağlantı hatası: {e}", None


# Sipariş durum güncelleme değerleri (v2/UpdateOrderStatus)
ORDER_STATUS_APPROVED  = "Approved"
ORDER_STATUS_REJECTED  = "Rejected"
ORDER_STATUS_PREPARED  = "Prepared"
ORDER_STATUS_DELIVERY  = "Delivery"
ORDER_STATUS_COMPLETED = "Completed"


def update_order_status(order_id, new_status: str, store_id, api_key: str, secret_key: str,
                        cancel_reason_id=None, base_url: str = DEFAULT_BASE) -> dict:
    """Siparişin durumunu Migros'ta günceller (onay/ret/hazırlandı vb.).
    Notifier MVP'de kullanılmaz; ileride 'siparişi onayla' butonu için hazırdır."""
    body = {"OrderId": order_id, "OrderStatus": new_status, "StoreId": store_id}
    if new_status == ORDER_STATUS_REJECTED and cancel_reason_id is not None:
        body["CancelReasonId"] = cancel_reason_id
    return api_post("/Order/v2/UpdateOrderStatus", body, api_key, secret_key, base_url)


# ── TERS AKIŞ: Webhook ayrıştırma ve mesaj formatlama ────────────────────────

WEBHOOK_ORDER_CREATED   = "order_created"
WEBHOOK_ORDER_CANCELED  = "order_canceled"
WEBHOOK_DELIVERY_STATUS = "delivery_status"
WEBHOOK_UNKNOWN         = "unknown"


def detect_webhook_type(p: dict) -> str:
    """Gelen webhook payload'unun tipini alan yapısına göre belirler."""
    if not isinstance(p, dict):
        return WEBHOOK_UNKNOWN
    if "deliveryStatus" in p:
        return WEBHOOK_DELIVERY_STATUS
    # Order Canceled modeli: {OrderId, StoreId, UserId} (baş harf büyük)
    if "OrderId" in p and "items" not in p and "customer" not in p:
        return WEBHOOK_ORDER_CANCELED
    # Order Created modeli: tam sipariş — id + items/customer/store
    if "id" in p and ("items" in p or "customer" in p or "store" in p):
        return WEBHOOK_ORDER_CREATED
    return WEBHOOK_UNKNOWN


def _penny(prices: dict, *keys) -> str:
    """prices içinden ilk bulunan anahtarın 'text' değerini döndürür."""
    for k in keys:
        node = (prices or {}).get(k) or {}
        if node.get("text"):
            return node["text"]
    return ""


def extract_order_fields(p: dict) -> dict:
    """Order Created payload'undan DB Order alanlarını çıkarır."""
    prices = p.get("prices") or {}
    total_penny = ((prices.get("total") or {}).get("amountAsPenny")) or 0
    payment = ((p.get("payment") or {}).get("type") or {})
    return {
        "external_id": str(p.get("id")),
        "order_number": str(p.get("id")),
        "status": p.get("status", "NEW_PENDING"),
        "total_price": round(total_penny / 100.0, 2),
        "payment_type": payment.get("name", ""),
        "app_source": "Migros Yemek",
        "customer_note": (p.get("extendedProperties") or {}).get("orderNote", "") or "",
    }


def format_order_created(p: dict) -> str:
    order_id = p.get("id", "N/A")
    store    = (p.get("store") or {}).get("name", "-")
    customer = (p.get("customer") or {}).get("fullName", "-")
    prices   = p.get("prices") or {}
    total    = _penny(prices, "total")
    discounted = _penny(prices, "discounted", "migrosDiscounted")

    provider = p.get("deliveryProvider", "")
    provider_map = {"RESTAURANT": "🏪 Restoran Kuryesi", "MIGROS": "🛵 Migros Kuryesi"}
    provider_label = provider_map.get(provider, provider or "-")

    payment = ((p.get("payment") or {}).get("type") or {})
    pay_label = payment.get("description") or payment.get("name", "-")

    # Ürünler
    items_text = ""
    for it in (p.get("items") or []):
        amount = it.get("amount", 1)
        name   = it.get("name", "?")
        items_text += f"  • {name} x{amount}\n"
        for op in (it.get("options") or []):
            opt = op.get("itemNames") or op.get("headerName")
            if opt:
                items_text += f"    ↳ {opt}\n"
        note = it.get("note")
        if note:
            items_text += f"    📝 {note}\n"
    if not items_text:
        items_text = f"  {p.get('description', '(ürün bilgisi yok)')}\n"

    ext = p.get("extendedProperties") or {}
    addr = ((p.get("customer") or {}).get("deliveryAddress") or {}).get("detail", "")

    msg = (
        f"🆕 <b>YENİ SİPARİŞ — Migros Yemek</b>\n"
        f"{'━'*28}\n"
        f"📋 <b>Sipariş No:</b> #{order_id}\n"
        f"🏪 <b>Şube:</b> {store}\n"
        f"👤 <b>Müşteri:</b> {customer}\n"
        f"{'━'*28}\n"
        f"🛍️ <b>Ürünler:</b>\n{items_text}"
        f"{'━'*28}\n"
        f"💰 <b>Tutar:</b> {total or '-'}\n"
    )
    if discounted and discounted != total:
        msg += f"🏷️ <b>İndirimli:</b> {discounted}\n"
    msg += (
        f"💳 <b>Ödeme:</b> {pay_label}\n"
        f"🚀 <b>Teslimat:</b> {provider_label}\n"
    )
    if addr:
        msg += f"📍 <b>Adres:</b> {addr}\n"
    if ext.get("orderNote"):
        msg += f"🗒️ <b>Not:</b> {ext['orderNote']}\n"
    flags = []
    if ext.get("ringDoorBell"):
        flags.append("🔔 Zili çal")
    if ext.get("contactlessDelivery"):
        flags.append("🤝 Temassız teslimat")
    if flags:
        msg += "ℹ️ " + " · ".join(flags) + "\n"
    return msg


def format_order_canceled(p: dict) -> str:
    order_id = p.get("OrderId") or p.get("orderId", "N/A")
    return (
        f"❌ <b>SİPARİŞ İPTAL EDİLDİ — Migros Yemek</b>\n"
        f"{'━'*28}\n"
        f"📋 <b>Sipariş No:</b> #{order_id}\n"
        f"ℹ️ Sipariş iptal/reddedildi.\n"
    )


_DELIVERY_MAP = {
    "ASSIGNED_FOR_DELIVERY": ("🧭", "Kurye atandı", "Siparişe kurye atandı."),
    "COURIER_APPROACHED":    ("📶", "Kurye yaklaşıyor", "Kurye restorana 1 km yaklaştı."),
    "COURIER_ARRIVED":       ("🏪", "Kurye ulaştı", "Kurye restorana ulaştı."),
    "IN_DELIVERY":           ("🛵", "Yolda", "Kurye siparişi teslimata çıkardı."),
    "DELIVERED":             ("🎉", "Teslim edildi", "Sipariş müşteriye teslim edildi."),
}


def format_delivery_status(p: dict) -> str:
    order_id = p.get("orderId", "N/A")
    ds = p.get("deliveryStatus", "")
    emoji, title, desc = _DELIVERY_MAP.get(ds, ("🚚", ds or "Kurye durumu", ""))
    courier = p.get("courierName")
    msg = (
        f"{emoji} <b>{title.upper()} — Migros Yemek</b>\n"
        f"{'━'*28}\n"
        f"📋 <b>Sipariş No:</b> #{order_id}\n"
    )
    if desc:
        msg += f"ℹ️ {desc}\n"
    if courier:
        msg += f"🧑‍🦯 <b>Kurye:</b> {courier}\n"
    return msg


# Sürüm işareti (senkron doğrulama için) — v1
__migros_version__ = "1.0"

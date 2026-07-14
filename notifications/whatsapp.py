"""WhatsApp bildirimi — Meta WhatsApp Cloud API.

Proaktif (müşteri bize yazmadan) bildirimlerde WhatsApp, önceden Meta onaylı
UTILITY şablon mesajı ister. Bu yüzden sipariş bildirimlerini `send_template`
ile göndeririz. `send_text` yalnızca 24 saatlik pencere içindeyken çalışır
(örn. kullanıcı bota yazdıysa) — test/opsiyonel amaçlıdır.

Gerekli env: WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID.
"""
import requests


def _endpoint(phone_number_id: str, version: str) -> str:
    return f"https://graph.facebook.com/{version}/{phone_number_id}/messages"


def _normalize_msisdn(number: str) -> str:
    """Numarayı WhatsApp'ın beklediği biçime getirir: sadece rakam, ülke koduyla.
    Örn: '0532 111 22 33' → '905321112233'. '+90...' → '90...'."""
    if not number:
        return ""
    digits = "".join(ch for ch in number if ch.isdigit())
    # Türkiye için baştaki 0'ı ülke koduyla değiştir
    if digits.startswith("0"):
        digits = "90" + digits[1:]
    # 10 haneli (5xxxxxxxxx) ise başına 90 ekle
    if len(digits) == 10 and digits.startswith("5"):
        digits = "90" + digits
    return digits


def send_template(to: str, template_name: str, lang: str, params: list,
                  token: str, phone_number_id: str, version: str = "v21.0"):
    """Onaylı şablon mesajı gönderir. params = body değişkenleri (sıralı liste).
    (ok: bool, hata: str|None) döner."""
    if not token or not phone_number_id:
        return False, "WhatsApp yapılandırması eksik (token/phone_number_id)"
    to = _normalize_msisdn(to)
    if not to:
        return False, "Geçersiz WhatsApp numarası"

    body = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": str(p)} for p in params],
            }],
        },
    }
    return _post(body, token, phone_number_id, version)


def send_text(to: str, text: str, token: str, phone_number_id: str, version: str = "v21.0"):
    """Serbest metin — SADECE 24 saatlik müşteri penceresi açıkken çalışır."""
    if not token or not phone_number_id:
        return False, "WhatsApp yapılandırması eksik"
    to = _normalize_msisdn(to)
    if not to:
        return False, "Geçersiz WhatsApp numarası"
    body = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text, "preview_url": False},
    }
    return _post(body, token, phone_number_id, version)


def _post(body: dict, token: str, phone_number_id: str, version: str):
    url = _endpoint(phone_number_id, version)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        r = requests.post(url, headers=headers, json=body, timeout=15)
        if r.status_code >= 400:
            # Meta hata gövdesini yakala (teşhis için)
            try:
                err = r.json().get("error", {}).get("message", r.text)
            except Exception:
                err = r.text
            print(f"[WHATSAPP HATA] HTTP {r.status_code}: {err}")
            return False, str(err)[:300]
        return True, None
    except requests.exceptions.RequestException as e:
        print(f"[WHATSAPP HATA] {e}")
        return False, str(e)[:300]

"""PayTR iFrame API istemcisi. Kart verisi bu uygulamadan gecmez."""
import base64
import hashlib
import hmac
import json
import secrets
import requests

TOKEN_URL = "https://www.paytr.com/odeme/api/get-token"


def _hmac(value, key):
    return base64.b64encode(hmac.new(key.encode(), value.encode(), hashlib.sha256).digest()).decode()


def merchant_oid():
    return "SG" + secrets.token_hex(20)


def iframe_token(config, oid, user, amount, ok_url, fail_url, ip):
    amount_kurus = str(int(round(amount * 100)))
    basket = base64.b64encode(json.dumps([["SiparisGeldi Pro Aylik Abonelik", f"{amount:.2f}", 1]], ensure_ascii=False, separators=(",", ":")).encode()).decode()
    payload = {
        "merchant_id": config["PAYTR_MERCHANT_ID"], "user_ip": ip[:39], "merchant_oid": oid,
        "email": user.email, "payment_amount": amount_kurus, "user_basket": basket,
        "no_installment": "0", "max_installment": "0", "user_name": user.name[:60],
        "user_address": str(config.get("COMPANY_ADDRESS", "Dijital hizmet aboneligi"))[:400],
        "user_phone": str(config.get("COMPANY_PHONE", "05000000000")).replace(" ", "")[:20],
        "merchant_ok_url": ok_url, "merchant_fail_url": fail_url, "timeout_limit": "30",
        "debug_on": "0", "test_mode": str(config.get("PAYTR_TEST_MODE", "1")), "lang": "tr",
    }
    sign = (payload["merchant_id"] + payload["user_ip"] + oid + payload["email"] + amount_kurus + basket +
            payload["no_installment"] + payload["max_installment"] + payload["user_name"] +
            payload["user_address"] + payload["user_phone"] + payload["merchant_ok_url"] +
            payload["merchant_fail_url"] + payload["timeout_limit"] + payload["debug_on"] + payload["test_mode"])
    payload["paytr_token"] = _hmac(sign + config["PAYTR_MERCHANT_SALT"], config["PAYTR_MERCHANT_KEY"])
    response = requests.post(TOKEN_URL, data=payload, timeout=(5, 20))
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "success" or not data.get("token"):
        raise ValueError(str(data.get("reason") or "PayTR token alınamadı")[:300])
    return data["token"]


def verify_callback(config, oid, status, total_amount, received):
    value = oid + config["PAYTR_MERCHANT_SALT"] + status + total_amount
    expected = _hmac(value, config["PAYTR_MERCHANT_KEY"])
    return hmac.compare_digest(expected, received or "")

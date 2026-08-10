"""Bildirim göndericisi — kullanıcının kanal tercihine göre iletir.

Telegram: zengin serbest metin (merkezi bot).
WhatsApp: Meta onaylı UTILITY şablonu (proaktif bildirim serbest metin olamaz).
  wa parametreleri = şablon gövde değişkenleri, sıralı: [olay, sipariş_no, ürünler, tutar]
"""
from flask import current_app
from . import telegram
from . import whatsapp


def _sanitize_wa_params(params: list) -> list:
    """WhatsApp şablon parametrelerini Meta'nın kabul edeceği hale getirir.

    Meta, şablon değişkenlerinde yeni satır, aşırı uzun metin ve özel
    karakterler (&, <, >, \u2028 vb.) kabul etmez; aksi halde mesaj hata
    verir ve hiç gönderilmez. HTML entity'leri deşifre edip güvenli
    temiz metin bırakır.
    """
    import html
    import re

    cleaned = []
    for p in params or []:
        s = str(p) if p is not None else ""
        s = html.unescape(s)
        s = re.sub(r"[<>\"']", "", s)
        s = s.replace("&", " ve ")
        s = s.replace("\u2028", " ").replace("\u2029", " ")
        s = " ".join(s.split())
        cleaned.append(s[:900])
    return cleaned


def send_to_user(user, telegram_text: str, wa: list = None, wa_template: str = None) -> bool:
    """Kullanıcının seçtiği kanal(lar)a bildirim gönderir.

    telegram_text: Telegram için tam biçimli mesaj.
    wa: WhatsApp şablon parametreleri (sıralı liste). None ise WhatsApp atlanır.
    wa_template: Kullanılacak WhatsApp şablon adı. None ise varsayılan sipariş
      şablonu (WHATSAPP_TEMPLATE_NAME) kullanılır. Raporlar için ayrı şablon geçilir.
    """
    if not user:
        return False
    channel = (user.notification_channel or "telegram").lower()
    if not getattr(user, "has_whatsapp_access", False) and channel in ("whatsapp", "both"):
        print(f"[BİLDİRİM] WhatsApp atlandı: WhatsApp erişimi yok, kanal telegram'a düştü (user={user.id})")
        channel = "telegram"
    any_sent = False

    # --- Telegram ---
    if channel in ("telegram", "both") and user.telegram_chat_id:
        token = current_app.config.get("TELEGRAM_BOT_TOKEN", "")
        if token:
            ok = telegram.send_message(token, user.telegram_chat_id, telegram_text)
            any_sent = any_sent or ok
        else:
            print("[BİLDİRİM] TELEGRAM_BOT_TOKEN yok")

    # --- WhatsApp ---
    if channel in ("whatsapp", "both") and getattr(user, "whatsapp_number", None) and wa:
        cfg = current_app.config
        token = cfg.get("WHATSAPP_ACCESS_TOKEN", "")
        pnid  = cfg.get("WHATSAPP_PHONE_NUMBER_ID", "")
        template = wa_template or cfg.get("WHATSAPP_TEMPLATE_NAME", "siparis_bildirim")
        if token and pnid:
            wa_params = _sanitize_wa_params(wa)
            print(f"[BİLDİRİM] WhatsApp gönderim deneniyor (user={user.id}, to={user.whatsapp_number}, template={template}, params={wa_params})")
            ok, err = whatsapp.send_template(
                to=user.whatsapp_number,
                template_name=template,
                lang=cfg.get("WHATSAPP_TEMPLATE_LANG", "tr"),
                params=wa_params,
                token=token,
                phone_number_id=pnid,
                version=cfg.get("WHATSAPP_API_VERSION", "v21.0"),
            )
            if not ok:
                print(f"[BİLDİRİM] WhatsApp gönderilemedi (user={user.id}): {err}")
            any_sent = any_sent or ok
        else:
            print(f"[BİLDİRİM] WhatsApp yapılandırması eksik (user={user.id})")
    elif channel in ("whatsapp", "both"):
        why = []
        if not getattr(user, "whatsapp_number", None):
            why.append("whatsapp_number boş")
        if not wa:
            why.append("wa parametreleri boş")
        print(f"[BİLDİRİM] WhatsApp atlandı (user={user.id}): {', '.join(why)}")

    return any_sent

"""Bildirim göndericisi — kullanıcının kanal tercihine göre iletir.

Telegram: zengin serbest metin (merkezi bot).
WhatsApp: Meta onaylı UTILITY şablonu (proaktif bildirim serbest metin olamaz).
  wa parametreleri = şablon gövde değişkenleri, sıralı: [olay, sipariş_no, tutar]
"""
from flask import current_app
from . import telegram
from . import whatsapp


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
            ok, err = whatsapp.send_template(
                to=user.whatsapp_number,
                template_name=template,
                lang=cfg.get("WHATSAPP_TEMPLATE_LANG", "tr"),
                params=wa,
                token=token,
                phone_number_id=pnid,
                version=cfg.get("WHATSAPP_API_VERSION", "v21.0"),
            )
            any_sent = any_sent or ok
        else:
            print(f"[BİLDİRİM] WhatsApp yapılandırması eksik (user={user.id})")

    return any_sent

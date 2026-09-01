"""Bildirim göndericisi — kullanıcının kanal tercihine göre iletir.

Telegram: zengin serbest metin (merkezi bot).
WhatsApp: Meta onaylı UTILITY şablonu (proaktif bildirim serbest metin olamaz).
  wa parametreleri = şablon gövde değişkenleri, sıralı:
  [başlık, sipariş_no, ürünler, tutar]
"""
from flask import current_app
from datetime import datetime
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
        s = re.sub(r"[<\">']", "", s)
        s = s.replace("&", " ve ")
        s = s.replace("\u2028", " ").replace("\u2029", " ")
        s = " ".join(s.split())
        cleaned.append(s[:900])
    return cleaned


def send_to_user(
    user,
    telegram_text: str,
    wa: list = None,
    wa_template: str = None,
    source: str = "",
) -> bool:
    """Kullanıcının seçtiği kanal(lar)a bildirim gönderir.

    telegram_text: Telegram için tam biçimli mesaj.
    wa: WhatsApp şablon parametreleri (sıralı liste). None ise WhatsApp atlanır.
    wa_template: Kullanılacak WhatsApp şablon adı. None ise varsayılan sipariş
      şablonu (WHATSAPP_TEMPLATE_NAME) kullanılır. Raporlar için ayrı şablon geçilir.
    """
    if not user:
        return False
    channel = (user.notification_channel or "telegram").lower()
    source_label = source or "genel"
    print(
        f"[BİLDİRİM {source_label}] başlangıç "
        f"user={user.id} channel={channel} access={getattr(user, 'has_whatsapp_access', False)} "
        f"numara={bool(getattr(user, 'whatsapp_number', None))} "
        f"wa_parametre={len(wa or [])}"
    )
    if not getattr(user, "has_whatsapp_access", False) and channel in ("whatsapp", "both"):
        print(f"[BİLDİRİM] WhatsApp erişimi yok, Telegram'a dönüldü (user={user.id})")
        channel = "telegram"
    any_sent = False

    # --- Telegram ---
    if channel in ("telegram", "both") and user.telegram_chat_id:
        token = current_app.config.get("TELEGRAM_BOT_TOKEN", "")
        if token:
            ok = telegram.send_message(token, user.telegram_chat_id, telegram_text)
            any_sent = any_sent or ok
            print(f"[BİLDİRİM {source_label}] Telegram {'ok' if ok else 'hata'} user={user.id}")
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
            ok, result = whatsapp.send_template(
                to=user.whatsapp_number,
                template_name=template,
                lang=cfg.get("WHATSAPP_TEMPLATE_LANG", "tr"),
                params=wa_params,
                token=token,
                phone_number_id=pnid,
                version=cfg.get("WHATSAPP_API_VERSION", "v21.0"),
            )
            any_sent = any_sent or ok
            if not ok:
                record_whatsapp_result(user, "failed", error=result)
                print(
                    f"[BİLDİRİM] WhatsApp gönderilemedi "
                    f"(source={source_label}, user={user.id}, template={template}): {result}"
                )
            else:
                record_whatsapp_result(user, "accepted", message_id=result)
                print(
                    f"[BİLDİRİM {source_label}] WhatsApp Meta'ya kabul edildi "
                    f"user={user.id} template={template} message_id={result or '-'}"
                )
        else:
            record_whatsapp_result(
                user,
                "skipped",
                error="WhatsApp yapılandırması eksik (token/phone_number_id)",
            )
            print(f"[BİLDİRİM] WhatsApp yapılandırması eksik (user={user.id})")
    elif channel in ("whatsapp", "both"):
        if not getattr(user, "whatsapp_number", None):
            record_whatsapp_result(user, "skipped", error="WhatsApp numarası eksik")
        elif not wa:
            record_whatsapp_result(user, "skipped", error="Şablon parametreleri yok")
        print(
            f"[BİLDİRİM] WhatsApp atlandı "
            f"(source={source_label}, user={user.id}, numara={bool(getattr(user, 'whatsapp_number', None))}, "
            f"parametre={bool(wa)})"
        )

    return any_sent


def record_whatsapp_result(user, status: str, message_id: str = None, error: str = None):
    """WhatsApp gönderim sonucunu ve Meta message ID'sini kullanıcıya kaydeder."""
    try:
        from extensions import db
        user.whatsapp_last_status = str(status or "unknown")[:30]
        user.whatsapp_last_status_at = datetime.utcnow()
        if message_id:
            user.whatsapp_last_message_id = str(message_id)[:200]
        user.whatsapp_last_error = str(error or "")[:300] or None
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        print(f"[WHATSAPP DURUM] sonuç kaydı yazılamadı (user={user.id}): {exc}")

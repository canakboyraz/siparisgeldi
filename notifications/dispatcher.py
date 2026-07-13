"""Bildirim göndericisi — merkezi bot üzerinden kullanıcının kanalına iletir."""
from flask import current_app
from . import telegram


def send_to_user(user, message: str) -> bool:
    """Kullanıcının bağlı Telegram hesabına merkezi bot ile mesaj gönderir."""
    if not user or not user.telegram_chat_id:
        print(f"[BİLDİRİM] Telegram bağlı değil (user={getattr(user, 'id', '?')})")
        return False

    bot_token = current_app.config.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        print("[BİLDİRİM] TELEGRAM_BOT_TOKEN yapılandırılmamış")
        return False

    return telegram.send_message(bot_token, user.telegram_chat_id, message)

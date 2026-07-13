"""Merkezi Telegram botu — mesaj gönderme ve /start ile hesap bağlama."""
import requests

API = "https://api.telegram.org/bot{token}/{method}"


def send_message(bot_token: str, chat_id: str, text: str) -> bool:
    """Merkezi bot üzerinden bir kullanıcıya mesaj gönderir."""
    if not bot_token or not chat_id:
        return False
    url = API.format(token=bot_token, method="sendMessage")
    try:
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        r.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"[TELEGRAM HATA] chat={chat_id}: {e}")
        return False


def get_updates(bot_token: str, offset: int = 0, timeout: int = 0) -> list:
    """Bota gelen güncellemeleri çeker (/start bağlama olayları için)."""
    if not bot_token:
        return []
    url = API.format(token=bot_token, method="getUpdates")
    try:
        r = requests.get(url, params={"offset": offset, "timeout": timeout}, timeout=timeout + 10)
        r.raise_for_status()
        return r.json().get("result", [])
    except requests.exceptions.RequestException as e:
        print(f"[TELEGRAM getUpdates HATA] {e}")
        return []


def parse_start_command(update: dict):
    """Bir güncellemeden /start payload'unu ve chat_id'yi çıkarır.

    Döner: (link_token, chat_id) veya (None, None)
    Kullanıcı 'https://t.me/BOT?start=<token>' linkine tıklayınca Telegram
    mesajı '/start <token>' olarak iletir.
    """
    msg = update.get("message") or update.get("edited_message") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if text.startswith("/start") and chat_id is not None:
        parts = text.split(maxsplit=1)
        token = parts[1].strip() if len(parts) > 1 else ""
        return (token or None), str(chat_id)
    return None, (str(chat_id) if chat_id is not None else None)

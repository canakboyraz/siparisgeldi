"""SMTP üzerinden e-posta gönderimi (şifre sıfırlama, e-posta doğrulama)."""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from flask import current_app

log = logging.getLogger(__name__)


def is_configured() -> bool:
    cfg = current_app.config
    return bool(cfg.get("SMTP_HOST") and (cfg.get("SMTP_FROM") or cfg.get("SMTP_USER")))


def send_email(to: str, subject: str, text: str, html: str = None) -> bool:
    """E-posta gönderir. SMTP tanımlı değilse veya hata olursa False döner."""
    cfg = current_app.config
    if not is_configured() or not to:
        log.warning("[EMAIL] SMTP tanımlı değil, gönderilmedi: to=%s subject=%s", to, subject)
        return False

    sender = cfg.get("SMTP_FROM") or cfg.get("SMTP_USER")
    name, addr = parseaddr(sender)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((name or cfg.get("COMPANY_BRAND_NAME", "SiparişGeldi"), addr))
    msg["To"] = to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    host, port = cfg.get("SMTP_HOST"), int(cfg.get("SMTP_PORT") or 587)
    user, password = cfg.get("SMTP_USER"), cfg.get("SMTP_PASSWORD")
    try:
        context = ssl.create_default_context()
        if cfg.get("SMTP_USE_SSL"):
            with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        log.info("[EMAIL] gönderildi to=%s subject=%s", to, subject)
        return True
    except Exception as e:  # noqa: BLE001 — gönderim hatası akışı bozmamalı
        log.error("[EMAIL] gönderilemedi to=%s: %s", to, e)
        return False


def _layout(title: str, body_html: str, button_text: str, url: str) -> str:
    return f"""<!doctype html><html lang="tr"><body style="margin:0;background:#f5f6f8;font-family:Arial,Helvetica,sans-serif;color:#1f2937">
<div style="max-width:520px;margin:24px auto;background:#fff;border-radius:12px;padding:28px">
<div style="font-weight:700;font-size:18px;margin-bottom:16px">SiparişGeldi</div>
<h2 style="font-size:20px;margin:0 0 12px">{title}</h2>
{body_html}
<p style="margin:24px 0"><a href="{url}" style="background:#ff5a2c;color:#fff;text-decoration:none;padding:12px 20px;border-radius:8px;font-weight:700;display:inline-block">{button_text}</a></p>
<p style="font-size:12px;color:#6b7280">Buton çalışmazsa bu adresi tarayıcına yapıştır:<br>{url}</p>
</div></body></html>"""


def send_password_reset(to: str, name: str, url: str) -> bool:
    text = (
        f"Merhaba {name},\n\n"
        "SiparişGeldi hesabın için şifre sıfırlama isteği aldık. Yeni şifre belirlemek için:\n"
        f"{url}\n\n"
        "Bağlantı 1 saat geçerlidir. Bu isteği sen yapmadıysan bu e-postayı yok sayabilirsin."
    )
    html = _layout(
        "Şifreni sıfırla",
        f"<p>Merhaba {name},</p><p>Hesabın için şifre sıfırlama isteği aldık. Bağlantı <b>1 saat</b> geçerlidir.</p>"
        "<p>Bu isteği sen yapmadıysan bu e-postayı yok sayabilirsin.</p>",
        "Yeni şifre belirle", url,
    )
    return send_email(to, "SiparişGeldi şifre sıfırlama", text, html)


def send_verification(to: str, name: str, url: str) -> bool:
    text = (
        f"Merhaba {name},\n\n"
        "SiparişGeldi'ye hoş geldin! E-posta adresini doğrulamak için:\n"
        f"{url}\n\n"
        "Doğrulama, şifreni unutursan hesabına geri dönebilmen için gerekli."
    )
    html = _layout(
        "E-posta adresini doğrula",
        f"<p>Merhaba {name}, SiparişGeldi'ye hoş geldin!</p>"
        "<p>Doğrulama, şifreni unutursan hesabına geri dönebilmen için gerekli.</p>",
        "E-postamı doğrula", url,
    )
    return send_email(to, "SiparişGeldi e-posta doğrulama", text, html)

"""Hassas verilerin (API secret) şifrelenmesi için yardımcılar (Fernet/AES)."""
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _cipher() -> Fernet:
    key = current_app.config.get("ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY tanımlı değil. .env dosyanıza ekleyin "
            '(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())").'
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    """Düz metni şifreler. Boş/None ise aynen döndürür."""
    if not plaintext:
        return plaintext or ""
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Şifreli metni çözer. Boşsa veya çözülemezse boş string döner."""
    if not ciphertext:
        return ""
    try:
        return _cipher().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        # Eski/şifrelenmemiş veri olabilir — güvenli tarafta kal
        return ""

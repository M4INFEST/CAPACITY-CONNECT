import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

from cryptography.fernet import Fernet, InvalidToken


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def encrypt_totp_secret(secret: str, key: bytes) -> str:
    return Fernet(key).encrypt(secret.encode("ascii")).decode("ascii")


def decrypt_totp_secret(ciphertext: str, key: bytes) -> str:
    try:
        return Fernet(key).decrypt(ciphertext.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError, UnicodeDecodeError) as error:
        raise ValueError("Stored MFA secret cannot be decrypted") from error


def verify_totp(secret: str, code: str, now: int | None = None) -> bool:
    return totp_counter_for_code(secret, code, now) is not None


def totp_counter_for_code(secret: str, code: str, now: int | None = None) -> int | None:
    normalized = code.replace(" ", "").replace("-", "")
    if len(normalized) != 6 or not normalized.isdigit():
        return None
    timestamp = int(time.time()) if now is None else now
    try:
        key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    except (ValueError, base64.binascii.Error):
        return None
    counter = timestamp // 30
    for candidate in (counter - 1, counter, counter + 1):
        if hmac.compare_digest(_totp_at_counter(key, candidate), normalized):
            return candidate
    return None


def _totp_at_counter(key: bytes, counter: int) -> str:
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary_code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{binary_code % 1_000_000:06d}"


def make_otpauth_uri(secret: str, email: str) -> str:
    label = f"Capacity Connect:{email}"
    query = urlencode(
        {
            "secret": secret,
            "issuer": "Capacity Connect",
            "algorithm": "SHA1",
            "digits": "6",
            "period": "30",
        }
    )
    return f"otpauth://totp/{quote(label, safe='')}?{query}"


def generate_recovery_codes(count: int = 10) -> list[str]:
    return [secrets.token_hex(16) for _ in range(count)]


def hash_recovery_code(code: str, pepper: bytes) -> str:
    normalized = code.strip().lower()
    return hmac.new(pepper, normalized.encode("ascii"), hashlib.sha256).hexdigest()


def hash_one_time_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def new_one_time_token() -> str:
    return secrets.token_urlsafe(32)

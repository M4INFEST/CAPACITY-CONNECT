import os

from cryptography.fernet import Fernet


def jwt_secret() -> bytes:
    value = os.getenv("AUTH_JWT_SECRET", "")
    if len(value) < 32:
        raise RuntimeError("AUTH_JWT_SECRET must contain at least 32 characters")
    return value.encode("utf-8")


def captcha_site_key() -> str:
    return os.getenv("CAPTCHA_SITE_KEY", "").strip()


def captcha_secret_key() -> str:
    return os.getenv("CAPTCHA_SECRET_KEY", "").strip()


def mfa_encryption_key() -> bytes:
    value = os.getenv("MFA_ENCRYPTION_KEY", "").strip()
    if not value:
        raise RuntimeError("MFA_ENCRYPTION_KEY must be configured to enable MFA")
    try:
        key = value.encode("ascii")
        Fernet(key)
    except (UnicodeEncodeError, ValueError) as error:
        raise RuntimeError("MFA_ENCRYPTION_KEY must be a valid Fernet key") from error
    return key


def database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL must be configured")
    return value

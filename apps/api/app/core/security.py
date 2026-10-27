import base64
import hashlib
import hmac
import json
import secrets
import time


_PASSWORD_ITERATIONS = 600_000
_DUMMY_SALT = b"capacity-connect-invalid-user"
_TOKEN_ISSUER = "capacity-connect"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS
    )
    return "$".join(
        (
            "pbkdf2_sha256",
            str(_PASSWORD_ITERATIONS),
            _base64url_encode(salt),
            _base64url_encode(digest),
        )
    )


def verify_password(password: str, encoded: str | None) -> bool:
    if encoded is None:
        hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _DUMMY_SALT, _PASSWORD_ITERATIONS
        )
        return False

    try:
        scheme, iterations_value, salt_value, digest_value = encoded.split("$")
        iterations = int(iterations_value)
        salt = _base64url_decode(salt_value)
        expected = _base64url_decode(digest_value)
    except (ValueError, TypeError):
        return False

    if scheme != "pbkdf2_sha256" or not 100_000 <= iterations <= 1_000_000:
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(actual, expected)


def create_access_token(
    subject: str,
    secret: bytes,
    now: int | None = None,
    expires_in: int = 1800,
    purpose: str = "access",
    auth_version: int = 0,
) -> str:
    issued_at = int(time.time()) if now is None else now
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": _TOKEN_ISSUER,
        "sub": subject,
        "iat": issued_at,
        "exp": issued_at + expires_in,
        "purpose": purpose,
        "ver": auth_version,
        "jti": secrets.token_urlsafe(16),
    }
    unsigned = ".".join(
        (
            _base64url_encode(json.dumps(header, separators=(",", ":")).encode()),
            _base64url_encode(json.dumps(payload, separators=(",", ":")).encode()),
        )
    )
    signature = hmac.new(secret, unsigned.encode("ascii"), hashlib.sha256).digest()
    return f"{unsigned}.{_base64url_encode(signature)}"


def decode_access_token(token: str, secret: bytes, now: int | None = None) -> str:
    claims = decode_access_token_claims(token, secret, now)
    if claims["purpose"] != "access":
        raise ValueError("A fully authenticated access token is required")
    return str(claims["sub"])


def decode_access_token_claims(
    token: str, secret: bytes, now: int | None = None
) -> dict[str, object]:
    try:
        header_value, payload_value, signature_value = token.split(".")
        unsigned = f"{header_value}.{payload_value}"
        signature = _base64url_decode(signature_value)
        expected = hmac.new(secret, unsigned.encode("ascii"), hashlib.sha256).digest()
        header = json.loads(_base64url_decode(header_value))
        payload = json.loads(_base64url_decode(payload_value))
        current_time = int(time.time()) if now is None else now
        if not isinstance(header, dict) or not isinstance(payload, dict):
            raise ValueError("Invalid access token")
        issued_at = payload["iat"]
        expires_at = payload["exp"]
        subject = payload["sub"]
        purpose = payload.get("purpose", "access")
        auth_version = payload.get("ver", 0)
        token_id = payload.get("jti", "legacy")
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise ValueError("Invalid access token") from error

    if (
        not isinstance(header, dict)
        or header.get("alg") != "HS256"
        or header.get("typ") != "JWT"
        or not isinstance(payload, dict)
        or payload.get("iss") != _TOKEN_ISSUER
        or not isinstance(subject, str)
        or not subject
        or not isinstance(purpose, str)
        or not isinstance(auth_version, int)
        or isinstance(auth_version, bool)
        or not isinstance(token_id, str)
        or not token_id
        or not isinstance(issued_at, int)
        or not isinstance(expires_at, int)
        or issued_at > current_time + 30
        or expires_at <= current_time
        or not hmac.compare_digest(signature, expected)
    ):
        raise ValueError("Invalid or expired access token")
    return {
        "sub": subject,
        "purpose": purpose,
        "ver": auth_version,
        "exp": expires_at,
        "jti": token_id,
    }


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

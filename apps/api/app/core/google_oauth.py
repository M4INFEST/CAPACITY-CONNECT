import json
from base64 import urlsafe_b64encode
from functools import partial
from hashlib import sha256
import os
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token


class GoogleOAuthError(RuntimeError):
    pass


def pkce_challenge(code_verifier: str) -> str:
    digest = sha256(code_verifier.encode("ascii")).digest()
    return urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def google_oauth_settings() -> tuple[str, str, str] | None:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv(
        "GOOGLE_REDIRECT_URI",
        "http://localhost:8000/api/v1/auth/google/callback",
    ).strip()
    if not client_id and not client_secret:
        return None
    if not client_id or not client_secret:
        raise GoogleOAuthError("Both Google OAuth client credentials must be configured")
    parsed = urlsplit(redirect_uri)
    local_http = parsed.scheme == "http" and parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not (parsed.scheme == "https" or local_http)
    ):
        raise GoogleOAuthError(
            "Google OAuth redirect URI must use HTTPS except for local development"
        )
    return client_id, client_secret, redirect_uri


def exchange_google_code(
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
    expected_nonce: str,
) -> dict[str, Any]:
    body = urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }
    ).encode("ascii")
    request = Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            token_response = json.loads(response.read())
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise GoogleOAuthError("Google sign-in could not reach the token service") from error
    if not isinstance(token_response, dict):
        raise GoogleOAuthError("Google returned an invalid token response")
    encoded_id_token = token_response.get("id_token")
    if not isinstance(encoded_id_token, str):
        raise GoogleOAuthError("Google did not return an identity token")
    try:
        claims = id_token.verify_oauth2_token(
            encoded_id_token,
            partial(GoogleRequest(), timeout=5),
            audience=client_id,
        )
    except (GoogleAuthError, ValueError, URLError, TimeoutError) as error:
        raise GoogleOAuthError("Google identity token could not be verified") from error
    if (
        claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}
        or claims.get("nonce") != expected_nonce
        or claims.get("email_verified") is not True
        or not isinstance(claims.get("sub"), str)
        or not claims["sub"]
        or not isinstance(claims.get("email"), str)
    ):
        raise GoogleOAuthError("Google identity claims are invalid or unverified")
    return claims

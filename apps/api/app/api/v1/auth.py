import json
import hmac
import logging
import secrets
import time
from collections.abc import Callable
from datetime import timedelta
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.security import (
    create_access_token,
    decode_access_token_claims,
    hash_password,
    verify_password,
)
from app.core.email import (
    EmailDeliveryError,
    email_delivery_configured,
    send_email,
    web_public_url,
)
from app.core.google_oauth import (
    GoogleOAuthError,
    exchange_google_code,
    google_oauth_settings,
    pkce_challenge,
)
from app.core.mfa import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_recovery_codes,
    generate_totp_secret,
    hash_one_time_token,
    hash_recovery_code,
    make_otpauth_uri,
    new_one_time_token,
    totp_counter_for_code,
)
from app.core.settings import (
    captcha_secret_key,
    captcha_site_key,
    jwt_secret,
    mfa_encryption_key,
)
from app.db import get_connection
from app.schemas.auth import (
    EmployerVerificationRequest,
    EmailRequest,
    EmailTokenRequest,
    GoogleOAuthExchangeRequest,
    LoginRequest,
    MfaCodeRequest,
    MfaDisableRequest,
    MfaEnrollmentResponse,
    MfaSetupRequest,
    MfaSetupResponse,
    MfaStatusResponse,
    PasswordResetRequest,
    RegisterRequest,
    RegistrationResponse,
    TrainerApplicationRequest,
    TokenResponse,
    TrainerDecisionRequest,
    UserResponse,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])
bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)
TOKEN_TTL_SECONDS = 1800
MFA_CHALLENGE_TTL_SECONDS = 300
MFA_SETUP_TTL_SECONDS = 600
EMAIL_VERIFICATION_TTL_HOURS = 24
PASSWORD_RESET_TTL_MINUTES = 30
MFA_FAILURE_LIMIT = 5
FAILURE_WINDOW_MINUTES = 15
CAPTCHA_FAILURE_THRESHOLD = 3
MAX_LOGIN_DELAY_SECONDS = 30
FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "yahoo.co.uk",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "icloud.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
}


def _request_ip(request: Request) -> str:
    if request.client is None:
        raise HTTPException(status_code=400, detail="Unable to determine client address")
    return request.client.host


def _verify_captcha(token: str | None, remote_ip: str) -> bool:
    secret = captcha_secret_key()
    if not secret or not captcha_site_key():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CAPTCHA verification is not configured",
        )
    if not token:
        return False
    body = urlencode(
        {"secret": secret, "response": token, "remoteip": remote_ip}
    ).encode("utf-8")
    request = UrlRequest(
        "https://www.google.com/recaptcha/api/siteverify",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read())
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CAPTCHA verification service is unavailable",
        ) from error
    return isinstance(result, dict) and result.get("success") is True


def _recent_failures(
    connection: psycopg.Connection, email: str, client_ip: str
) -> tuple[int, int]:
    row = connection.execute(
        """
        SELECT
          count(*) FILTER (WHERE lower(email) = lower(%s)) AS email_failures,
          count(*) FILTER (WHERE client_ip = %s::inet) AS ip_failures
        FROM auth_login_attempts
        WHERE succeeded = false
          AND attempted_at > now() - (%s * interval '1 minute')
        """,
        (email, client_ip, FAILURE_WINDOW_MINUTES),
    ).fetchone()
    return int(row["email_failures"]), int(row["ip_failures"])


def _login_delay(failure_count: int) -> int:
    if failure_count <= 0:
        return 0
    return min(2 ** min(failure_count - 1, 5), MAX_LOGIN_DELAY_SECONDS)


def _record_attempt(
    connection: psycopg.Connection, email: str, client_ip: str, succeeded: bool
) -> None:
    connection.execute(
        """
        INSERT INTO auth_login_attempts (email, client_ip, succeeded)
        VALUES (%s, %s::inet, %s)
        """,
        (email, client_ip, succeeded),
    )
    connection.execute(
        """
        INSERT INTO audit_events (action, entity_type, details)
        VALUES (%s, 'authentication', %s)
        """,
        (
            "auth_login_succeeded" if succeeded else "auth_login_failed",
            Jsonb({"succeeded": succeeded}),
        ),
    )


def _issue_email_token(
    connection: psycopg.Connection,
    user_id: UUID,
    purpose: str,
    lifetime: timedelta,
) -> str:
    token = new_one_time_token()
    connection.execute(
        "DELETE FROM auth_email_tokens WHERE expires_at < now() - interval '30 days'"
    )
    connection.execute(
        """
        UPDATE auth_email_tokens SET used_at = now()
        WHERE user_id = %s AND purpose = %s AND used_at IS NULL
        """,
        (user_id, purpose),
    )
    connection.execute(
        """
        INSERT INTO auth_email_tokens (user_id, purpose, token_hash, expires_at)
        VALUES (%s, %s, %s, now() + %s)
        """,
        (user_id, purpose, hash_one_time_token(token), lifetime),
    )
    return token


def _record_email_delivery_attempt(
    connection: psycopg.Connection,
    email: str,
    client_ip: str,
    purpose: str,
) -> None:
    email_hash = hmac.new(
        jwt_secret(), email.strip().lower().encode("utf-8"), "sha256"
    ).hexdigest()
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
        (purpose, email_hash),
    )
    attempts = connection.execute(
        """
        SELECT count(*) FILTER (WHERE email_hash = %s) AS email_count,
               count(*) FILTER (WHERE client_ip = %s::inet) AS ip_count
        FROM auth_email_delivery_attempts
        WHERE purpose = %s AND attempted_at > now() - interval '1 hour'
        """,
        (email_hash, client_ip, purpose),
    ).fetchone()
    if attempts["email_count"] >= 3 or attempts["ip_count"] >= 20:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many email requests. Try again later.",
        )
    connection.execute(
        """
        INSERT INTO auth_email_delivery_attempts (email_hash, client_ip, purpose)
        VALUES (%s, %s::inet, %s)
        """,
        (email_hash, client_ip, purpose),
    )
    connection.execute(
        "DELETE FROM auth_email_delivery_attempts WHERE attempted_at < now() - interval '1 day'"
    )
    connection.commit()


def _send_auth_email(email: str, path: str, token: str, purpose: str) -> None:
    link = f"{web_public_url()}{path}#token={token}"
    send_email(
        email,
        f"Capacity Connect {purpose}",
        f"Use this one-time link to {purpose.lower()}:\n\n{link}\n\n"
        "If you did not request this, you can ignore this message.",
    )


def _identity_from_token(
    credentials: HTTPAuthorizationCredentials | None,
    connection: psycopg.Connection,
    allowed_purposes: tuple[str, ...],
) -> tuple[UUID, dict[str, object], dict[str, object], list[str]]:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_access_token_claims(credentials.credentials, jwt_secret())
        user_id = UUID(str(claims["sub"]))
    except (ValueError, TypeError, RuntimeError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    if claims["purpose"] not in allowed_purposes:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This token cannot access the requested operation",
            headers={"WWW-Authenticate": "Bearer"},
        )

    with connection.cursor(row_factory=dict_row) as cursor:
        user = cursor.execute(
            """
            SELECT id, email, account_status, email_verified_at, auth_version, mfa_enabled
            FROM users WHERE id = %s
            """,
            (user_id,),
        ).fetchone()
        if (
            not user
            or user["account_status"] != "active"
            or user["email_verified_at"] is None
            or user["auth_version"] != claims["ver"]
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is unavailable or requires email verification",
            )
        role_rows = cursor.execute(
            "SELECT role::text AS role FROM user_roles WHERE user_id = %s ORDER BY role",
            (user_id,),
        ).fetchall()
    roles = [row["role"] for row in role_rows]
    if user["mfa_enabled"] is False and any(
        role in {"trainer", "employer", "admin"} for role in roles
    ) and "mfa_setup" not in allowed_purposes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Multi-factor authentication setup is required",
        )
    return user_id, claims, user, roles


def _employer_email_matches_company(email: str, website: str | None) -> bool:
    email_domain = email.rsplit("@", 1)[-1].lower()
    if any(
        email_domain == free_domain or email_domain.endswith(f".{free_domain}")
        for free_domain in FREE_EMAIL_DOMAINS
    ) or website is None:
        return False
    host = (
        urlsplit(website if "://" in website else f"https://{website}").hostname or ""
    ).lower()
    company_domain = host.removeprefix("www.")
    return bool(company_domain) and (
        email_domain == company_domain or email_domain.endswith(f".{company_domain}")
    )


def _login_response(
    connection: psycopg.Connection,
    user: dict[str, object],
    roles: list[str],
) -> TokenResponse:
    requires_mfa = any(role in {"trainer", "employer", "admin"} for role in roles)
    if user["mfa_enabled"]:
        connection.execute(
            "DELETE FROM auth_mfa_challenges WHERE expires_at < now() - interval '1 day'"
        )
        token = create_access_token(
            str(user["id"]),
            jwt_secret(),
            expires_in=MFA_CHALLENGE_TTL_SECONDS,
            purpose="mfa_challenge",
            auth_version=user["auth_version"],
        )
        connection.execute(
            """
            INSERT INTO auth_mfa_challenges (user_id, token_hash, expires_at)
            VALUES (%s, %s, now() + (%s * interval '1 second'))
            """,
            (user["id"], hash_one_time_token(token), MFA_CHALLENGE_TTL_SECONDS),
        )
        return TokenResponse(
            mfa_required=True,
            challenge_token=token,
            expires_in=MFA_CHALLENGE_TTL_SECONDS,
        )
    if requires_mfa:
        try:
            mfa_encryption_key()
        except (RuntimeError, UnicodeEncodeError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="MFA setup is unavailable until the encryption key is configured",
            ) from error
        token = create_access_token(
            str(user["id"]),
            jwt_secret(),
            expires_in=MFA_SETUP_TTL_SECONDS,
            purpose="mfa_setup",
            auth_version=user["auth_version"],
        )
        return TokenResponse(
            mfa_setup_required=True,
            setup_token=token,
            expires_in=MFA_SETUP_TTL_SECONDS,
        )
    token = create_access_token(
        str(user["id"]), jwt_secret(), auth_version=user["auth_version"]
    )
    return TokenResponse(access_token=token, expires_in=TOKEN_TTL_SECONDS)


@router.post("/auth/register", response_model=RegistrationResponse, status_code=201)
def register(
    payload: RegisterRequest,
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> RegistrationResponse:
    if not email_delivery_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email verification delivery is not configured",
        )
    if payload.role == "employer" and not payload.company_name:
        raise HTTPException(status_code=422, detail="company_name is required for employers")
    try:
        web_public_url()
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A secure verification-link origin is not configured",
        ) from error
    _record_email_delivery_attempt(
        connection, payload.email, _request_ip(request), "registration"
    )
    with connection.cursor(row_factory=dict_row) as cursor:
        existing = cursor.execute(
            "SELECT 1 FROM users WHERE lower(email) = lower(%s)", (payload.email,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        user = cursor.execute(
            """
            INSERT INTO users (email, password_hash, account_status)
            VALUES (%s, %s, 'pending')
            ON CONFLICT (lower(email)) DO NOTHING
            RETURNING id, email
            """,
            (payload.email, hash_password(payload.password)),
        ).fetchone()
        if not user:
            raise HTTPException(status_code=409, detail="An account with this email already exists")

        cursor.execute(
            "INSERT INTO user_roles (user_id, role) VALUES (%s, %s::app_role)",
            (user["id"], payload.role),
        )
        level = None
        if payload.role == "employer":
            cursor.execute(
                """
                INSERT INTO employer_profiles (user_id, company_name, website, industry)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    user["id"],
                    payload.company_name,
                    payload.website,
                    payload.industry,
                ),
            )
            level = 0
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'account_registered', 'user', %s, %s)
            """,
            (user["id"], user["id"], Jsonb({"role": payload.role})),
        )
        verification_token = _issue_email_token(
            connection,
            user["id"],
            "email_verification",
            timedelta(hours=EMAIL_VERIFICATION_TTL_HOURS),
        )
        connection.commit()
        result = RegistrationResponse(
            id=str(user["id"]),
            email=user["email"],
            roles=[payload.role],
            employer_verification_level=level,
        )
    try:
        _send_auth_email(
            user["email"], "/verify-email", verification_token, "email verification"
        )
    except EmailDeliveryError as error:
        logger.exception("Verification email delivery failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    return result


@router.post("/auth/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> TokenResponse:
    client_ip = _request_ip(request)
    failures_by_email, failures_by_ip = _recent_failures(
        connection, payload.email, client_ip
    )
    failure_count = max(failures_by_email, failures_by_ip)
    delay = _login_delay(failure_count)
    if delay:
        time.sleep(delay)

    if failure_count >= CAPTCHA_FAILURE_THRESHOLD:
        if not _verify_captcha(payload.captcha_token, client_ip):
            _record_attempt(connection, payload.email, client_ip, False)
            connection.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email, password, or CAPTCHA",
            )

    with connection.cursor(row_factory=dict_row) as cursor:
        user = cursor.execute(
            """
            SELECT id, email, password_hash, account_status, email_verified_at,
                   mfa_enabled, auth_version
            FROM users
            WHERE lower(email) = lower(%s)
            """,
            (payload.email,),
        ).fetchone()
        valid_password = verify_password(
            payload.password, user["password_hash"] if user else None
        )
        if not user or not valid_password or user["account_status"] not in {"active", "pending"}:
            _record_attempt(connection, payload.email, client_ip, False)
            connection.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        if user["email_verified_at"] is None:
            _record_attempt(connection, payload.email, client_ip, True)
            connection.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email verification is required before sign-in",
            )
        if user["account_status"] != "active":
            _record_attempt(connection, payload.email, client_ip, False)
            connection.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        role_rows = cursor.execute(
            "SELECT role::text AS role FROM user_roles WHERE user_id = %s",
            (user["id"],),
        ).fetchall()
        roles = [row["role"] for row in role_rows]
        _record_attempt(connection, payload.email, client_ip, True)
        connection.commit()
        return _login_response(connection, user, roles)


def _google_callback_url(error: str | None = None, code: str | None = None) -> str:
    destination = f"{web_public_url()}/auth/google/callback"
    if error:
        return f"{destination}?{urlencode({'error': error})}"
    if code:
        return f"{destination}#{urlencode({'code': code})}"
    raise ValueError("Google callback requires an error or exchange code")


def _resolve_google_user(
    connection: psycopg.Connection,
    google_sub: str,
    email: str,
) -> UUID:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext('google-sub'), hashtext(%s))",
            (google_sub,),
        )
        identity = cursor.execute(
            """
            SELECT user_id FROM user_google_identities
            WHERE google_sub = %s FOR UPDATE
            """,
            (google_sub,),
        ).fetchone()
        if identity:
            user_id = identity["user_id"]
            account = cursor.execute(
                "SELECT account_status FROM users WHERE id = %s FOR UPDATE",
                (user_id,),
            ).fetchone()
            if not account or account["account_status"] != "active":
                raise HTTPException(status_code=403, detail="This account is unavailable")
            cursor.execute(
                """
                UPDATE users SET email_verified_at = COALESCE(email_verified_at, now()),
                    updated_at = now() WHERE id = %s
                """,
                (user_id,),
            )
            return user_id

        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext('google-oauth'), hashtext(%s))",
            (email,),
        )
        account = cursor.execute(
            """
            SELECT id, account_status FROM users
            WHERE lower(email) = lower(%s) FOR UPDATE
            """,
            (email,),
        ).fetchone()
        if account and account["account_status"] not in {"active", "pending"}:
            raise HTTPException(status_code=403, detail="This account is unavailable")
        if account:
            linked_identity = cursor.execute(
                "SELECT google_sub FROM user_google_identities WHERE user_id = %s",
                (account["id"],),
            ).fetchone()
            if linked_identity and linked_identity["google_sub"] != google_sub:
                raise HTTPException(
                    status_code=409,
                    detail="A different Google account is already linked",
                )
            user_id = account["id"]
            cursor.execute(
                """
                UPDATE users SET email_verified_at = COALESCE(email_verified_at, now()),
                    account_status = 'active', updated_at = now()
                WHERE id = %s
                """,
                (user_id,),
            )
        else:
            user_id = cursor.execute(
                """
                INSERT INTO users (email, password_hash, email_verified_at, account_status)
                VALUES (%s, NULL, now(), 'active')
                RETURNING id
                """,
                (email,),
            ).fetchone()["id"]
            cursor.execute(
                "INSERT INTO user_roles (user_id, role) VALUES (%s, 'trainee')",
                (user_id,),
            )
            cursor.execute(
                """
                INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
                VALUES (%s, 'account_registered_google', 'user', %s, %s)
                """,
                (user_id, user_id, Jsonb({"provider": "google", "role": "trainee"})),
            )
        cursor.execute(
            """
            INSERT INTO user_google_identities (google_sub, user_id, email_snapshot)
            VALUES (%s, %s, %s)
            """,
            (google_sub, user_id, email),
        )
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'auth_google_identity_linked', 'user', %s, %s)
            """,
            (user_id, user_id, Jsonb({"provider": "google"})),
        )
        connection.commit()
    return user_id


@router.get("/auth/google/start")
def start_google_sign_in(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        settings = google_oauth_settings()
    except GoogleOAuthError:
        return RedirectResponse(
            _google_callback_url("google_not_configured"), status_code=303
        )
    if settings is None:
        return RedirectResponse(
            _google_callback_url("google_not_configured"), status_code=303
        )
    client_id, _, redirect_uri = settings
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    connection.execute(
        "DELETE FROM auth_google_oauth_states WHERE expires_at < now() - interval '1 day'"
    )
    attempts = connection.execute(
        """
        SELECT count(*) AS attempts FROM auth_google_oauth_states
        WHERE client_ip = %s::inet AND created_at > now() - interval '10 minutes'
        """,
        (_request_ip(request),),
    ).fetchone()["attempts"]
    if attempts >= 20:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many Google sign-in attempts. Try again later.",
        )
    connection.execute(
        """
        INSERT INTO auth_google_oauth_states
            (state_hash, nonce, code_verifier, client_ip, expires_at)
        VALUES (%s, %s, %s, %s::inet, now() + interval '5 minutes')
        """,
        (
            hash_one_time_token(state),
            nonce,
            code_verifier,
            _request_ip(request),
        ),
    )
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email",
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return RedirectResponse(
        f"https://accounts.google.com/o/oauth2/v2/auth?{query}", status_code=303
    )


@router.get("/auth/google/callback")
def complete_google_sign_in(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    if error:
        return RedirectResponse(
            _google_callback_url(
                "google_cancelled" if error == "access_denied" else "google_failed"
            ),
            status_code=303,
        )
    if not code or len(code) > 4096 or not state or len(state) > 256:
        return RedirectResponse(_google_callback_url("google_failed"), status_code=303)

    with connection.cursor(row_factory=dict_row) as cursor:
        oauth_state = cursor.execute(
            """
            SELECT nonce, code_verifier FROM auth_google_oauth_states
            WHERE state_hash = %s AND consumed_at IS NULL AND expires_at > now()
            FOR UPDATE
            """,
            (hash_one_time_token(state),),
        ).fetchone()
        if not oauth_state:
            return RedirectResponse(
                _google_callback_url("google_state_invalid"), status_code=303
            )
        cursor.execute(
            "UPDATE auth_google_oauth_states SET consumed_at = now() WHERE state_hash = %s",
            (hash_one_time_token(state),),
        )
        connection.commit()

    try:
        settings = google_oauth_settings()
        if settings is None:
            raise GoogleOAuthError("Google sign-in is not configured")
        client_id, client_secret, redirect_uri = settings
        claims = exchange_google_code(
            code,
            oauth_state["code_verifier"],
            redirect_uri,
            client_id,
            client_secret,
            oauth_state["nonce"],
        )
    except GoogleOAuthError:
        logger.warning("Google OAuth token exchange or identity validation failed")
        return RedirectResponse(
            _google_callback_url("google_verification_failed"), status_code=303
        )

    email = claims["email"].strip().lower()
    if (
        len(email) > 320
        or len(claims["sub"]) > 255
        or email.count("@") != 1
        or any(char.isspace() for char in email)
    ):
        return RedirectResponse(_google_callback_url("google_identity_invalid"), status_code=303)
    try:
        user_id = _resolve_google_user(connection, claims["sub"], email)
    except HTTPException as account_error:
        reason = (
            "google_account_unavailable"
            if account_error.status_code == 403
            else "google_account_link_conflict"
        )
        return RedirectResponse(_google_callback_url(reason), status_code=303)

    transfer_code = new_one_time_token()
    connection.execute(
        """DELETE FROM auth_google_login_codes WHERE expires_at < now()"""
    )
    connection.execute(
        """
        INSERT INTO auth_google_login_codes (code_hash, user_id, expires_at)
        VALUES (%s, %s, now() + interval '90 seconds')
        """,
        (hash_one_time_token(transfer_code), user_id),
    )
    connection.commit()
    return RedirectResponse(_google_callback_url(code=transfer_code), status_code=303)


@router.post("/auth/google/exchange", response_model=TokenResponse)
def exchange_google_login_code(
    payload: GoogleOAuthExchangeRequest,
    connection: psycopg.Connection = Depends(get_connection),
) -> TokenResponse:
    with connection.cursor(row_factory=dict_row) as cursor:
        transfer = cursor.execute(
            """
            SELECT code_hash, user_id FROM auth_google_login_codes
            WHERE code_hash = %s AND consumed_at IS NULL AND expires_at > now()
            FOR UPDATE
            """,
            (hash_one_time_token(payload.code),),
        ).fetchone()
        if not transfer:
            raise HTTPException(status_code=400, detail="Google sign-in code is invalid or expired")
        cursor.execute(
            "UPDATE auth_google_login_codes SET consumed_at = now() WHERE code_hash = %s",
            (transfer["code_hash"],),
        )
        user = cursor.execute(
            """
            SELECT id, email, account_status, email_verified_at, mfa_enabled, auth_version
            FROM users WHERE id = %s
            """,
            (transfer["user_id"],),
        ).fetchone()
        if (
            not user
            or user["account_status"] != "active"
            or user["email_verified_at"] is None
        ):
            raise HTTPException(status_code=403, detail="This account is unavailable")
        role_rows = cursor.execute(
            "SELECT role::text AS role FROM user_roles WHERE user_id = %s",
            (user["id"],),
        ).fetchall()
        roles = [row["role"] for row in role_rows]
        if not roles:
            raise HTTPException(status_code=403, detail="This account has no assigned role")
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'auth_google_login_succeeded', 'user', %s, %s)
            """,
            (user["id"], user["id"], Jsonb({"provider": "google"})),
        )
        return _login_response(connection, user, roles)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    connection: psycopg.Connection = Depends(get_connection),
) -> UserResponse:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_access_token_claims(credentials.credentials, jwt_secret())
        user_id = UUID(str(claims["sub"]))
    except (ValueError, TypeError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    if claims["purpose"] != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A fully authenticated access token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    with connection.cursor(row_factory=dict_row) as cursor:
        user = cursor.execute(
            """
            SELECT u.id, u.email, u.account_status, u.email_verified_at,
                   u.auth_version, u.mfa_enabled, ep.verification_level
            FROM users u
            LEFT JOIN employer_profiles ep ON ep.user_id = u.id
            WHERE u.id = %s
            """,
            (user_id,),
        ).fetchone()
        if (
            not user
            or user["account_status"] != "active"
            or user["email_verified_at"] is None
            or user["auth_version"] != claims["ver"]
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is unavailable or requires email verification",
            )
        role_rows = cursor.execute(
            "SELECT role::text AS role FROM user_roles WHERE user_id = %s ORDER BY role",
            (user_id,),
        ).fetchall()
    roles = [row["role"] for row in role_rows]
    if any(role in {"trainer", "employer", "admin"} for role in roles) and not user["mfa_enabled"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Multi-factor authentication setup is required",
        )
    return UserResponse(
        id=str(user["id"]),
        email=user["email"],
        roles=roles,
        employer_verification_level=user["verification_level"],
    )


@router.post("/auth/email/verify")
def verify_email(
    payload: EmailTokenRequest,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        token = cursor.execute(
            """
            SELECT id, user_id FROM auth_email_tokens
            WHERE token_hash = %s AND purpose = 'email_verification'
              AND used_at IS NULL AND expires_at > now()
            FOR UPDATE
            """,
            (hash_one_time_token(payload.token),),
        ).fetchone()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This verification link is invalid or expired",
            )
        cursor.execute(
            """
            UPDATE users
            SET email_verified_at = now(),
                account_status = CASE WHEN account_status = 'pending'
                                      THEN 'active' ELSE account_status END,
                updated_at = now()
            WHERE id = %s
            """,
            (token["user_id"],),
        )
        cursor.execute(
            "UPDATE auth_email_tokens SET used_at = now() WHERE id = %s",
            (token["id"],),
        )
        cursor.execute(
            """
            UPDATE auth_email_tokens SET used_at = now()
            WHERE user_id = %s AND purpose = 'email_verification'
              AND used_at IS NULL
            """,
            (token["user_id"],),
        )
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id)
            VALUES (%s, 'email_verified', 'user', %s)
            """,
            (token["user_id"], token["user_id"]),
        )
    return {"status": "verified", "message": "Email verified. You can now sign in."}


@router.post("/auth/email/resend")
def resend_verification_email(
    payload: EmailRequest,
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    if not email_delivery_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email verification delivery is not configured",
        )
    _record_email_delivery_attempt(
        connection, payload.email, _request_ip(request), "verification"
    )
    with connection.cursor(row_factory=dict_row) as cursor:
        user = cursor.execute(
            """
            SELECT id, email FROM users
            WHERE lower(email) = lower(%s) AND email_verified_at IS NULL
            """,
            (payload.email,),
        ).fetchone()
        if not user:
            return {"message": "If the account needs verification, a link will be sent."}
        token = _issue_email_token(
            connection,
            user["id"],
            "email_verification",
            timedelta(hours=EMAIL_VERIFICATION_TTL_HOURS),
        )
        connection.commit()
    try:
        _send_auth_email(user["email"], "/verify-email", token, "email verification")
    except EmailDeliveryError as error:
        logger.exception("Verification email delivery failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    return {"message": "If the account needs verification, a link will be sent."}


@router.post("/auth/password/forgot")
def request_password_reset(
    payload: EmailRequest,
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    if not email_delivery_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password recovery email delivery is not configured",
        )
    _record_email_delivery_attempt(
        connection, payload.email, _request_ip(request), "password_reset"
    )
    with connection.cursor(row_factory=dict_row) as cursor:
        user = cursor.execute(
            """
            SELECT id, email FROM users
            WHERE lower(email) = lower(%s) AND account_status = 'active'
              AND email_verified_at IS NOT NULL
            """,
            (payload.email,),
        ).fetchone()
        if not user:
            return {"message": "If the account is eligible, a reset link will be sent."}
        token = _issue_email_token(
            connection,
            user["id"],
            "password_reset",
            timedelta(minutes=PASSWORD_RESET_TTL_MINUTES),
        )
        connection.commit()
    try:
        _send_auth_email(
            user["email"], "/reset-password", token, "password reset"
        )
    except EmailDeliveryError as error:
        logger.exception("Password reset email delivery failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    return {"message": "If the account is eligible, a reset link will be sent."}


@router.post("/auth/password/reset")
def reset_password(
    payload: PasswordResetRequest,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        token = cursor.execute(
            """
            SELECT id, user_id FROM auth_email_tokens
            WHERE token_hash = %s AND purpose = 'password_reset'
              AND used_at IS NULL AND expires_at > now()
            FOR UPDATE
            """,
            (hash_one_time_token(payload.token),),
        ).fetchone()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This password reset link is invalid or expired",
            )
        cursor.execute(
            """
            UPDATE users
            SET password_hash = %s, auth_version = auth_version + 1, updated_at = now()
            WHERE id = %s
            """,
            (hash_password(payload.password), token["user_id"]),
        )
        cursor.execute(
            "UPDATE auth_email_tokens SET used_at = now() WHERE id = %s",
            (token["id"],),
        )
        cursor.execute(
            """
            UPDATE auth_email_tokens SET used_at = now()
            WHERE user_id = %s AND purpose = 'password_reset' AND used_at IS NULL
            """,
            (token["user_id"],),
        )
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id)
            VALUES (%s, 'password_reset_completed', 'user', %s)
            """,
            (token["user_id"], token["user_id"]),
        )
    return {"message": "Password reset. Sign in using your new password."}


@router.post("/auth/mfa/setup", response_model=MfaSetupResponse)
def begin_mfa_setup(
    payload: MfaSetupRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    connection: psycopg.Connection = Depends(get_connection),
) -> MfaSetupResponse:
    user_id, claims, user, _ = _identity_from_token(
        credentials, connection, ("access", "mfa_setup")
    )
    with connection.cursor(row_factory=dict_row) as cursor:
        stored_password = cursor.execute(
            "SELECT password_hash FROM users WHERE id = %s", (user_id,)
        ).fetchone()
        if claims["purpose"] == "access" and (
            not payload.password
            or not verify_password(payload.password, stored_password["password_hash"])
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Re-enter your current password to set up MFA",
            )
        if user["mfa_enabled"]:
            raise HTTPException(status_code=409, detail="MFA is already enabled")
        try:
            key = mfa_encryption_key()
            secret = generate_totp_secret()
            encrypted_secret = encrypt_totp_secret(secret, key)
        except (RuntimeError, ValueError, UnicodeEncodeError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="MFA encryption is not configured correctly",
            ) from error
        cursor.execute(
            """
            INSERT INTO user_mfa (user_id, pending_secret_ciphertext)
            VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
              pending_secret_ciphertext = EXCLUDED.pending_secret_ciphertext,
              failed_attempts = 0, locked_until = NULL, updated_at = now()
            """,
            (user_id, encrypted_secret),
        )
    return MfaSetupResponse(
        secret=secret,
        otpauth_uri=make_otpauth_uri(secret, user["email"]),
    )


@router.get("/auth/mfa/status", response_model=MfaStatusResponse)
def get_mfa_status(
    user: UserResponse = Depends(current_user),
    connection: psycopg.Connection = Depends(get_connection),
) -> MfaStatusResponse:
    row = connection.execute(
        """
        SELECT u.mfa_enabled,
               count(rc.id) FILTER (WHERE rc.used_at IS NULL) AS recovery_codes_remaining
        FROM users u
        LEFT JOIN user_mfa_recovery_codes rc ON rc.user_id = u.id
        WHERE u.id = %s
        GROUP BY u.id
        """,
        (UUID(user.id),),
    ).fetchone()
    return MfaStatusResponse(
        enabled=row["mfa_enabled"],
        recovery_codes_remaining=int(row["recovery_codes_remaining"]),
    )


@router.post("/auth/mfa/disable")
def disable_optional_mfa(
    payload: MfaDisableRequest,
    user: UserResponse = Depends(current_user),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    if any(role in {"trainer", "employer", "admin"} for role in user.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA is mandatory for trainer, employer, and admin accounts",
        )
    user_id = UUID(user.id)
    with connection.cursor(row_factory=dict_row) as cursor:
        account = cursor.execute(
            "SELECT password_hash FROM users WHERE id = %s FOR UPDATE",
            (user_id,),
        ).fetchone()
        mfa = cursor.execute(
            "SELECT * FROM user_mfa WHERE user_id = %s FOR UPDATE", (user_id,)
        ).fetchone()
        if not mfa or not mfa["secret_ciphertext"]:
            raise HTTPException(status_code=409, detail="MFA is not enabled")
        now = cursor.execute("SELECT now() AS current_time").fetchone()["current_time"]
        if mfa["locked_until"] and mfa["locked_until"] > now:
            raise HTTPException(status_code=429, detail="MFA verification is temporarily locked")
        if not verify_password(payload.password, account["password_hash"]):
            failures = (
                0
                if mfa["locked_until"] and mfa["locked_until"] <= now
                else mfa["failed_attempts"]
            )
            _record_mfa_failure(connection, user_id, failures)
            raise HTTPException(status_code=401, detail="Current password is incorrect")
        try:
            secret = decrypt_totp_secret(
                mfa["secret_ciphertext"], mfa_encryption_key()
            )
        except (RuntimeError, ValueError, UnicodeEncodeError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="MFA encryption key is unavailable or invalid",
            ) from error
        recovery_hash = hash_recovery_code(payload.code, jwt_secret())
        recovery = cursor.execute(
            """
            SELECT id FROM user_mfa_recovery_codes
            WHERE user_id = %s AND code_hash = %s AND used_at IS NULL
            FOR UPDATE
            """,
            (user_id, recovery_hash),
        ).fetchone()
        counter = totp_counter_for_code(secret, payload.code)
        valid_totp = (
            counter is not None
            and (mfa["last_totp_counter"] is None or counter > mfa["last_totp_counter"])
        )
        if not valid_totp and not recovery:
            failures = (
                0
                if mfa["locked_until"] and mfa["locked_until"] <= now
                else mfa["failed_attempts"]
            )
            _record_mfa_failure(connection, user_id, failures)
            raise HTTPException(status_code=401, detail="Invalid authenticator or recovery code")
        if recovery:
            cursor.execute(
                "UPDATE user_mfa_recovery_codes SET used_at = now() WHERE id = %s",
                (recovery["id"],),
            )
        cursor.execute("DELETE FROM user_mfa_recovery_codes WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM user_mfa WHERE user_id = %s", (user_id,))
        cursor.execute(
            """
            UPDATE users SET mfa_enabled = false, auth_version = auth_version + 1,
                updated_at = now() WHERE id = %s
            """,
            (user_id,),
        )
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'mfa_disabled', 'user', %s, %s)
            """,
            (user_id, user_id, Jsonb({"recovery_code_used": bool(recovery)})),
        )
    return {"status": "disabled", "message": "MFA disabled. Sign in again to continue."}


@router.post("/auth/mfa/confirm", response_model=MfaEnrollmentResponse)
def confirm_mfa_setup(
    payload: MfaCodeRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    connection: psycopg.Connection = Depends(get_connection),
) -> MfaEnrollmentResponse:
    user_id, claims, user, _ = _identity_from_token(
        credentials, connection, ("access", "mfa_setup")
    )
    with connection.cursor(row_factory=dict_row) as cursor:
        mfa = cursor.execute(
            "SELECT * FROM user_mfa WHERE user_id = %s FOR UPDATE", (user_id,)
        ).fetchone()
        if not mfa or not mfa["pending_secret_ciphertext"]:
            raise HTTPException(status_code=409, detail="Begin MFA setup before confirming it")
        current_time = connection.execute(
            "SELECT now() AS current_time"
        ).fetchone()["current_time"]
        if mfa["locked_until"] and mfa["locked_until"] > current_time:
            raise HTTPException(status_code=429, detail="MFA setup is temporarily locked")
        try:
            secret = decrypt_totp_secret(
                mfa["pending_secret_ciphertext"], mfa_encryption_key()
            )
        except (RuntimeError, ValueError, UnicodeEncodeError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="MFA encryption key is unavailable or invalid",
            ) from error
        totp_counter = totp_counter_for_code(secret, payload.code)
        if totp_counter is None:
            failures = (
                0
                if mfa["locked_until"] and mfa["locked_until"] <= current_time
                else mfa["failed_attempts"]
            )
            _record_mfa_failure(connection, user_id, failures)
            raise HTTPException(status_code=401, detail="Invalid authenticator code")
        recovery_codes = generate_recovery_codes()
        pepper = jwt_secret()
        cursor.execute(
            "DELETE FROM user_mfa_recovery_codes WHERE user_id = %s", (user_id,)
        )
        cursor.executemany(
            """
            INSERT INTO user_mfa_recovery_codes (user_id, code_hash)
            VALUES (%s, %s)
            """,
            [(user_id, hash_recovery_code(code, pepper)) for code in recovery_codes],
        )
        cursor.execute(
            """
            UPDATE user_mfa
            SET secret_ciphertext = pending_secret_ciphertext,
                pending_secret_ciphertext = NULL, failed_attempts = 0,
                locked_until = NULL, last_totp_counter = %s, updated_at = now()
            WHERE user_id = %s
            """,
            (totp_counter, user_id),
        )
        updated_user = cursor.execute(
            """
            UPDATE users
            SET mfa_enabled = true, auth_version = auth_version + 1, updated_at = now()
            WHERE id = %s
            RETURNING auth_version
            """,
            (user_id,),
        ).fetchone()
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id)
            VALUES (%s, 'mfa_enabled', 'user', %s)
            """,
            (user_id, user_id),
        )
        access_token = create_access_token(
            str(user_id), jwt_secret(), auth_version=updated_user["auth_version"]
        )
    return MfaEnrollmentResponse(
        recovery_codes=recovery_codes,
        access_token=access_token,
    )


@router.post("/auth/mfa/verify", response_model=TokenResponse)
def verify_login_mfa(
    payload: MfaCodeRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    connection: psycopg.Connection = Depends(get_connection),
) -> TokenResponse:
    if credentials is None:
        raise HTTPException(status_code=401, detail="MFA challenge token is required")
    try:
        claims = decode_access_token_claims(credentials.credentials, jwt_secret())
        user_id = UUID(str(claims["sub"]))
    except (ValueError, TypeError, RuntimeError) as error:
        raise HTTPException(status_code=401, detail="Invalid or expired MFA challenge") from error
    if claims["purpose"] != "mfa_challenge":
        raise HTTPException(status_code=401, detail="Invalid MFA challenge")

    with connection.cursor(row_factory=dict_row) as cursor:
        challenge = cursor.execute(
            """
            SELECT id, user_id FROM auth_mfa_challenges
            WHERE user_id = %s AND token_hash = %s AND consumed_at IS NULL
              AND expires_at > now()
            FOR UPDATE
            """,
            (user_id, hash_one_time_token(credentials.credentials)),
        ).fetchone()
        user = cursor.execute(
            """
            SELECT email, account_status, email_verified_at, auth_version, mfa_enabled
            FROM users WHERE id = %s
            """,
            (user_id,),
        ).fetchone()
        if (
            not challenge
            or not user
            or user["account_status"] != "active"
            or user["email_verified_at"] is None
            or user["auth_version"] != claims["ver"]
            or not user["mfa_enabled"]
        ):
            raise HTTPException(status_code=401, detail="Invalid or expired MFA challenge")
        mfa = cursor.execute(
            "SELECT * FROM user_mfa WHERE user_id = %s FOR UPDATE", (user_id,)
        ).fetchone()
        if not mfa or not mfa["secret_ciphertext"]:
            raise HTTPException(status_code=401, detail="MFA is not configured")
        now = cursor.execute("SELECT now() AS current_time").fetchone()["current_time"]
        if mfa["locked_until"] and mfa["locked_until"] > now:
            raise HTTPException(status_code=429, detail="MFA verification is temporarily locked")
        try:
            secret = decrypt_totp_secret(
                mfa["secret_ciphertext"], mfa_encryption_key()
            )
        except (RuntimeError, ValueError, UnicodeEncodeError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="MFA encryption key is unavailable or invalid",
            ) from error
        recovery_code_hash = hash_recovery_code(payload.code, jwt_secret())
        recovery = cursor.execute(
            """
            SELECT id FROM user_mfa_recovery_codes
            WHERE user_id = %s AND code_hash = %s AND used_at IS NULL
            FOR UPDATE
            """,
            (user_id, recovery_code_hash),
        ).fetchone()
        totp_counter = totp_counter_for_code(secret, payload.code)
        is_valid_totp = (
            totp_counter is not None
            and (
                mfa["last_totp_counter"] is None
                or totp_counter > mfa["last_totp_counter"]
            )
        )
        if not is_valid_totp and not recovery:
            failures = (
                0
                if mfa["locked_until"] and mfa["locked_until"] <= now
                else mfa["failed_attempts"]
            )
            _record_mfa_failure(connection, user_id, failures)
            raise HTTPException(status_code=401, detail="Invalid authenticator or recovery code")
        cursor.execute(
            "UPDATE auth_mfa_challenges SET consumed_at = now() WHERE id = %s",
            (challenge["id"],),
        )
        if recovery:
            cursor.execute(
                "UPDATE user_mfa_recovery_codes SET used_at = now() WHERE id = %s",
                (recovery["id"],),
            )
        elif is_valid_totp:
            cursor.execute(
                "UPDATE user_mfa SET last_totp_counter = %s WHERE user_id = %s",
                (totp_counter, user_id),
            )
        cursor.execute(
            """
            UPDATE user_mfa SET failed_attempts = 0, locked_until = NULL,
                updated_at = now() WHERE user_id = %s
            """,
            (user_id,),
        )
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'mfa_login_succeeded', 'user', %s, %s)
            """,
            (
                user_id,
                user_id,
                Jsonb({"recovery_code_used": bool(recovery)}),
            ),
        )
        token = create_access_token(
            str(user_id), jwt_secret(), auth_version=int(user["auth_version"])
        )
    return TokenResponse(access_token=token, expires_in=TOKEN_TTL_SECONDS)


def _record_mfa_failure(
    connection: psycopg.Connection, user_id: UUID, current_failures: int
) -> None:
    failures = current_failures + 1
    lock = failures >= MFA_FAILURE_LIMIT
    connection.execute(
        """
        UPDATE user_mfa
        SET failed_attempts = %s,
            locked_until = CASE WHEN %s THEN now() + interval '15 minutes'
                                ELSE locked_until END,
            updated_at = now()
        WHERE user_id = %s
        """,
        (failures, lock, user_id),
    )
    connection.execute(
        """
        INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
        VALUES (%s, 'mfa_verification_failed', 'user', %s, %s)
        """,
        (user_id, user_id, Jsonb({"failed_attempts": failures, "locked": lock})),
    )
    connection.commit()


def require_role(role: str) -> Callable[..., UserResponse]:
    def dependency(user: UserResponse = Depends(current_user)) -> UserResponse:
        if role not in user.roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency


@router.get("/auth/me", response_model=UserResponse)
def get_me(user: UserResponse = Depends(current_user)) -> UserResponse:
    return user


@router.post("/roles/trainer/apply", status_code=201)
def apply_as_trainer(
    payload: TrainerApplicationRequest,
    user: UserResponse = Depends(current_user),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    if "trainer" in user.roles:
        raise HTTPException(status_code=409, detail="User is already an approved trainer")
    with connection.cursor(row_factory=dict_row) as cursor:
        pending = cursor.execute(
            """
            SELECT id FROM trainer_applications
            WHERE user_id = %s AND status = 'pending'
            ORDER BY submitted_at DESC LIMIT 1
            """,
            (UUID(user.id),),
        ).fetchone()
        if pending:
            raise HTTPException(status_code=409, detail="A trainer application is already pending")
        application = cursor.execute(
            """
            INSERT INTO trainer_applications (user_id, expertise)
            VALUES (%s, %s)
            RETURNING id
            """,
            (UUID(user.id), payload.expertise),
        ).fetchone()
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'trainer_application_submitted', 'trainer_application', %s, %s)
            """,
            (
                UUID(user.id),
                application["id"],
                Jsonb({"expertise_count": len(payload.expertise)}),
            ),
        )
    return {"application_id": str(application["id"]), "status": "pending"}


@router.get("/roles/trainer/applications/me")
def get_my_trainer_application(
    user: UserResponse = Depends(current_user),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object] | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        application = cursor.execute(
            """
            SELECT id, expertise, status::text AS status, submitted_at,
                   reviewed_at, review_reason
            FROM trainer_applications
            WHERE user_id = %s
            ORDER BY submitted_at DESC
            LIMIT 1
            """,
            (UUID(user.id),),
        ).fetchone()
    if not application:
        return None
    return {
        "application_id": str(application["id"]),
        "expertise": application["expertise"],
        "status": application["status"],
        "submitted_at": application["submitted_at"].isoformat(),
        "reviewed_at": application["reviewed_at"].isoformat()
        if application["reviewed_at"]
        else None,
        "review_reason": application["review_reason"],
    }


@router.get("/admin/trainer-applications")
def list_trainer_applications(
    _: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, object]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        records = cursor.execute(
            """
            SELECT ta.id, ta.user_id, u.email, ta.expertise, ta.status::text AS status,
                   ta.submitted_at
            FROM trainer_applications ta
            JOIN users u ON u.id = ta.user_id
            WHERE ta.status = 'pending'
            ORDER BY ta.submitted_at
            """
        ).fetchall()
    return [
        {
            **record,
            "id": str(record["id"]),
            "user_id": str(record["user_id"]),
            "submitted_at": record["submitted_at"].isoformat(),
        }
        for record in records
    ]


@router.post("/admin/trainer-applications/{application_id}/decision")
def decide_trainer_application(
    application_id: UUID,
    payload: TrainerDecisionRequest,
    admin: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        application = cursor.execute(
            """
            SELECT id, user_id, status::text AS status
            FROM trainer_applications WHERE id = %s FOR UPDATE
            """,
            (application_id,),
        ).fetchone()
        if not application:
            raise HTTPException(status_code=404, detail="Trainer application not found")
        if application["status"] != "pending":
            raise HTTPException(status_code=409, detail="Trainer application was already reviewed")
        cursor.execute(
            """
            UPDATE trainer_applications
            SET status = %s::approval_status, reviewed_at = now(),
                reviewed_by = %s, review_reason = %s
            WHERE id = %s
            """,
            (payload.decision, UUID(admin.id), payload.review_reason, application_id),
        )
        if payload.decision == "approved":
            cursor.execute(
                """
                INSERT INTO user_roles (user_id, role, granted_by)
                VALUES (%s, 'trainer', %s)
                ON CONFLICT (user_id, role) DO NOTHING
                """,
                (application["user_id"], UUID(admin.id)),
            )
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, %s, 'trainer_application', %s, %s)
            """,
            (
                UUID(admin.id),
                f"trainer_application_{payload.decision}",
                application_id,
                Jsonb({"reason": payload.review_reason}),
            ),
        )
    return {"application_id": str(application_id), "status": payload.decision}


@router.get("/admin/employers/pending")
def list_unverified_employers(
    _: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, object]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        records = cursor.execute(
            """
            SELECT u.id AS user_id, u.email, ep.company_name, ep.website, ep.industry,
                   ep.verification_level
            FROM employer_profiles ep
            JOIN users u ON u.id = ep.user_id
            WHERE ep.verification_level < 2
            ORDER BY ep.verification_level, ep.company_name
            """
        ).fetchall()
    return [{**record, "user_id": str(record["user_id"])} for record in records]


@router.post("/admin/employers/{user_id}/verification")
def verify_employer(
    user_id: UUID,
    payload: EmployerVerificationRequest,
    admin: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    with connection.cursor(row_factory=dict_row) as cursor:
        employer = cursor.execute(
            """
            SELECT verification_level FROM employer_profiles
            WHERE user_id = %s FOR UPDATE
            """,
            (user_id,),
        ).fetchone()
        if not employer:
            raise HTTPException(status_code=404, detail="Employer profile not found")
        current_level = employer["verification_level"]
        if payload.level != current_level + 1:
            raise HTTPException(
                status_code=409,
                detail=f"Verification must advance one level from the current level ({current_level})",
            )
        if payload.level == 1:
            company = cursor.execute(
                """
                SELECT u.email, ep.website
                FROM users u
                JOIN employer_profiles ep ON ep.user_id = u.id
                WHERE u.id = %s
                """,
                (user_id,),
            ).fetchone()
            if not _employer_email_matches_company(company["email"], company["website"]):
                raise HTTPException(
                    status_code=422,
                    detail="Level 1 requires a non-free email on the employer's website domain",
                )
        cursor.execute(
            """
            UPDATE employer_profiles
            SET verification_level = %s, verified_at = now()
            WHERE user_id = %s
            """,
            (payload.level, user_id),
        )
        cursor.execute(
            """
            INSERT INTO employer_verification_events
              (user_id, previous_level, new_level, reviewed_by, review_reason)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, current_level, payload.level, UUID(admin.id), payload.review_reason),
        )
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'employer_verification_advanced', 'employer_profile', %s, %s)
            """,
            (
                UUID(admin.id),
                user_id,
                Jsonb(
                    {
                        "previous_level": current_level,
                        "new_level": payload.level,
                        "reason": payload.review_reason,
                    }
                ),
            ),
        )
    return {"user_id": str(user_id), "verification_level": payload.level}

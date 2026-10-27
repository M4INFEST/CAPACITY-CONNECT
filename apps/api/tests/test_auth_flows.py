import base64
import os
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import psycopg
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.core.mfa import _totp_at_counter
from app.db import get_connection
from app.main import app


class AuthenticationFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.database_url = os.getenv("CAPACITY_CONNECT_TEST_DATABASE_URL")
        if not cls.database_url:
            raise unittest.SkipTest("CAPACITY_CONNECT_TEST_DATABASE_URL is not configured")
        cls.environment = patch.dict(
            os.environ,
            {
                "AUTH_JWT_SECRET": "test-only-auth-secret-which-is-long-enough",
                "MFA_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
                "SMTP_HOST": "smtp.test.invalid",
                "SMTP_PORT": "587",
                "SMTP_FROM": "no-reply@example.test",
                "WEB_PUBLIC_URL": "https://capacity.example.test",
            },
        )
        cls.environment.start()

        def override_connection():
            with psycopg.connect(cls.database_url, row_factory=dict_row) as connection:
                yield connection

        app.dependency_overrides[get_connection] = override_connection
        cls.client = TestClient(app, client=("127.0.0.1", 50123))
        with psycopg.connect(cls.database_url) as connection:
            connection.execute(
                "TRUNCATE auth_login_attempts, auth_email_delivery_attempts RESTART IDENTITY CASCADE"
            )

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.pop(get_connection, None)
        cls.environment.stop()

    def setUp(self) -> None:
        self.email = f"learner-{uuid4().hex}@example.test"
        self.password = "StrongPassword123"

    @staticmethod
    def _email_token(mock_send: unittest.mock.Mock) -> str:
        message = mock_send.call_args.args[2]
        link = next(line for line in message.splitlines() if "#token=" in line)
        return parse_qs(urlsplit(link.strip()).fragment)["token"][0]

    def _register_and_verify(self, role: str = "trainee") -> None:
        payload = {"email": self.email, "password": self.password, "role": role}
        if role == "employer":
            payload["company_name"] = "Example Company"
        with patch("app.api.v1.auth.send_email") as send_email:
            response = self.client.post("/api/v1/auth/register", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        token = self._email_token(send_email)
        self.assertEqual(
            self.client.post("/api/v1/auth/email/verify", json={"token": token}).status_code,
            200,
        )
        self.assertEqual(
            self.client.post("/api/v1/auth/email/verify", json={"token": token}).status_code,
            400,
        )

    def test_email_verification_gates_login_and_tokens_are_single_use(self) -> None:
        with patch("app.api.v1.auth.send_email") as send_email:
            response = self.client.post(
                "/api/v1/auth/register",
                json={"email": self.email, "password": self.password, "role": "trainee"},
            )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/login",
                json={"email": self.email, "password": self.password},
            ).status_code,
            403,
        )
        verification_token = self._email_token(send_email)
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/email/verify",
                json={"token": verification_token},
            ).status_code,
            200,
        )
        login = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": self.password},
        )
        self.assertEqual(login.status_code, 200, login.text)
        access_token = login.json()["access_token"]
        self.assertEqual(
            self.client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            ).status_code,
            200,
        )

    def test_password_reset_invalidates_existing_access_tokens(self) -> None:
        self._register_and_verify()
        login = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": self.password},
        )
        access_token = login.json()["access_token"]
        with patch("app.api.v1.auth.send_email") as send_email:
            requested = self.client.post(
                "/api/v1/auth/password/forgot", json={"email": self.email}
            )
        self.assertEqual(requested.status_code, 200, requested.text)
        reset_token = self._email_token(send_email)
        reset = self.client.post(
            "/api/v1/auth/password/reset",
            json={"token": reset_token, "password": "NewStrongPassword456"},
        )
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/password/reset",
                json={"token": reset_token, "password": "AnotherPassword789"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/login",
                json={"email": self.email, "password": "NewStrongPassword456"},
            ).status_code,
            200,
        )

    def test_trainer_mfa_enrollment_and_challenge_are_enforced(self) -> None:
        self._register_and_verify()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            user = connection.execute(
                "SELECT id FROM users WHERE email = %s", (self.email,)
            ).fetchone()
            connection.execute(
                "INSERT INTO user_roles (user_id, role) VALUES (%s, 'trainer')",
                (user["id"],),
            )

        login = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": self.password},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.assertTrue(login.json()["mfa_setup_required"])
        setup_token = login.json()["setup_token"]
        headers = {"Authorization": f"Bearer {setup_token}"}
        setup = self.client.post(
            "/api/v1/auth/mfa/setup",
            headers=headers,
            json={"password": self.password},
        )
        self.assertEqual(setup.status_code, 200, setup.text)
        secret = setup.json()["secret"]
        now = int(time.time())
        counter = now // 30
        secret_bytes = base64.b32decode(secret + "=" * (-len(secret) % 8))
        code = _totp_at_counter(secret_bytes, counter)
        confirmed = self.client.post(
            "/api/v1/auth/mfa/confirm",
            headers=headers,
            json={"code": code},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(len(confirmed.json()["recovery_codes"]), 10)
        access_token = confirmed.json()["access_token"]
        self.assertEqual(
            self.client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get("/api/v1/auth/me", headers=headers).status_code, 401
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/mfa/disable",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "password": self.password,
                    "code": confirmed.json()["recovery_codes"][1],
                },
            ).status_code,
            403,
        )

        while int(time.time()) // 30 == counter:
            time.sleep(0.1)
        challenge = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": self.password},
        )
        self.assertEqual(challenge.status_code, 200, challenge.text)
        self.assertTrue(challenge.json()["mfa_required"])
        challenge_token = challenge.json()["challenge_token"]
        code = _totp_at_counter(secret_bytes, int(time.time()) // 30)
        challenge_headers = {"Authorization": f"Bearer {challenge_token}"}
        verified = self.client.post(
            "/api/v1/auth/mfa/verify",
            headers=challenge_headers,
            json={"code": code},
        )
        self.assertEqual(verified.status_code, 200, verified.text)
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/mfa/verify",
                headers=challenge_headers,
                json={"code": code},
            ).status_code,
            401,
        )
        replayed_totp_challenge = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": self.password},
        )
        replayed_totp = self.client.post(
            "/api/v1/auth/mfa/verify",
            headers={"Authorization": f"Bearer {replayed_totp_challenge.json()['challenge_token']}"},
            json={"code": code},
        )
        self.assertEqual(replayed_totp.status_code, 401)

        recovery_code = confirmed.json()["recovery_codes"][0]
        recovery_challenge = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": self.password},
        )
        recovery_login = self.client.post(
            "/api/v1/auth/mfa/verify",
            headers={"Authorization": f"Bearer {recovery_challenge.json()['challenge_token']}"},
            json={"code": recovery_code},
        )
        self.assertEqual(recovery_login.status_code, 200, recovery_login.text)
        reused_recovery_challenge = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": self.password},
        )
        reused_recovery = self.client.post(
            "/api/v1/auth/mfa/verify",
            headers={"Authorization": f"Bearer {reused_recovery_challenge.json()['challenge_token']}"},
            json={"code": recovery_code},
        )
        self.assertEqual(reused_recovery.status_code, 401)

    def test_trainee_can_enable_and_disable_optional_mfa(self) -> None:
        self._register_and_verify()
        login = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": self.password},
        )
        access_token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        initial_status = self.client.get("/api/v1/auth/mfa/status", headers=headers)
        self.assertEqual(initial_status.status_code, 200, initial_status.text)
        self.assertEqual(
            initial_status.json(),
            {"enabled": False, "recovery_codes_remaining": 0},
        )

        setup = self.client.post(
            "/api/v1/auth/mfa/setup",
            headers=headers,
            json={"password": self.password},
        )
        self.assertEqual(setup.status_code, 200, setup.text)
        secret = setup.json()["secret"]
        counter = int(time.time()) // 30
        secret_bytes = base64.b32decode(secret + "=" * (-len(secret) % 8))
        confirmation = self.client.post(
            "/api/v1/auth/mfa/confirm",
            headers=headers,
            json={"code": _totp_at_counter(secret_bytes, counter)},
        )
        self.assertEqual(confirmation.status_code, 200, confirmation.text)
        self.assertEqual(len(confirmation.json()["recovery_codes"]), 10)

        enabled_headers = {
            "Authorization": f"Bearer {confirmation.json()['access_token']}"
        }
        enabled_status = self.client.get(
            "/api/v1/auth/mfa/status", headers=enabled_headers
        )
        self.assertEqual(enabled_status.status_code, 200, enabled_status.text)
        self.assertEqual(
            enabled_status.json(),
            {"enabled": True, "recovery_codes_remaining": 10},
        )

        recovery_code = confirmation.json()["recovery_codes"][0]
        wrong_password = self.client.post(
            "/api/v1/auth/mfa/disable",
            headers=enabled_headers,
            json={"password": "WrongPassword123", "code": recovery_code},
        )
        self.assertEqual(wrong_password.status_code, 401, wrong_password.text)
        disabled = self.client.post(
            "/api/v1/auth/mfa/disable",
            headers=enabled_headers,
            json={
                "password": self.password,
                "code": recovery_code,
            },
        )
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertEqual(
            self.client.get(
                "/api/v1/auth/mfa/status", headers=enabled_headers
            ).status_code,
            401,
        )
        new_login = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": self.password},
        )
        self.assertEqual(new_login.status_code, 200, new_login.text)
        final_status = self.client.get(
            "/api/v1/auth/mfa/status",
            headers={"Authorization": f"Bearer {new_login.json()['access_token']}"},
        )
        self.assertEqual(final_status.status_code, 200, final_status.text)
        self.assertEqual(
            final_status.json(),
            {"enabled": False, "recovery_codes_remaining": 0},
        )

    def test_trainer_application_does_not_grant_trainer_role(self) -> None:
        self._register_and_verify()
        login = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": self.password},
        )
        access_token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        response = self.client.post(
            "/api/v1/roles/trainer/apply",
            headers=headers,
            json={"expertise": ["Python", "Data engineering"]},
        )
        self.assertEqual(response.status_code, 201, response.text)
        application = self.client.get(
            "/api/v1/roles/trainer/applications/me", headers=headers
        )
        self.assertEqual(application.status_code, 200, application.text)
        self.assertEqual(application.json()["status"], "pending")
        account = self.client.get("/api/v1/auth/me", headers=headers)
        self.assertEqual(account.status_code, 200, account.text)
        self.assertEqual(account.json()["roles"], ["trainee"])

    def test_employer_and_admin_roles_require_mfa_before_access(self) -> None:
        self._register_and_verify(role="employer")
        employer_login = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": self.password},
        )
        self.assertEqual(employer_login.status_code, 200, employer_login.text)
        self.assertTrue(employer_login.json()["mfa_setup_required"])
        self.assertIsNone(employer_login.json()["access_token"])

        admin_email = f"admin-{uuid4().hex}@example.test"
        with patch("app.api.v1.auth.send_email") as send_email:
            self.client.post(
                "/api/v1/auth/register",
                json={
                    "email": admin_email,
                    "password": self.password,
                    "role": "trainee",
                },
            )
        verify_token = self._email_token(send_email)
        self.client.post("/api/v1/auth/email/verify", json={"token": verify_token})
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO user_roles (user_id, role)
                SELECT id, 'admin' FROM users WHERE email = %s
                """,
                (admin_email,),
            )
        admin_login = self.client.post(
            "/api/v1/auth/login",
            json={"email": admin_email, "password": self.password},
        )
        self.assertEqual(admin_login.status_code, 200, admin_login.text)
        self.assertTrue(admin_login.json()["mfa_setup_required"])
        self.assertIsNone(admin_login.json()["access_token"])

    def test_registration_fails_closed_without_email_delivery(self) -> None:
        with patch.dict(os.environ, {"SMTP_HOST": ""}):
            response = self.client.post(
                "/api/v1/auth/register",
                json={
                    "email": self.email,
                    "password": self.password,
                    "role": "trainee",
                },
            )
        self.assertEqual(response.status_code, 503, response.text)
        with psycopg.connect(self.database_url) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM users WHERE email = %s", (self.email,)
                ).fetchone()[0],
                0,
            )

    def test_google_sign_in_creates_learner_and_consumes_one_time_codes(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GOOGLE_CLIENT_ID": "capacity-connect-test.apps.googleusercontent.com",
                "GOOGLE_CLIENT_SECRET": "test-google-client-secret",
                "GOOGLE_REDIRECT_URI": "http://localhost:8000/api/v1/auth/google/callback",
            },
        ):
            start = self.client.get(
                "/api/v1/auth/google/start", follow_redirects=False
            )
            self.assertEqual(start.status_code, 303, start.text)
            authorization_url = urlsplit(start.headers["location"])
            self.assertEqual(
                authorization_url.netloc, "accounts.google.com"
            )
            authorization = parse_qs(authorization_url.query)
            self.assertEqual(authorization["code_challenge_method"], ["S256"])
            self.assertIn("openid email", authorization["scope"])
            state = authorization["state"][0]

            with patch(
                "app.api.v1.auth.exchange_google_code",
                return_value={
                    "sub": f"google-{uuid4().hex}",
                    "email": self.email,
                    "email_verified": True,
                },
            ):
                callback = self.client.get(
                    "/api/v1/auth/google/callback",
                    params={"code": "provider-authorization-code", "state": state},
                    follow_redirects=False,
                )
            self.assertEqual(callback.status_code, 303, callback.text)
            callback_url = urlsplit(callback.headers["location"])
            self.assertEqual(callback_url.path, "/auth/google/callback")
            transfer_code = parse_qs(callback_url.fragment)["code"][0]

            exchanged = self.client.post(
                "/api/v1/auth/google/exchange",
                json={"code": transfer_code},
            )
            self.assertEqual(exchanged.status_code, 200, exchanged.text)
            self.assertTrue(exchanged.json()["access_token"])
            account = self.client.get(
                "/api/v1/auth/me",
                headers={
                    "Authorization": f"Bearer {exchanged.json()['access_token']}"
                },
            )
            self.assertEqual(account.status_code, 200, account.text)
            self.assertEqual(account.json()["email"], self.email)
            self.assertEqual(account.json()["roles"], ["trainee"])
            replay = self.client.post(
                "/api/v1/auth/google/exchange",
                json={"code": transfer_code},
            )
            self.assertEqual(replay.status_code, 400)

            replayed_state = self.client.get(
                "/api/v1/auth/google/callback",
                params={"code": "provider-authorization-code", "state": state},
                follow_redirects=False,
            )
            self.assertIn("google_state_invalid", replayed_state.headers["location"])

    def test_google_sign_in_links_only_the_same_verified_email(self) -> None:
        with patch("app.api.v1.auth.send_email"):
            registered = self.client.post(
                "/api/v1/auth/register",
                json={"email": self.email, "password": self.password, "role": "trainee"},
            )
        self.assertEqual(registered.status_code, 201, registered.text)

        with patch.dict(
            os.environ,
            {
                "GOOGLE_CLIENT_ID": "capacity-connect-test.apps.googleusercontent.com",
                "GOOGLE_CLIENT_SECRET": "test-google-client-secret",
                "GOOGLE_REDIRECT_URI": "http://localhost:8000/api/v1/auth/google/callback",
            },
        ):
            start = self.client.get(
                "/api/v1/auth/google/start", follow_redirects=False
            )
            state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
            with patch(
                "app.api.v1.auth.exchange_google_code",
                return_value={
                    "sub": f"google-{uuid4().hex}",
                    "email": self.email,
                    "email_verified": True,
                },
            ):
                callback = self.client.get(
                    "/api/v1/auth/google/callback",
                    params={"code": "provider-authorization-code", "state": state},
                    follow_redirects=False,
                )
            transfer_code = parse_qs(urlsplit(callback.headers["location"]).fragment)["code"][0]
            exchanged = self.client.post(
                "/api/v1/auth/google/exchange",
                json={"code": transfer_code},
            )

        self.assertEqual(exchanged.status_code, 200, exchanged.text)
        account = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {exchanged.json()['access_token']}"},
        )
        self.assertEqual(account.status_code, 200, account.text)
        self.assertEqual(account.json()["id"], registered.json()["id"])
        self.assertEqual(account.json()["roles"], ["trainee"])

    def test_google_sign_in_fails_closed_when_provider_is_not_configured(self) -> None:
        with patch.dict(
            os.environ,
            {"GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": ""},
        ):
            response = self.client.get(
                "/api/v1/auth/google/start", follow_redirects=False
            )
        self.assertEqual(response.status_code, 303)
        self.assertIn("google_not_configured", response.headers["location"])

    def test_email_recovery_requests_are_rate_limited(self) -> None:
        for _ in range(3):
            response = self.client.post(
                "/api/v1/auth/password/forgot", json={"email": self.email}
            )
            self.assertEqual(response.status_code, 200, response.text)
        limited = self.client.post(
            "/api/v1/auth/password/forgot", json={"email": self.email}
        )
        self.assertEqual(limited.status_code, 429, limited.text)

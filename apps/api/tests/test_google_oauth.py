import base64
import hashlib
import unittest
from unittest.mock import patch

from app.core.google_oauth import (
    GoogleOAuthError,
    exchange_google_code,
    google_oauth_settings,
    pkce_challenge,
)


class GoogleOAuthTests(unittest.TestCase):
    def test_pkce_challenge_uses_base64url_sha256_without_padding(self) -> None:
        verifier = "a" * 64
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        self.assertEqual(pkce_challenge(verifier), expected)

    def test_settings_require_both_credentials_and_secure_redirect_uri(self) -> None:
        with patch.dict(
            "os.environ",
            {"GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": ""},
        ):
            self.assertIsNone(google_oauth_settings())

        with patch.dict(
            "os.environ",
            {"GOOGLE_CLIENT_ID": "client-id", "GOOGLE_CLIENT_SECRET": ""},
        ):
            with self.assertRaises(GoogleOAuthError):
                google_oauth_settings()

        with patch.dict(
            "os.environ",
            {
                "GOOGLE_CLIENT_ID": "client-id",
                "GOOGLE_CLIENT_SECRET": "client-secret",
                "GOOGLE_REDIRECT_URI": "http://example.com/callback",
            },
        ):
            with self.assertRaises(GoogleOAuthError):
                google_oauth_settings()

    def test_code_exchange_checks_signed_identity_and_nonce(self) -> None:
        response = unittest.mock.Mock()
        response.__enter__ = unittest.mock.Mock(return_value=response)
        response.__exit__ = unittest.mock.Mock(return_value=False)
        response.read.return_value = b'{"id_token":"signed-google-id-token"}'
        claims = {
            "iss": "https://accounts.google.com",
            "nonce": "expected-nonce",
            "email_verified": True,
            "sub": "google-subject",
            "email": "learner@example.test",
        }
        with (
            patch("app.core.google_oauth.urlopen", return_value=response),
            patch(
                "app.core.google_oauth.id_token.verify_oauth2_token",
                return_value=claims,
            ) as verify,
        ):
            result = exchange_google_code(
                "authorization-code",
                "pkce-verifier",
                "http://localhost:8000/callback",
                "client-id",
                "client-secret",
                "expected-nonce",
            )
        self.assertEqual(result, claims)
        self.assertEqual(verify.call_args.kwargs["audience"], "client-id")

    def test_code_exchange_rejects_nonce_mismatch(self) -> None:
        response = unittest.mock.Mock()
        response.__enter__ = unittest.mock.Mock(return_value=response)
        response.__exit__ = unittest.mock.Mock(return_value=False)
        response.read.return_value = b'{"id_token":"signed-google-id-token"}'
        with (
            patch("app.core.google_oauth.urlopen", return_value=response),
            patch(
                "app.core.google_oauth.id_token.verify_oauth2_token",
                return_value={
                    "iss": "accounts.google.com",
                    "nonce": "different",
                    "email_verified": True,
                    "sub": "google-subject",
                    "email": "learner@example.test",
                },
            ),
        ):
            with self.assertRaises(GoogleOAuthError):
                exchange_google_code(
                    "authorization-code",
                    "pkce-verifier",
                    "http://localhost:8000/callback",
                    "client-id",
                    "client-secret",
                    "expected-nonce",
                )

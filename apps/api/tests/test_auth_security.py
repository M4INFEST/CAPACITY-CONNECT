import unittest

from app.api.v1.auth import _employer_email_matches_company, _login_delay
from app.core.security import (
    create_access_token,
    decode_access_token,
    decode_access_token_claims,
    hash_password,
    verify_password,
)
from app.schemas.auth import RegisterRequest


class PasswordSecurityTests(unittest.TestCase):
    def test_password_hash_is_salted_and_verified(self) -> None:
        first = hash_password("correct horse battery staple")
        second = hash_password("correct horse battery staple")

        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("correct horse battery staple", first))
        self.assertFalse(verify_password("incorrect", first))

    def test_missing_hash_does_not_authenticate(self) -> None:
        self.assertFalse(verify_password("some password", None))


class TokenSecurityTests(unittest.TestCase):
    def test_access_token_round_trip_and_expiration(self) -> None:
        token = create_access_token("user-123", b"test-secret-that-is-long-enough", now=100)

        self.assertEqual(
            decode_access_token(token, b"test-secret-that-is-long-enough", now=101),
            "user-123",
        )
        with self.assertRaises(ValueError):
            decode_access_token(token, b"test-secret-that-is-long-enough", now=1900)

    def test_tampered_signature_is_rejected(self) -> None:
        token = create_access_token("user-123", b"test-secret-that-is-long-enough", now=100)
        unsigned, signature = token.rsplit(".", 1)
        replacement = "A" if signature[0] != "A" else "B"

        with self.assertRaises(ValueError):
            decode_access_token(
                f"{unsigned}.{replacement}{signature[1:]}",
                b"test-secret-that-is-long-enough",
                now=101,
            )

    def test_access_tokens_have_unique_identifiers(self) -> None:
        secret = b"test-secret-that-is-long-enough"
        first = create_access_token("user-123", secret, now=100)
        second = create_access_token("user-123", secret, now=100)

        self.assertNotEqual(
            decode_access_token_claims(first, secret, now=101)["jti"],
            decode_access_token_claims(second, secret, now=101)["jti"],
        )


class LoginProtectionTests(unittest.TestCase):
    def test_progressive_delay_is_bounded_and_does_not_lock_out(self) -> None:
        self.assertEqual([_login_delay(count) for count in range(5)], [0, 1, 2, 4, 8])
        self.assertEqual(_login_delay(100), 30)

    def test_company_email_requires_matching_non_free_domain(self) -> None:
        self.assertTrue(
            _employer_email_matches_company("person@company.example", "https://company.example")
        )
        self.assertFalse(
            _employer_email_matches_company("person@gmail.com", "https://company.example")
        )
        self.assertFalse(
            _employer_email_matches_company("person@other.example", "https://company.example")
        )

    def test_public_registration_cannot_grant_privileged_roles(self) -> None:
        request = RegisterRequest(
            email=" Person@Example.com ",
            password="Long enough password 1",
        )
        self.assertEqual(request.email, "person@example.com")
        with self.assertRaises(ValueError):
            RegisterRequest(
                email="person@example.com",
                password="Long enough password 1",
                role="admin",
            )
        with self.assertRaises(ValueError):
            RegisterRequest(
                email="person@example.com",
                password="long enough password",
            )


if __name__ == "__main__":
    unittest.main()

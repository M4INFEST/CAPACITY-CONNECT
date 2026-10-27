import unittest

from cryptography.fernet import Fernet

from app.core.mfa import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    make_otpauth_uri,
    totp_counter_for_code,
    verify_totp,
)
from app.core.security import create_access_token, decode_access_token_claims
from app.schemas.auth import MfaCodeRequest


class TotpSecurityTests(unittest.TestCase):
    def test_rfc_totp_vector_and_time_window(self) -> None:
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        self.assertTrue(verify_totp(secret, "287082", now=59))
        self.assertFalse(verify_totp(secret, "287083", now=59))
        self.assertFalse(verify_totp(secret, "28A082", now=59))
        self.assertEqual(totp_counter_for_code(secret, "287082", now=59), 1)
        self.assertIsNone(totp_counter_for_code(secret, "287083", now=59))

    def test_encrypted_totp_secret_round_trip_and_wrong_key_rejected(self) -> None:
        key = Fernet.generate_key()
        ciphertext = encrypt_totp_secret("TESTSECRET", key)
        self.assertNotEqual(ciphertext, "TESTSECRET")
        self.assertEqual(decrypt_totp_secret(ciphertext, key), "TESTSECRET")
        with self.assertRaises(ValueError):
            decrypt_totp_secret(ciphertext, Fernet.generate_key())

    def test_recovery_codes_are_unique_and_hashed_with_pepper(self) -> None:
        codes = generate_recovery_codes()
        self.assertEqual(len(codes), 10)
        self.assertEqual(len(set(codes)), 10)
        self.assertTrue(all(len(code) == 32 for code in codes))
        self.assertNotEqual(
            hash_recovery_code(codes[0], b"pepper"),
            hash_recovery_code(codes[0], b"different-pepper"),
        )

    def test_otpauth_uri_includes_issuer_and_account_label(self) -> None:
        uri = make_otpauth_uri("SECRET", "person@example.com")
        self.assertTrue(uri.startswith("otpauth://totp/Capacity%20Connect%3Aperson%40example.com?"))
        self.assertIn("issuer=Capacity+Connect", uri)

    def test_mfa_code_schema_accepts_only_totp_or_recovery_code_shapes(self) -> None:
        self.assertEqual(MfaCodeRequest(code="123-456").code, "123456")
        self.assertEqual(MfaCodeRequest(code="a" * 32).code, "a" * 32)
        for code in ("12345", "１２３４５６", "z" * 32, "1234567"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                MfaCodeRequest(code=code)


class PurposeBoundTokenTests(unittest.TestCase):
    def test_setup_token_is_not_an_access_token(self) -> None:
        secret = b"test-secret-that-is-long-enough"
        token = create_access_token("user-123", secret, purpose="mfa_setup")
        claims = decode_access_token_claims(token, secret)
        self.assertEqual(claims["purpose"], "mfa_setup")
        self.assertEqual(claims["sub"], "user-123")

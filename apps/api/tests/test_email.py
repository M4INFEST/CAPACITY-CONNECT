import unittest
from unittest.mock import patch

from app.core.email import EmailDeliveryError, send_email


class EmailDeliveryTests(unittest.TestCase):
    def test_mailpit_development_delivery_does_not_attempt_starttls(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "SMTP_HOST": "mailpit",
                    "SMTP_PORT": "1025",
                    "SMTP_FROM": "no-reply@capacity-connect.local",
                    "SMTP_USE_STARTTLS": "false",
                    "SMTP_USERNAME": "",
                },
            ),
            patch("app.core.email.smtplib.SMTP") as smtp,
        ):
            send_email("learner@example.test", "Verify", "Verification link")

        client = smtp.return_value.__enter__.return_value
        client.starttls.assert_not_called()
        client.send_message.assert_called_once()

    def test_starttls_is_required_by_default(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "SMTP_HOST": "smtp.example.test",
                    "SMTP_PORT": "587",
                    "SMTP_FROM": "no-reply@example.test",
                    "SMTP_USE_STARTTLS": "true",
                    "SMTP_USERNAME": "",
                },
            ),
            patch("app.core.email.smtplib.SMTP") as smtp,
        ):
            send_email("learner@example.test", "Verify", "Verification link")

        client = smtp.return_value.__enter__.return_value
        client.starttls.assert_called_once()

    def test_plain_smtp_cannot_be_combined_with_authentication(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SMTP_HOST": "mailpit",
                "SMTP_PORT": "1025",
                "SMTP_FROM": "no-reply@capacity-connect.local",
                "SMTP_USE_STARTTLS": "false",
                "SMTP_USERNAME": "unexpected-user",
                "SMTP_PASSWORD": "unexpected-password",
            },
        ):
            with self.assertRaises(EmailDeliveryError):
                send_email("learner@example.test", "Verify", "Verification link")

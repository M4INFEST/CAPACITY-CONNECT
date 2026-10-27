import os
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlsplit


class EmailDeliveryError(RuntimeError):
    pass


def email_delivery_configured() -> bool:
    return all(
        os.getenv(name, "").strip()
        for name in ("SMTP_HOST", "SMTP_FROM", "WEB_PUBLIC_URL")
    )


def web_public_url() -> str:
    value = os.getenv("WEB_PUBLIC_URL", "").strip().rstrip("/")
    parsed = urlsplit(value)
    local_http = parsed.scheme == "http" and parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or not (parsed.scheme == "https" or local_http)
    ):
        raise RuntimeError("WEB_PUBLIC_URL must use HTTPS except for local development")
    return value


def send_email(recipient: str, subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("SMTP_FROM", "").strip()
    if not host or not sender:
        raise EmailDeliveryError("Email delivery is not configured")

    try:
        port = int(os.getenv("SMTP_PORT", "587"))
        timeout = int(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))
        if not 1 <= port <= 65535 or not 1 <= timeout <= 30:
            raise ValueError("SMTP port or timeout is outside its allowed range")
        starttls_setting = os.getenv("SMTP_USE_STARTTLS", "true").strip().lower() or "true"
        if starttls_setting not in {"true", "false"}:
            raise ValueError("SMTP_USE_STARTTLS must be true or false")
        use_starttls = starttls_setting == "true"
        username = os.getenv("SMTP_USERNAME", "").strip()
        password = os.getenv("SMTP_PASSWORD", "")
        if username and not use_starttls:
            raise ValueError("SMTP authentication requires STARTTLS")
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(host, port, timeout=timeout) as client:
            client.ehlo()
            if use_starttls:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if username:
                if not password:
                    raise ValueError("SMTP_PASSWORD is required when SMTP_USERNAME is set")
                client.login(username, password)
            client.send_message(message)
    except (OSError, ValueError, smtplib.SMTPException) as error:
        raise EmailDeliveryError(
            "Email delivery failed; retry after checking SMTP configuration"
        ) from error

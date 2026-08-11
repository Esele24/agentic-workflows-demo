"""Send an email over SMTP. The sending layer for the enquiry autoresponder.

Usage (test that your credentials work — send yourself one):
    python tools/send_email.py --to you@example.com --subject "Test" --text "Hello"

With an HTML body as well as plain text:
    python tools/send_email.py --to you@example.com --subject "Hi" \
        --text "Plain fallback" --html "<h1>Fancy</h1>"

Set a Reply-To so replies go to the business owner, not the sending account:
    python tools/send_email.py --to customer@example.com --subject "Got it" \
        --text "Thanks!" --reply-to owner@clinic.com

Required in .env:
    SMTP_USER       the full Gmail address sending the mail
    SMTP_PASSWORD   a Google *App Password* (16 chars) — NOT the account password
    FROM_NAME       display name recipients see, e.g. "Bright Smile Dental"

Optional in .env (defaults suit Gmail):
    SMTP_HOST       default smtp.gmail.com
    SMTP_PORT       default 587
"""

import argparse
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FROM_NAME = os.getenv("FROM_NAME", "")

CONNECT_TIMEOUT = 30  # seconds; Gmail is usually fast but PH connections stall


class EmailConfigError(RuntimeError):
    """Credentials are missing or malformed — a setup problem, not a send problem."""


class EmailSendError(RuntimeError):
    """The server rejected the message or the connection failed."""


def _check_config() -> None:
    missing = [
        name
        for name, value in (("SMTP_USER", SMTP_USER), ("SMTP_PASSWORD", SMTP_PASSWORD))
        if not value
    ]
    if missing:
        raise EmailConfigError(
            f"Missing in .env: {', '.join(missing)}. "
            "See the module docstring for how to generate a Gmail App Password."
        )
    # App Passwords are 16 characters. Google shows them spaced ("abcd efgh ijkl mnop")
    # and pasting the spaces is the single most common setup mistake.
    if " " in SMTP_PASSWORD:
        raise EmailConfigError(
            "SMTP_PASSWORD contains spaces. Google displays App Passwords in "
            "groups of four for readability, but you must store them with the "
            "spaces removed (16 characters, no spaces)."
        )


def send_email(
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
    reply_to: str | None = None,
) -> None:
    """Send one email. Raises EmailConfigError or EmailSendError on failure.

    `text` is always required even when `html` is supplied: it's the fallback
    body for clients that don't render HTML, and messages sent without a plain
    text alternative score worse with spam filters.
    """
    _check_config()

    message = EmailMessage()
    message["From"] = f"{FROM_NAME} <{SMTP_USER}>" if FROM_NAME else SMTP_USER
    message["To"] = to
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to

    message.set_content(text)
    if html:
        # Adds the HTML as an alternative part; the client picks the richest one
        # it can render, falling back to the plain text set above.
        message.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=CONNECT_TIMEOUT) as server:
            server.starttls()  # upgrade the plaintext connection to TLS before auth
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailSendError(
            "Gmail rejected the login. The usual causes, in order of likelihood:\n"
            "  1. SMTP_PASSWORD is the normal account password — it must be an "
            "App Password.\n"
            "  2. 2-Step Verification is off on the Google account. App Passwords "
            "cannot be created until it is on.\n"
            "  3. The App Password was revoked or regenerated.\n"
            f"Server said: {exc}"
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailSendError(f"Could not send to {to}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a test email over SMTP")
    parser.add_argument("--to", required=True, help="Recipient address")
    parser.add_argument("--subject", required=True, help="Subject line")
    parser.add_argument("--text", required=True, help="Plain-text body")
    parser.add_argument("--html", help="Optional HTML body")
    parser.add_argument("--reply-to", help="Optional Reply-To address")
    args = parser.parse_args()

    try:
        send_email(
            to=args.to,
            subject=args.subject,
            text=args.text,
            html=args.html,
            reply_to=args.reply_to,
        )
    except (EmailConfigError, EmailSendError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Sent to {args.to}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

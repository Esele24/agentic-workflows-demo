"""Send an email. The sending layer for the enquiry autoresponder.

TWO TRANSPORTS, AND THE REASON THERE ARE TWO
    `smtp`   talks to Gmail on port 587. Works locally. **Does not work on
             Render's free tier**, which blocked outbound ports 25, 465 and 587
             on free web services in September 2025. The symptom is not an
             error: the connection HANGS until something kills the worker, and
             /health keeps reporting a perfectly healthy service the whole time.
    `brevo`  posts to Brevo's HTTPS API on port 443, which no host blocks.

    Which one runs is chosen by `_transport()` below. If BREVO_API_KEY is set,
    Brevo wins. ⚠️ That default is deliberate and it is the safe direction: on a
    host that blocks SMTP, defaulting to SMTP means hanging, and a hang is far
    harder to diagnose than a missing key.

Usage (send yourself one to check the credentials work):
    python tools/send_email.py --to you@example.com --subject "Test" --text "Hello"

Set a Reply-To so replies go to the business owner, not the sending account:
    python tools/send_email.py --to customer@example.com --subject "Got it" \
        --text "Thanks!" --reply-to owner@clinic.com

Required in .env for the BREVO transport:
    BREVO_API_KEY        from Brevo, SMTP & API, API Keys
    BREVO_SENDER_EMAIL   a sender you VERIFIED in Brevo (falls back to SMTP_USER)
    FROM_NAME            display name recipients see

Required in .env for the SMTP transport:
    SMTP_USER            the full Gmail address sending the mail
    SMTP_PASSWORD        a Google *App Password* (16 chars), NOT the account password
    FROM_NAME            display name recipients see

Optional:
    EMAIL_TRANSPORT      force "smtp" or "brevo" instead of auto selecting
    SMTP_HOST            default smtp.gmail.com
    SMTP_PORT            default 587

⚠️ DELIVERABILITY, AND IT IS NOT A CODE PROBLEM. Brevo cannot authenticate a
free webmail domain: "@gmail.com" and "@yahoo.com" senders can be verified but
never DKIM signed. Since February 2024 Gmail and Yahoo require authentication of
bulk senders, so mail sent from a gmail.com address lands in spam more often.
Sending works; it just does not arrive as reliably. **The fix is a domain, not
code** — authenticate it in Brevo and nothing here changes.
"""

import argparse
import json
import os
import smtplib
import sys
import urllib.error
import urllib.request
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

BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"

CONNECT_TIMEOUT = 30  # seconds; Gmail is usually fast but PH connections stall

# ⚠️ Shorter than gunicorn's 60s worker timeout ON PURPOSE. Two sends happen per
# enquiry, so anything at or above 30 each can exceed the worker budget and get
# the process killed mid request. Killed by gunicorn produces no application
# error and no log line worth reading; a timeout raised here produces both.
HTTP_TIMEOUT = 20


class EmailConfigError(RuntimeError):
    """Credentials are missing or malformed — a setup problem, not a send problem."""


class EmailSendError(RuntimeError):
    """The server rejected the message or the connection failed."""


def _env(name: str, default: str = "") -> str:
    """Read at call time, not import time, so tests can set the environment."""
    return os.getenv(name, default).strip()


def _transport() -> str:
    """Which sender to use. Explicit setting wins; otherwise a key decides."""
    explicit = _env("EMAIL_TRANSPORT").lower()
    if explicit:
        if explicit not in ("smtp", "brevo"):
            raise EmailConfigError(
                f"EMAIL_TRANSPORT is {explicit!r}, expected 'smtp' or 'brevo'."
            )
        return explicit
    return "brevo" if _env("BREVO_API_KEY") else "smtp"


def _sender_address() -> str:
    """The From address. Brevo needs a sender VERIFIED in the Brevo dashboard."""
    return _env("BREVO_SENDER_EMAIL") or SMTP_USER


def _check_smtp_config() -> None:
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
    # App Passwords are 16 characters. Google shows them spaced ("abcd efgh ijkl
    # mnop") and pasting the spaces is the single most common setup mistake.
    if " " in SMTP_PASSWORD:
        raise EmailConfigError(
            "SMTP_PASSWORD contains spaces. Google displays App Passwords in "
            "groups of four for readability, but you must store them with the "
            "spaces removed (16 characters, no spaces)."
        )


def _check_brevo_config() -> None:
    if not _env("BREVO_API_KEY"):
        raise EmailConfigError(
            "BREVO_API_KEY is missing. Brevo dashboard, SMTP & API, API Keys."
        )
    if not _sender_address():
        raise EmailConfigError(
            "No sender address. Set BREVO_SENDER_EMAIL to an address you have "
            "verified in Brevo (Senders, Domains & Dedicated IPs), or set SMTP_USER."
        )


def _send_smtp(
    to: str, subject: str, text: str, html: str | None, reply_to: str | None
) -> None:
    _check_smtp_config()

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
        raise EmailSendError(
            f"Could not send to {to}: {exc}\n"
            "⚠️ If this HUNG rather than failed, the host is blocking SMTP. "
            "Render's free tier blocks ports 25, 465 and 587. Set BREVO_API_KEY "
            "to switch to the HTTPS transport."
        ) from exc


def brevo_payload(
    to: str, subject: str, text: str, html: str | None, reply_to: str | None
) -> dict:
    """Build the request body. Separate from the call so it can be tested."""
    payload: dict = {
        "sender": {"email": _sender_address()},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": text,
    }
    if FROM_NAME:
        payload["sender"]["name"] = FROM_NAME
    if html:
        payload["htmlContent"] = html
    # The whole product is in this line. On the customer's acknowledgement it
    # points at the business owner; on the owner's alert it points at the
    # customer, so the owner just hits reply. Lose it and the tool is a bell.
    if reply_to:
        payload["replyTo"] = {"email": reply_to}
    return payload


def _send_brevo(
    to: str, subject: str, text: str, html: str | None, reply_to: str | None
) -> None:
    _check_brevo_config()

    body = json.dumps(brevo_payload(to, subject, text, html, reply_to)).encode()
    request = urllib.request.Request(
        BREVO_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "api-key": _env("BREVO_API_KEY"),
            "content-type": "application/json",
            "accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            if response.status not in (200, 201, 202):
                raise EmailSendError(
                    f"Brevo returned HTTP {response.status} sending to {to}."
                )
    except urllib.error.HTTPError as exc:
        # ⚠️ Read the body. Brevo explains a rejection there and nowhere else:
        # an unverified sender, an expired key and a daily cap all arrive as a
        # bare 400 or 401 with the actual reason only in the response body.
        detail = exc.read().decode(errors="replace")
        hint = ""
        if exc.code in (400, 401):
            hint = (
                "\nUsual causes: the sender address is not verified in Brevo, "
                "the API key is wrong or revoked, or the free plan's 300 a day "
                "has been used up."
            )
        raise EmailSendError(
            f"Brevo rejected the send to {to} (HTTP {exc.code}): {detail}{hint}"
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise EmailSendError(f"Could not reach Brevo to send to {to}: {exc}") from exc


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
    if _transport() == "brevo":
        _send_brevo(to, subject, text, html, reply_to)
    else:
        _send_smtp(to, subject, text, html, reply_to)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a test email")
    parser.add_argument("--to", required=True, help="Recipient address")
    parser.add_argument("--subject", required=True, help="Subject line")
    parser.add_argument("--text", required=True, help="Plain-text body")
    parser.add_argument("--html", help="Optional HTML body")
    parser.add_argument("--reply-to", help="Optional Reply-To address")
    args = parser.parse_args()

    try:
        transport = _transport()
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

    # Naming the transport matters: "Sent" while silently using SMTP on a host
    # that blocks it is the confusion this whole module exists to prevent.
    print(f"Sent to {args.to} via {transport}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

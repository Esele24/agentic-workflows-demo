"""Enquiry autoresponder — receives website form submissions and reacts instantly.

This is a *service*, not a WAT tool: it runs unattended and is triggered by a
customer, not by an agent. It reuses tools/send_email.py and tools/log_enquiry.py.

Run it:
    python enquiry_server.py
    # listening on http://localhost:5000

Test it without a website (PowerShell):
    curl.exe -X POST http://localhost:5000/enquiry `
      -H "Content-Type: application/json" `
      -d '{\"name\":\"Ada\",\"email\":\"ada@example.com\",\"message\":\"How much for 100 guests?\"}'

Required in .env (in addition to the SMTP_* vars send_email.py needs):
    BUSINESS_NAME    e.g. "Bright Smile Dental"
    OWNER_EMAIL      where enquiry alerts go — the business owner's inbox

Optional in .env:
    REPLY_WINDOW     human phrase for the promise, default "within 24 hours"
    ENQUIRY_LOG      CSV path, default output/enquiries.csv
"""

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools.log_enquiry import log_enquiry  # noqa: E402
from tools.send_email import EmailConfigError, EmailSendError, send_email  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

BUSINESS_NAME = os.getenv("BUSINESS_NAME", "").strip()
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "").strip()
REPLY_WINDOW = os.getenv("REPLY_WINDOW", "within 24 hours").strip()
ENQUIRY_LOG = PROJECT_ROOT / os.getenv("ENQUIRY_LOG", "output/enquiries.csv")

MAX_FIELD_LENGTH = 5000  # stops a bot posting a megabyte of spam into the CSV
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = Flask(__name__)


def customer_reply_body(name: str, message: str) -> tuple[str, str]:
    """Return (plain_text, html) for the auto-reply sent to the customer."""
    text = (
        f"Hi {name},\n\n"
        f"Thanks for getting in touch with {BUSINESS_NAME}. We've received your "
        f"message and someone will reply personally {REPLY_WINDOW}.\n\n"
        f"For your records, here's what you sent us:\n\n"
        f"{message}\n\n"
        f"— {BUSINESS_NAME}"
    )
    html = (
        f"<p>Hi {name},</p>"
        f"<p>Thanks for getting in touch with <strong>{BUSINESS_NAME}</strong>. "
        f"We've received your message and someone will reply personally "
        f"{REPLY_WINDOW}.</p>"
        f"<p>For your records, here's what you sent us:</p>"
        f"<blockquote style='border-left:3px solid #ccc;padding-left:12px;"
        f"color:#555'>{message}</blockquote>"
        f"<p>— {BUSINESS_NAME}</p>"
    )
    return text, html


def owner_alert_body(name: str, email: str, phone: str, message: str) -> str:
    return (
        f"New enquiry from your website.\n\n"
        f"Name:    {name}\n"
        f"Email:   {email}\n"
        f"Phone:   {phone or '(not given)'}\n\n"
        f"Message:\n{message}\n\n"
        f"Reply to this email and it goes straight to {name}.\n"
        f"They've already had an automatic acknowledgement."
    )


@app.post("/enquiry")
def handle_enquiry():
    data = request.get_json(silent=True) or request.form

    # Honeypot: a field hidden with CSS that humans never see and bots always
    # fill. Return 200 so the bot believes it succeeded and doesn't retry.
    if (data.get("website") or "").strip():
        return jsonify({"ok": True}), 200

    name = (data.get("name") or "").strip()[:MAX_FIELD_LENGTH]
    email = (data.get("email") or "").strip()[:MAX_FIELD_LENGTH]
    phone = (data.get("phone") or "").strip()[:MAX_FIELD_LENGTH]
    message = (data.get("message") or "").strip()[:MAX_FIELD_LENGTH]

    missing = [f for f, v in (("name", name), ("email", email), ("message", message)) if not v]
    if missing:
        return jsonify({"ok": False, "error": f"Missing: {', '.join(missing)}"}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"ok": False, "error": "That email address doesn't look valid."}), 400

    # Log FIRST, and never let a mail failure lose the lead. Email is the nice
    # part of this product; the CSV is the part the business cannot afford to
    # lose. If SMTP is down, the enquiry still survives.
    log_failed = False
    try:
        log_enquiry(ENQUIRY_LOG, name=name, email=email, message=message, phone=phone)
    except OSError as exc:
        log_failed = True
        app.logger.error("Could not write enquiry log: %s", exc)

    text, html = customer_reply_body(name, message)
    mail_errors = []

    # Reply-To points at the owner, so if the customer replies to the automatic
    # acknowledgement it reaches the business rather than the sending account.
    try:
        send_email(
            to=email,
            subject=f"We got your message — {BUSINESS_NAME}",
            text=text,
            html=html,
            reply_to=OWNER_EMAIL or None,
        )
    except (EmailConfigError, EmailSendError) as exc:
        mail_errors.append(f"customer auto-reply: {exc}")
        app.logger.error("Customer auto-reply failed: %s", exc)

    # And here Reply-To is the *customer*, so the owner just hits reply.
    if OWNER_EMAIL:
        try:
            send_email(
                to=OWNER_EMAIL,
                subject=f"New enquiry from {name}",
                text=owner_alert_body(name, email, phone, message),
                reply_to=email,
            )
        except (EmailConfigError, EmailSendError) as exc:
            mail_errors.append(f"owner alert: {exc}")
            app.logger.error("Owner alert failed: %s", exc)

    if log_failed and mail_errors:
        # Nothing survived — the only honest response is to tell the customer
        # so they try another channel instead of assuming they've been heard.
        return jsonify({"ok": False, "error": "We couldn't record your message. Please call us."}), 500

    return jsonify({"ok": True, "warnings": mail_errors}), 200


@app.get("/health")
def health():
    """Cheap check that config is present — hit this after every deploy."""
    return jsonify(
        {
            "ok": True,
            "business_name": BUSINESS_NAME or "(unset)",
            "owner_email_set": bool(OWNER_EMAIL),
            "smtp_user_set": bool(os.getenv("SMTP_USER")),
            "log_path": str(ENQUIRY_LOG),
        }
    )


if __name__ == "__main__":
    if not BUSINESS_NAME or not OWNER_EMAIL:
        print(
            "WARNING: BUSINESS_NAME and/or OWNER_EMAIL are unset in .env — "
            "auto-replies will look unbranded and owner alerts will be skipped.",
            file=sys.stderr,
        )
    app.run(port=5000, debug=True)

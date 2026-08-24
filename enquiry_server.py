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
import time
from collections import defaultdict, deque
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

# ── Rate limiting ───────────────────────────────────────────────────────────
# ⚠️ THIS IS THE CHANGE THAT MAKES A PUBLIC URL SAFE, AND IT IS NOT OPTIONAL.
# On localhost this endpoint was reachable only by Esele. In public it will send
# a branded email to ANY address a stranger types, signed by the Gmail account in
# SMTP_USER. Without a cap that is an open relay: someone loops it, Google sees
# the volume, and the account that sends every client's mail gets suspended. The
# damage is not this demo going down, it is the sending account being lost.
#
# Two ceilings, because they stop different attacks. The per IP cap stops one
# person hammering it. The global cap stops a spread out flood from many
# addresses, and keeps the whole service well under Gmail's roughly 500 a day.
RATE_LIMIT_PER_IP_HOUR = int(os.getenv("RATE_LIMIT_PER_IP_HOUR", "5"))
RATE_LIMIT_GLOBAL_HOUR = int(os.getenv("RATE_LIMIT_GLOBAL_HOUR", "50"))

# Deques of timestamps rather than counters. A counter cannot expire: it needs a
# reset job, and whatever resets it is a second thing to get wrong. A deque holds
# when each request happened, so the window slides on its own.
#
# ⚠️ In memory, so the limits are PER WORKER PROCESS. The start command pins
# gunicorn to one worker for exactly this reason. Raise the worker count and each
# one gets its own allowance, silently multiplying the real ceiling.
_ip_hits: dict[str, deque] = defaultdict(deque)
_global_hits: deque = deque()

# Browsers block a cross origin POST unless the server says otherwise, so the
# form on a client's website cannot reach this without CORS. Set to the client's
# real domain; the "*" default is fine while nothing but curl is calling it, and
# should be narrowed the moment a real site points here.
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]

# Set to "true" on any host whose filesystem does not survive a restart, which
# includes Render's free tier. It changes no behaviour; it changes what /health
# admits and what the startup warnings say. A wrong claim about where the data
# lives is worse than no claim.
EPHEMERAL_STORAGE = os.getenv("EPHEMERAL_STORAGE", "").lower() in ("1", "true", "yes")

app = Flask(__name__)


def client_ip() -> str:
    """The caller's real address, not the proxy's.

    ⚠️ Behind Render every request arrives from the platform's proxy, so
    `request.remote_addr` is the same value for the entire internet and one
    bucket would be shared by everyone. `X-Forwarded-For` is a comma separated
    chain and the FIRST entry is the original client.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _trim(hits: deque, now: float) -> None:
    """Drop everything older than an hour off the left of the window."""
    cutoff = now - 3600
    while hits and hits[0] < cutoff:
        hits.popleft()


def rate_limited() -> str | None:
    """Return a reason string if this request should be refused, else None."""
    now = time.time()
    ip = client_ip()

    _trim(_global_hits, now)
    if len(_global_hits) >= RATE_LIMIT_GLOBAL_HOUR:
        return "global"

    hits = _ip_hits[ip]
    _trim(hits, now)
    if len(hits) >= RATE_LIMIT_PER_IP_HOUR:
        return "ip"

    hits.append(now)
    _global_hits.append(now)

    # Without this, every address that ever calls stays in the dict for the life
    # of the process. Empty deques are dead weight, so clear them out as we go.
    if not hits:
        _ip_hits.pop(ip, None)
    return None


def cors_origin() -> str | None:
    """Echo the caller's origin when it is allowed, so credentials still work."""
    origin = request.headers.get("Origin", "")
    if "*" in ALLOWED_ORIGINS:
        return origin or "*"
    return origin if origin in ALLOWED_ORIGINS else None


@app.after_request
def add_cors_headers(response):
    origin = cors_origin()
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Access-Control-Max-Age"] = "86400"
    return response


@app.route("/enquiry", methods=["OPTIONS"])
def enquiry_preflight():
    """A JSON POST from a browser is preflighted. Answer it or the form never fires.

    ⚠️ This is the failure that looks like nothing at all: curl works perfectly,
    the deployed service is healthy, and the form on the real website does
    nothing when clicked, with the reason only visible in the browser console.
    """
    return ("", 204)


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

    # ⚠️ Checked AFTER the honeypot and BEFORE anything is sent. After, because a
    # caught bot should not burn a real visitor's allowance. Before, because the
    # whole point is to refuse without touching SMTP.
    limit = rate_limited()
    if limit:
        app.logger.warning("Rate limited (%s) from %s", limit, client_ip())
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Too many enquiries from here just now. "
                    "Please try again shortly, or call us.",
                }
            ),
            429,
        )

    name = (data.get("name") or "").strip()[:MAX_FIELD_LENGTH]
    email = (data.get("email") or "").strip()[:MAX_FIELD_LENGTH]
    phone = (data.get("phone") or "").strip()[:MAX_FIELD_LENGTH]
    message = (data.get("message") or "").strip()[:MAX_FIELD_LENGTH]

    missing = [f for f, v in (("name", name), ("email", email), ("message", message)) if not v]
    if missing:
        return jsonify({"ok": False, "error": f"Missing: {', '.join(missing)}"}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"ok": False, "error": "That email address doesn't look valid."}), 400

    # Log FIRST, and never let a mail failure lose the lead. If SMTP is down, the
    # enquiry still survives.
    #
    # 🔴 THE SENTENCE THAT USED TO BE HERE IS FALSE IN PRODUCTION. It said the CSV
    # is "the part the business cannot afford to lose", which was true on a laptop
    # and is not true on Render's free tier: that filesystem is EPHEMERAL, so the
    # CSV is wiped on every deploy, every restart, and every wake from sleep.
    #
    # On this deployment the durable record is the OWNER ALERT EMAIL, because it
    # lands in a real inbox that nobody redeploys. The CSV is now a convenience,
    # and the ordering below survives only because a mail failure with a working
    # log still returns 200 while losing BOTH returns 500.
    #
    # 📌 This is the seam to replace, and it is the same seam that unblocks the
    # expo-app dashboard: swap log_enquiry for a Supabase insert and the CSV, the
    # durability problem and the mobile app's missing data source all resolve at
    # once. Until then, OWNER_EMAIL is not optional in production.
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
    """Cheap check that config is present — hit this after every deploy.

    ⚠️ It reports what is CONFIGURED, not what works. `smtp_user_set: true` means
    a value exists, not that Gmail will accept it. The only proof of a working
    chain is a real enquiry that produces two delivered emails.
    """
    return jsonify(
        {
            "ok": True,
            "business_name": BUSINESS_NAME or "(unset)",
            "owner_email_set": bool(OWNER_EMAIL),
            "smtp_user_set": bool(os.getenv("SMTP_USER")),
            "smtp_password_set": bool(os.getenv("SMTP_PASSWORD")),
            "log_path": str(ENQUIRY_LOG),
            # Surfaced rather than buried, because a CSV that silently empties
            # itself is the kind of thing that is discovered when someone asks
            # for last month's enquiries and they are gone.
            "log_is_ephemeral": EPHEMERAL_STORAGE,
            "durable_record": "owner alert email" if EPHEMERAL_STORAGE else "csv + owner alert email",
            "rate_limit_per_ip_hour": RATE_LIMIT_PER_IP_HOUR,
            "rate_limit_global_hour": RATE_LIMIT_GLOBAL_HOUR,
            "allowed_origins": ALLOWED_ORIGINS,
        }
    )


def config_warnings() -> list[str]:
    """Everything that would make a live deployment quietly wrong."""
    problems = []
    if not BUSINESS_NAME:
        problems.append("BUSINESS_NAME unset — auto-replies will look unbranded.")
    if not OWNER_EMAIL:
        problems.append(
            "OWNER_EMAIL unset — owner alerts are SKIPPED. On ephemeral storage "
            "that means an enquiry can leave no durable trace at all."
        )
    if not os.getenv("SMTP_PASSWORD"):
        problems.append("SMTP_PASSWORD unset — no email can be sent.")
    if EPHEMERAL_STORAGE and not OWNER_EMAIL:
        problems.append(
            "EPHEMERAL_STORAGE with no OWNER_EMAIL is the one combination that "
            "loses enquiries permanently."
        )
    return problems


# Printed at import time so the warnings appear in the Render log too, not only
# when the file is run directly. Under gunicorn the __main__ block never runs.
for _problem in config_warnings():
    print(f"CONFIG WARNING: {_problem}", file=sys.stderr)


if __name__ == "__main__":
    # ⚠️ NEVER `debug=True` HERE AGAIN. The Werkzeug debugger exposes an
    # interactive Python console on any unhandled exception. On a public URL that
    # is remote code execution on the box holding the SMTP credentials. It was
    # harmless while this only ever bound to localhost.
    #
    # ⚠️ PORT and HOST come from the environment. Hard coding 5000 is what makes a
    # platform health check fail to connect, and it is the exact bug that had to
    # be fixed in ai-lab's server.py before Render would accept it.
    #
    # This block is for LOCAL runs only. Render uses gunicorn, which does not run
    # on Windows, so local testing keeps the Flask server.
    port = int(os.getenv("PORT", "5000"))
    host = os.getenv("HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=False)

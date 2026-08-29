"""Checks for the two email transports. Sends nothing and needs no key.

    python test_send_email.py

Every network call is stubbed. A suite that really sent email is one nobody
dares run twice, and on the Brevo free plan each run would eat the 300 a day.
"""

import io
import json
import os
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools import send_email as se  # noqa: E402

passed = failed = 0


def check(label: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}")


def set_env(**values) -> None:
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


class FakeResponse:
    def __init__(self, status: int = 201):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def capture(status: int = 201):
    """Replace urlopen and record what would have gone to Brevo."""
    sent = {}

    def fake_urlopen(request, timeout=None):
        sent["url"] = request.full_url
        sent["method"] = request.method
        sent["headers"] = {k.lower(): v for k, v in request.headers.items()}
        sent["body"] = json.loads(request.data.decode())
        sent["timeout"] = timeout
        return FakeResponse(status)

    se.urllib.request.urlopen = fake_urlopen
    return sent


def raiser(exc):
    def fake_urlopen(request, timeout=None):
        raise exc

    se.urllib.request.urlopen = fake_urlopen


real_urlopen = se.urllib.request.urlopen

print("\ntransport selection")
set_env(EMAIL_TRANSPORT=None, BREVO_API_KEY=None)
check("no key falls back to smtp", se._transport() == "smtp")
set_env(BREVO_API_KEY="xkeysib-test")
# The safe direction: on a host that blocks SMTP, defaulting to SMTP hangs, and
# a hang is far harder to diagnose than a missing key.
check("a key switches to brevo automatically", se._transport() == "brevo")
set_env(EMAIL_TRANSPORT="smtp")
check("an explicit setting overrides the key", se._transport() == "smtp")
set_env(EMAIL_TRANSPORT="sendgrid")
try:
    se._transport()
    check("an unknown transport is refused", False)
except se.EmailConfigError as exc:
    check("an unknown transport is refused", "expected" in str(exc))
set_env(EMAIL_TRANSPORT=None)

print("\nbrevo config")
set_env(BREVO_API_KEY=None)
try:
    se._send_brevo("a@b.com", "s", "t", None, None)
    check("a missing API key is refused", False)
except se.EmailConfigError as exc:
    check("a missing API key is refused", "BREVO_API_KEY" in str(exc))

set_env(BREVO_API_KEY="xkeysib-test", BREVO_SENDER_EMAIL=None)
original_user = se.SMTP_USER
se.SMTP_USER = ""
try:
    se._send_brevo("a@b.com", "s", "t", None, None)
    check("no sender address at all is refused", False)
except se.EmailConfigError as exc:
    check("no sender address at all is refused", "sender" in str(exc).lower())
se.SMTP_USER = original_user

print("\npayload")
set_env(BREVO_SENDER_EMAIL="sender@clinic.com")
se.FROM_NAME = "Bright Smile Dental"
body = se.brevo_payload("cust@x.com", "Subject", "plain", "<p>rich</p>", "owner@clinic.com")
check("sender is the verified address", body["sender"]["email"] == "sender@clinic.com")
check("from name is carried", body["sender"]["name"] == "Bright Smile Dental")
check("recipient is a list of objects", body["to"] == [{"email": "cust@x.com"}])
check("subject is set", body["subject"] == "Subject")
check("plain text is always present", body["textContent"] == "plain")
check("html is included when given", body["htmlContent"] == "<p>rich</p>")
# The whole product is this line. Lose it and the tool is a bell, not a tool.
check("reply-to is set", body["replyTo"] == {"email": "owner@clinic.com"})

bare = se.brevo_payload("cust@x.com", "S", "plain", None, None)
check("no html key when there is no html", "htmlContent" not in bare)
check("no replyTo key when there is none", "replyTo" not in bare)
check("plain text survives anyway", bare["textContent"] == "plain")

print("\nthe request itself")
sent = capture()
se._send_brevo("cust@x.com", "S", "plain", None, "owner@clinic.com")
check("posts to Brevo's transactional endpoint", sent["url"] == se.BREVO_ENDPOINT)
check("uses HTTPS, which no host blocks", sent["url"].startswith("https://"))
check("method is POST", sent["method"] == "POST")
check("api key travels in the api-key header", sent["headers"].get("Api-key".lower()) == "xkeysib-test")
check("declares json", sent["headers"].get("content-type") == "application/json")
# Must stay under gunicorn's 60s worker timeout: two sends happen per enquiry,
# and a worker killed mid request produces no readable error at all.
check("a timeout is always passed", sent["timeout"] == se.HTTP_TIMEOUT)
check("the timeout leaves room for two sends", se.HTTP_TIMEOUT * 2 < 60)

print("\nfailures are reported, not swallowed")
raiser(urllib.error.HTTPError(se.BREVO_ENDPOINT, 401, "Unauthorized", {}, io.BytesIO(b'{"message":"Key not found"}')))
try:
    se._send_brevo("cust@x.com", "S", "t", None, None)
    check("a 401 raises", False)
except se.EmailSendError as exc:
    check("a 401 raises", True)
    # Brevo puts the actual reason in the body and nowhere else.
    check("the response body is preserved", "Key not found" in str(exc))
    check("the usual causes are named", "verified" in str(exc))

raiser(urllib.error.HTTPError(se.BREVO_ENDPOINT, 400, "Bad Request", {}, io.BytesIO(b'{"message":"Sender not valid"}')))
try:
    se._send_brevo("cust@x.com", "S", "t", None, None)
    check("a 400 raises", False)
except se.EmailSendError as exc:
    check("a 400 raises", "Sender not valid" in str(exc))

raiser(urllib.error.URLError("connection refused"))
try:
    se._send_brevo("cust@x.com", "S", "t", None, None)
    check("an unreachable API raises", False)
except se.EmailSendError as exc:
    check("an unreachable API raises", "reach Brevo" in str(exc))

sent = capture(status=500)
try:
    se._send_brevo("cust@x.com", "S", "t", None, None)
    check("a non success status raises", False)
except se.EmailSendError as exc:
    check("a non success status raises", "500" in str(exc))

print("\nsmtp still names the hang for what it is")
se.urllib.request.urlopen = real_urlopen
set_env(BREVO_API_KEY=None, EMAIL_TRANSPORT="smtp")
se.SMTP_USER = "x@gmail.com"
se.SMTP_PASSWORD = "abcd efgh ijkl mnop"
try:
    se.send_email("a@b.com", "S", "t")
    check("spaces in the App Password are caught before connecting", False)
except se.EmailConfigError as exc:
    check("spaces in the App Password are caught before connecting", "spaces" in str(exc))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

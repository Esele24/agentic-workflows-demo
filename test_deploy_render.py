"""Checks for deploy_render.py — everything except the HTTP call.

The create call itself needs a live Render key, so it is not covered here and
DEPLOY.md says so. Input validation, payload construction and secret masking
are. Pretending otherwise is how a "passing" suite ends up proving nothing.

    python test_deploy_render.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deploy_render import (  # noqa: E402
    PUBLIC_ENV,
    REQUIRED_KEYS,
    DeployError,
    build_payload,
    load_env,
    mask,
)

passed = failed = 0


def check(label: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}")


def write_env(**overrides) -> Path:
    values = {
        "BREVO_API_KEY": "xkeysib-abc123def456",
        "BREVO_SENDER_EMAIL": "hello@clinic.com",
        "OWNER_EMAIL": "owner@gmail.com",
        "FROM_NAME": "Bright Smile",
        "BUSINESS_NAME": "Bright Smile Dental",
    }
    values.update(overrides)
    tmp = Path(tempfile.mkdtemp()) / ".env"
    tmp.write_text("\n".join(f"{k}={v}" for k, v in values.items() if v is not None))
    return tmp


def expect_error(label: str, fragment: str, **overrides) -> None:
    try:
        load_env(write_env(**overrides))
        check(label, False)
    except DeployError as exc:
        check(label, fragment.lower() in str(exc).lower())


print("\nvalid env file")
env = load_env(write_env())
check("all required values load", set(env) == set(REQUIRED_KEYS))
check("values are stripped", env["BUSINESS_NAME"] == "Bright Smile Dental")

print("\nthe Brevo key")
expect_error("a missing key is refused", "BREVO_API_KEY", BREVO_API_KEY="")
# Brevo's SMTP key and its v3 API key sit on the same dashboard page and look
# similar. Only the xkeysib- one works against the HTTP API.
expect_error("an SMTP key is refused", "xkeysib-", BREVO_API_KEY="smtp-key-9912")

print("\nthe sender must be one Brevo has verified")
expect_error("a malformed sender is refused", "not an email", BREVO_SENDER_EMAIL="clinic.com")
# An env file written before Brevo existed still deploys: send_email.py has the
# same fallback, so the two cannot disagree.
fallback = load_env(write_env(BREVO_SENDER_EMAIL="", SMTP_USER="legacy@gmail.com"))
check("falls back to SMTP_USER, matching send_email.py", fallback["BREVO_SENDER_EMAIL"] == "legacy@gmail.com")

print("\nvalues whose absence deploys something quietly broken")
for key in REQUIRED_KEYS:
    if key == "BREVO_SENDER_EMAIL":
        continue  # has a documented fallback, covered above
    expect_error(f"missing {key} is refused", key, **{key: ""})
# Ephemeral storage plus no owner email is the one combination that loses an
# enquiry with no trace anywhere, so it must never reach Render.
expect_error("a malformed OWNER_EMAIL is refused", "not an email", OWNER_EMAIL="nope")

print("\nmissing file")
try:
    load_env(Path(tempfile.mkdtemp()) / "absent.env")
    check("a missing env file is refused", False)
except DeployError as exc:
    check("a missing env file is refused", "no env file" in str(exc).lower())

print("\npayload")
payload = build_payload("own-123", "enquiry-autoresponder", load_env(write_env()))
keys = [v["key"] for v in payload["envVars"]]
check("carries every required value", all(k in keys for k in REQUIRED_KEYS))
check("carries the public defaults", all(k in keys for k in PUBLIC_ENV))
check("no duplicate env keys", len(keys) == len(set(keys)))
# Render's free tier blocks ports 25, 465 and 587, so an App Password sent there
# is exposure with no upside: the transport that would use it cannot run.
check("no Gmail App Password is sent to Render", "SMTP_PASSWORD" not in keys)
check("the transport is pinned to brevo", ("EMAIL_TRANSPORT", "brevo") in [(v["key"], v["value"]) for v in payload["envVars"]])
check("owner id is set", payload["ownerId"] == "own-123")
check("health check path is set", payload["serviceDetails"]["healthCheckPath"] == "/health")
# Both load bearing, both fail silently if lost. One worker is what keeps the
# in-memory rate limiter's ceiling real; binding 0.0.0.0 is what lets Render's
# health check connect at all.
start = payload["serviceDetails"]["envSpecificDetails"]["startCommand"]
check("gunicorn is pinned to one worker", "--workers 1" in start)
check("binds 0.0.0.0, not localhost", "0.0.0.0:$PORT" in start)
check("free plan", payload["serviceDetails"]["plan"] == "free")

print("\nmasking — scrollback gets screenshotted and pasted")
check("the Brevo key never appears", "xkeysib-abc123def456" not in mask("BREVO_API_KEY", "xkeysib-abc123def456"))
check("its length is still reported", "chars" in mask("BREVO_API_KEY", "xkeysib-abc123def456"))
check("an App Password would still be hidden", "hidden" in mask("SMTP_PASSWORD", "abcdefghijklmnop"))
check("emails are partly hidden", mask("OWNER_EMAIL", "owner@gmail.com") == "ow***@gmail.com")
check("the sender is masked too", mask("BREVO_SENDER_EMAIL", "hello@clinic.com") == "he***@clinic.com")
check("the domain survives, to catch a typo", "clinic.com" in mask("BREVO_SENDER_EMAIL", "hello@clinic.com"))
check("non-secrets print in full", mask("BUSINESS_NAME", "Bright Smile Dental") == "Bright Smile Dental")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

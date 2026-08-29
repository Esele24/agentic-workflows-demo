"""Checks for deploy_render.py — everything except the HTTP call.

The network call cannot be tested without a live Render key, and pretending
otherwise is how a "passing" suite ends up proving nothing. So this file draws
the line explicitly: input validation, payload construction and secret masking
are covered here; the request shape is NOT, and DEPLOY.md says so.

    python test_deploy_render.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deploy_render import (  # noqa: E402
    PUBLIC_ENV,
    SECRET_KEYS,
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
        "SMTP_USER": "sender@gmail.com",
        "SMTP_PASSWORD": "abcdefghijklmnop",
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
check("all five values load", set(env) == set(SECRET_KEYS))
check("values are stripped", env["BUSINESS_NAME"] == "Bright Smile Dental")

print("\nthe App Password mistakes that fail at SMTP login")
# Google displays it in four groups of four; pasting the spaces is the single
# most common setup error and the SMTP error it produces never mentions spaces.
expect_error("spaces in the password are refused", "spaces", SMTP_PASSWORD="abcd efgh ijkl mnop")
expect_error("a wrong length password is refused", "16", SMTP_PASSWORD="short")
expect_error("an account password is refused", "16", SMTP_PASSWORD="my-real-gmail-password")

print("\nvalues whose absence deploys something quietly broken")
for key in SECRET_KEYS:
    expect_error(f"missing {key} is refused", key, **{key: ""})
# Ephemeral storage plus no owner email is the one combination that loses an
# enquiry with no trace anywhere, so it must never reach Render.
expect_error("a malformed OWNER_EMAIL is refused", "email address", OWNER_EMAIL="not-an-email")

print("\nmissing file")
try:
    load_env(Path(tempfile.mkdtemp()) / "absent.env")
    check("a missing env file is refused", False)
except DeployError as exc:
    check("a missing env file is refused", "no env file" in str(exc).lower())

print("\npayload")
payload = build_payload("own-123", "enquiry-autoresponder", load_env(write_env()))
keys = [v["key"] for v in payload["envVars"]]
check("carries all five prompted values", all(k in keys for k in SECRET_KEYS))
check("carries the public defaults", all(k in keys for k in PUBLIC_ENV))
check("no duplicate env keys", len(keys) == len(set(keys)))
check("owner id is set", payload["ownerId"] == "own-123")
check("health check path is set", payload["serviceDetails"]["healthCheckPath"] == "/health")
# Both of these are load bearing and both fail silently if lost. One worker is
# what keeps the in-memory rate limiter's ceiling real; binding 0.0.0.0 is what
# lets Render's health check connect at all.
start = payload["serviceDetails"]["envSpecificDetails"]["startCommand"]
check("gunicorn is pinned to one worker", "--workers 1" in start)
check("binds 0.0.0.0, not localhost", "0.0.0.0:$PORT" in start)
check("free plan", payload["serviceDetails"]["plan"] == "free")

print("\nmasking — scrollback gets screenshotted and pasted")
check("the App Password never appears", "abcdefghijklmnop" not in mask("SMTP_PASSWORD", "abcdefghijklmnop"))
check("its length is still reported", "16 chars" in mask("SMTP_PASSWORD", "abcdefghijklmnop"))
check("emails are partly hidden", mask("SMTP_USER", "sender@gmail.com") == "se***@gmail.com")
check("the domain survives, to catch a typo", "gmail.com" in mask("OWNER_EMAIL", "owner@gmail.com"))
check("non-secrets print in full", mask("BUSINESS_NAME", "Bright Smile Dental") == "Bright Smile Dental")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

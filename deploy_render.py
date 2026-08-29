"""Provision the enquiry autoresponder on Render from the command line.

WHY THIS EXISTS
    Render has no CLI for creating a service, so DEPLOY.md's six dashboard
    clicks were the only route. That is fine once. It is not fine when this
    service becomes a per client product: every client Esele sells the
    autoresponder to needs their OWN deployment, with their own BUSINESS_NAME,
    their own OWNER_EMAIL and their own sending account. Six clicks and a hand
    typed 16 character password, per client, is where mistakes live.

    This script does the same thing through Render's REST API, reading the
    values from a .env file so nothing is retyped.

⚠️ HONEST STATUS: THE --create PATH HAS NEVER BEEN RUN AGAINST THE LIVE API.
    There was no Render API key on this machine when it was written, so the
    request shape below is built from Render's documented v1 schema and has NOT
    been confirmed by a successful call. Treat a failure here as "the shape is
    wrong", not "the account is broken", and fall back to the six clicks in
    DEPLOY.md, which remain the guaranteed path.

    That is also why --check is the default and why every failure prints
    Render's own response body verbatim rather than a summary. A wrong guess
    should be legible in one read.

USAGE
    # 1. Make a key: Render dashboard, Account Settings, API Keys, Create.
    $env:RENDER_API_KEY = "rnd_..."

    # 2. Dry run. Validates the key, the owner, and every value it would send.
    #    Sends nothing. Prints the exact payload with secrets masked.
    python deploy_render.py

    # 3. Do it.
    python deploy_render.py --create

    # For a client deployment, point at their own env file:
    python deploy_render.py --env-file clients/best-smilez.env --create

AFTER IT RETURNS
    The service URL is printed. Then run the two checks in DEPLOY.md, and do
    not skip the second one: /health reports what is CONFIGURED, not what
    works, so only a real enquiry that delivers two emails proves the chain.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

API = "https://api.render.com/v1"
PROJECT_ROOT = Path(__file__).resolve().parent

REPO = "https://github.com/Esele24/agentic-workflows-demo"
BRANCH = "main"

# Mirrors render.yaml. If you change one, change the other, and read the two
# warnings in that file before touching startCommand: --workers 1 is what keeps
# the rate limiter honest, and binding 0.0.0.0 is what lets the health check
# connect at all.
BUILD_COMMAND = "pip install -r requirements.txt"
START_COMMAND = "gunicorn enquiry_server:app --bind 0.0.0.0:$PORT --workers 1 --timeout 60"
HEALTH_PATH = "/health"
REGION = "frankfurt"  # closest of Render's free regions to Nigeria
PLAN = "free"

# Prompted by the blueprint, so they must come from the env file here.
#
# ⚠️ SMTP_USER AND SMTP_PASSWORD ARE DELIBERATELY ABSENT, and this is a change
# from the first version. Render's free tier blocks outbound ports 25, 465 and
# 587, so the SMTP transport cannot work there at all: it hangs until gunicorn
# kills the worker. Shipping a Gmail App Password to a host that is physically
# unable to use it is exposure with no upside, so it is not sent.
REQUIRED_KEYS = (
    "BREVO_API_KEY",
    "BREVO_SENDER_EMAIL",
    "OWNER_EMAIL",
    "FROM_NAME",
    "BUSINESS_NAME",
)

# Not secret, and the defaults matter. Same values as render.yaml.
PUBLIC_ENV = {
    # Pinned rather than left to the automatic choice. The auto rule picks Brevo
    # whenever a key is present, but on this host being explicit means a missing
    # key fails loudly instead of silently falling back to a transport that hangs.
    "EMAIL_TRANSPORT": "brevo",
    "REPLY_WINDOW": "within 24 hours",
    "EPHEMERAL_STORAGE": "true",
    "RATE_LIMIT_PER_IP_HOUR": "5",
    "RATE_LIMIT_GLOBAL_HOUR": "50",
    "ALLOWED_ORIGINS": "*",
    "PYTHON_VERSION": "3.13.1",
}


class DeployError(Exception):
    """Something is wrong with the inputs or with Render's answer."""


def mask(key: str, value: str) -> str:
    """Never print a secret in full, not even into a terminal he trusts.

    Scrollback gets pasted into chats and screenshots. SMTP_PASSWORD is the one
    value here whose leak costs the sending account, so it is masked entirely
    rather than partially.
    """
    if key in ("SMTP_PASSWORD", "BREVO_API_KEY"):
        return f"<{len(value)} chars, hidden>"
    if key in ("SMTP_USER", "OWNER_EMAIL", "BREVO_SENDER_EMAIL") and "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:2]}***@{domain}"
    return value


def request(method: str, path: str, token: str, body: dict | None = None) -> object:
    """One call to Render, with the error body preserved.

    ⚠️ The `except HTTPError` block reads and re-raises the response body. Render
    explains a rejected payload in that body and nowhere else; swallowing it
    turns a one line fix ("unknown field: env") into an afternoon of guessing.
    """
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        if exc.code == 401:
            raise DeployError(
                "Render rejected the API key (401). Generate one at Render, "
                "Account Settings, API Keys, and set RENDER_API_KEY."
            ) from exc
        raise DeployError(f"Render returned HTTP {exc.code} for {method} {path}:\n{detail}") from exc
    except urllib.error.URLError as exc:
        raise DeployError(f"Could not reach {API}: {exc.reason}") from exc


def load_env(env_file: Path) -> dict[str, str]:
    """Read the five prompted values, and refuse anything that would deploy wrong."""
    if not env_file.exists():
        raise DeployError(f"No env file at {env_file}")

    values = {k: (v or "").strip() for k, v in dotenv_values(env_file).items()}
    resolved = {k: values.get(k, "") for k in REQUIRED_KEYS}

    # BREVO_SENDER_EMAIL falls back to SMTP_USER, matching send_email.py, so an
    # env file written before Brevo existed still deploys.
    if not resolved["BREVO_SENDER_EMAIL"]:
        resolved["BREVO_SENDER_EMAIL"] = values.get("SMTP_USER", "")

    missing = [k for k, v in resolved.items() if not v]
    if missing:
        raise DeployError(
            f"{env_file.name} is missing: {', '.join(missing)}.\n\n"
            "BREVO_API_KEY comes from Brevo, SMTP & API, API Keys.\n"
            "BREVO_SENDER_EMAIL must be an address you VERIFIED in Brevo under "
            "Senders, Domains & Dedicated IPs."
        )

    if not resolved["BREVO_API_KEY"].startswith("xkeysib-"):
        raise DeployError(
            "BREVO_API_KEY does not look like a Brevo v3 API key: those start "
            "with 'xkeysib-'. An SMTP key from the same page will not work "
            "against the HTTP API."
        )

    for key in ("OWNER_EMAIL", "BREVO_SENDER_EMAIL"):
        if "@" not in resolved[key]:
            raise DeployError(f"{key} is not an email address.")

    # OWNER_EMAIL is where the durable record of every enquiry lands, because
    # Render's filesystem is ephemeral and the CSV does not survive a restart.
    # Deploying without it is the one combination that loses enquiries with no
    # trace, which is why enquiry_server.py warns about it at import time.
    return resolved


def build_payload(owner_id: str, name: str, env: dict[str, str]) -> dict:
    env_vars = [{"key": k, "value": v} for k, v in env.items()]
    env_vars += [{"key": k, "value": v} for k, v in PUBLIC_ENV.items()]
    return {
        "type": "web_service",
        "name": name,
        "ownerId": owner_id,
        "repo": REPO,
        "branch": BRANCH,
        "autoDeploy": "yes",
        "envVars": env_vars,
        "serviceDetails": {
            "runtime": "python",
            "plan": PLAN,
            "region": REGION,
            "healthCheckPath": HEALTH_PATH,
            "envSpecificDetails": {
                "buildCommand": BUILD_COMMAND,
                "startCommand": START_COMMAND,
            },
        },
    }


def resolve_owner(token: str, wanted: str | None) -> tuple[str, str]:
    owners = request("GET", "/owners?limit=50", token) or []
    entries = [o.get("owner", o) for o in owners]
    if not entries:
        raise DeployError("This API key can see no Render owners or workspaces.")
    if wanted:
        for o in entries:
            if wanted in (o.get("id"), o.get("name"), o.get("email")):
                return o["id"], o.get("name") or o.get("email") or o["id"]
        names = ", ".join(str(o.get("name") or o.get("email")) for o in entries)
        raise DeployError(f"No owner matching '{wanted}'. Available: {names}")
    if len(entries) > 1:
        names = ", ".join(str(o.get("name") or o.get("email")) for o in entries)
        raise DeployError(f"This key sees several owners. Pass --owner. Available: {names}")
    o = entries[0]
    return o["id"], o.get("name") or o.get("email") or o["id"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Provision the enquiry autoresponder on Render.")
    ap.add_argument("--create", action="store_true", help="actually create it (default is a dry run)")
    ap.add_argument("--env-file", default=".env", help="env file to read the five values from")
    ap.add_argument("--name", default="enquiry-autoresponder", help="Render service name")
    ap.add_argument("--owner", default=None, help="workspace name, email or id, if the key sees several")
    args = ap.parse_args()

    # ⚠️ Strip surrounding quotes, not just whitespace. In cmd.exe
    # `set KEY="rnd_abc"` stores the quotes AS PART OF THE VALUE, so the key
    # travels to Render as "rnd_abc" with the quote characters attached and comes
    # back 401. That reads as a bad key and sends you to regenerate a key that was
    # fine. Same family as the trailing newline that broke the ai-lab BACKEND_URL.
    token = os.getenv("RENDER_API_KEY", "").strip().strip('"').strip("'").strip()
    if not token:
        print(
            "RENDER_API_KEY is not set in THIS terminal.\n\n"
            "Check which shell you are in. The prompt tells you:\n"
            "  PS C:\\...>   PowerShell\n"
            "  C:\\...>      cmd, and the syntax below is different\n\n"
            "Get the key: Render dashboard, Account Settings, API Keys, Create API Key.\n"
            "Copy it immediately, Render shows it once.\n\n"
            "PowerShell:\n"
            '  $env:RENDER_API_KEY = "rnd_yourkey"\n\n'
            "cmd:\n"
            '  set "RENDER_API_KEY=rnd_yourkey"\n\n'
            "In cmd, keep the quotes around the WHOLE assignment as shown. Writing\n"
            '  set RENDER_API_KEY="rnd_yourkey"\n'
            "stores the quote characters inside the value and Render answers 401.\n\n"
            "Either way the variable lives only in that terminal window. A new\n"
            "terminal, or a restarted VS Code, means setting it again.\n",
            file=sys.stderr,
        )
        return 2

    if not token.startswith("rnd_"):
        print(
            f"RENDER_API_KEY is set but does not look like a Render key: it starts "
            f"with {token[:4]!r} and Render keys start with 'rnd_'.\n"
            "Most likely the shell kept some punctuation from the assignment. "
            "Re-set it and check the syntax note above.",
            file=sys.stderr,
        )
        return 2

    env_path = Path(args.env_file)
    if not env_path.is_absolute():
        env_path = PROJECT_ROOT / env_path

    try:
        env = load_env(env_path)
        owner_id, owner_name = resolve_owner(token, args.owner)
        payload = build_payload(owner_id, args.name, env)

        print(f"Owner:   {owner_name} ({owner_id})")
        print(f"Service: {args.name}   {PLAN} plan, {REGION}")
        print(f"Repo:    {REPO} @ {BRANCH}")
        print(f"Env:     {env_path}")
        print("\nEnvironment variables that would be set:")
        for item in payload["envVars"]:
            print(f"  {item['key']:<24} {mask(item['key'], item['value'])}")

        if not args.create:
            print("\nDry run. Nothing was sent. Re-run with --create to provision.")
            return 0

        print("\nCreating the service...")
        result = request("POST", "/services", token, payload) or {}
        service = result.get("service", result)
        url = service.get("serviceDetails", {}).get("url") or "(read it off the dashboard)"

        print(f"\nCreated. id={service.get('id')}")
        print(f"URL: {url}")
        print(
            "\n⚠️ The first build takes a few minutes, and the URL is NOT derivable: "
            "Render appends a random suffix when the plain name is taken, exactly as "
            "it did for ai-lab-backend-hhrb. Read the real hostname off the dashboard.\n"
            "\nNow run BOTH checks in DEPLOY.md. /health only proves config exists. "
            "The only proof of a working chain is a real enquiry that delivers two emails."
        )
        return 0

    except DeployError as exc:
        print(f"\n{exc}", file=sys.stderr)
        print(
            "\nThe six dashboard steps in DEPLOY.md still work and are the "
            "guaranteed path. This script is the convenience, not the contract.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Read recent Gmail messages, and create drafts. The Gmail layer of the assistant.

Scopes are deliberately readonly + compose. There is NO send scope anywhere in
this project: the tool is physically incapable of sending mail on someone's
behalf. That is the safety property that makes it acceptable to point at a
business inbox at all — a human reviews and sends every reply.

First run opens a browser to authorize and caches token.json. If you previously
authorized with a different scope set, delete token.json and re-run.

Usage:
    python tools/gmail_inbox.py --max 10
    python tools/gmail_inbox.py --query "is:unread newer_than:7d" --max 20

Required files (see PROJECT/ for an existing OAuth client, or Google Cloud
Console -> Gmail API -> OAuth client ID of type "Desktop app"):
    credentials.json    OAuth client, path overridable via GMAIL_CREDENTIALS_JSON
    token.json          cached after first authorization, via GMAIL_TOKEN_JSON
"""

import argparse
import base64
import os
import sys
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# readonly = look at the inbox. compose = create drafts. No send scope, ever.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]

MAX_BODY_CHARS = 4000  # long threads blow up prompt cost for no extra signal


def get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds_path = Path(
        os.getenv("GMAIL_CREDENTIALS_JSON", str(PROJECT_ROOT / "credentials.json"))
    )
    token_path = Path(os.getenv("GMAIL_TOKEN_JSON", str(PROJECT_ROOT / "token.json")))

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise RuntimeError(
                    f"OAuth client file not found at {creds_path}. Copy one from "
                    "PROJECT/credentials.json or create a Desktop-app OAuth client "
                    "in Google Cloud Console with the Gmail API enabled."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)


def _header(payload: dict, name: str) -> str:
    for header in payload.get("headers", []):
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _extract_body(payload: dict) -> str:
    """Walk the MIME tree for the best plain-text body.

    Gmail nests parts arbitrarily deep (multipart/alternative inside
    multipart/mixed, etc.), so this recurses. Plain text is preferred; HTML is
    only used when there is no text/plain part anywhere.
    """
    plain, html = [], []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data:
            decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            if mime == "text/plain":
                plain.append(decoded)
            elif mime == "text/html":
                html.append(decoded)
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    body = "\n".join(plain) if plain else "\n".join(html)
    return body.strip()[:MAX_BODY_CHARS]


def list_recent(
    service,
    query: str = "newer_than:7d",
    max_results: int = 10,
    headers_only: bool = False,
) -> list[dict]:
    """Return recent messages as dicts. `query` uses normal Gmail search syntax.

    `headers_only` fetches just From/Subject/Date and skips message bodies. Use
    it for counting and triage: it's faster, cheaper, and reads less of the
    user's mail than the task requires.
    """
    listing = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )

    messages = []
    for stub in listing.get("messages", []):
        get_kwargs = {"userId": "me", "id": stub["id"]}
        if headers_only:
            get_kwargs["format"] = "metadata"
            get_kwargs["metadataHeaders"] = ["From", "Subject", "Date"]
        else:
            get_kwargs["format"] = "full"
        full = service.users().messages().get(**get_kwargs).execute()
        payload = full.get("payload", {})
        messages.append(
            {
                "id": full["id"],
                "thread_id": full.get("threadId", ""),
                "from": _header(payload, "From"),
                "to": _header(payload, "To"),
                "subject": _header(payload, "Subject"),
                "date": _header(payload, "Date"),
                "snippet": full.get("snippet", ""),
                "body": "" if headers_only else _extract_body(payload),
            }
        )
    return messages


def create_draft(service, to: str, subject: str, body: str, thread_id: str = "") -> str:
    """Create a reply draft. Returns the draft id. Never sends."""
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = to
    message["subject"] = subject

    payload = {"message": {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}}
    if thread_id:
        # Threading the draft keeps it in the original conversation, so the boss
        # sees it in context rather than as a stray new message.
        payload["message"]["threadId"] = thread_id

    draft = service.users().drafts().create(userId="me", body=payload).execute()
    return draft.get("id", "")


def main() -> int:
    parser = argparse.ArgumentParser(description="List recent Gmail messages")
    parser.add_argument("--query", default="newer_than:7d", help="Gmail search query")
    parser.add_argument("--max", type=int, default=10, help="How many messages")
    args = parser.parse_args()

    try:
        service = get_service()
        messages = list_recent(service, query=args.query, max_results=args.max)
    except Exception as exc:  # noqa: BLE001 — surface any auth/API failure plainly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not messages:
        print(f"No messages matched: {args.query}")
        return 0

    for msg in messages:
        print(f"\n--- {msg['subject'] or '(no subject)'}")
        print(f"    from: {msg['from']}")
        print(f"    date: {msg['date']}")
        print(f"    {msg['snippet'][:150]}")
    print(f"\n{len(messages)} message(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

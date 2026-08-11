"""Classify an email against the playbook and draft a reply. Never sends.

The categories live in config/email_playbook.md, NOT in this file. That is the
whole design: when the boss says which emails he actually gets, you edit the
markdown and this code is untouched.

Usage — score the classifier against the test fixtures:
    python tools/classify_email.py --test

Classify one email from a JSON file ({from, subject, body}):
    python tools/classify_email.py --file tmp/one_email.json

Required in .env:
    ANTHROPIC_API_KEY
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

PLAYBOOK_PATH = PROJECT_ROOT / "config" / "email_playbook.md"
FIXTURES_PATH = PROJECT_ROOT / "tests" / "fixtures" / "emails.json"

MODEL = "claude-opus-4-8"

# A raw JSON schema rather than a Pydantic model: this project's environment has
# pydantic 1.x, and the SDK's messages.parse() helper needs pydantic 2.x.
# Upgrading pydantic globally would risk breaking EMBEDDING DEMO and PROJECT, so
# the schema is declared by hand. The guarantee is identical — the API constrains
# the response to this shape, so json.loads() below cannot fail on a malformed body.
CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "category_id": {
            "type": "string",
            "description": "The `id` of the matching playbook category",
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "reasoning": {
            "type": "string",
            "description": "One sentence on why this category matched",
        },
        "should_draft": {
            "type": "boolean",
            "description": "True only if the category is draft-only AND a useful reply is possible",
        },
        "draft_subject": {
            "type": "string",
            "description": "Reply subject line, or empty string if should_draft is false",
        },
        "draft_body": {
            "type": "string",
            "description": "The draft reply, or empty string if should_draft is false",
        },
        "blanks_to_fill": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Every [CONFIRM: ...] / [ATTACH: ...] placeholder left in the draft",
        },
    },
    "required": [
        "category_id",
        "confidence",
        "reasoning",
        "should_draft",
        "draft_subject",
        "draft_body",
        "blanks_to_fill",
    ],
    "additionalProperties": False,
}


SYSTEM = """You triage a manager's work inbox at a Nigerian oil servicing company \
(wellhead maintenance, wellhead intervention, fabrication).

You will be given a playbook defining the email categories, the tone, and the \
drafting rules. Follow it exactly. The playbook is authoritative — if it conflicts \
with your instincts, the playbook wins.

Two hard rules that override everything else:

1. NEVER invent a fact. No prices, dates, job statuses, payment confirmations, or \
commitments. Where a real detail is needed, leave a visible placeholder like \
[CONFIRM: completion date] so the human must fill it before sending. A visible gap \
is safe; a plausible invention is not.

2. If the email does not clearly match a category, use `other` and set \
should_draft to false. A wrong draft costs more than no draft."""


def load_playbook() -> str:
    if not PLAYBOOK_PATH.exists():
        raise FileNotFoundError(
            f"Playbook not found at {PLAYBOOK_PATH}. It defines the categories — "
            "the classifier cannot run without it."
        )
    return PLAYBOOK_PATH.read_text(encoding="utf-8")


def classify(client, playbook: str, sender: str, subject: str, body: str) -> dict:
    """Classify one email and draft a reply if the playbook allows it."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        # Adaptive thinking lets the model reason about ambiguous emails without a
        # fixed token budget. `effort: medium` keeps cost sane for a triage task.
        thinking={"type": "adaptive"},
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": CLASSIFICATION_SCHEMA},
        },
        system=[
            {"type": "text", "text": SYSTEM},
            {"type": "text", "text": f"<playbook>\n{playbook}\n</playbook>"},
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Classify and, if the playbook allows, draft a reply to this email.\n\n"
                    f"From: {sender}\nSubject: {subject}\n\n{body}"
                ),
            }
        ],
    )

    if response.stop_reason == "max_tokens":
        raise RuntimeError("Response hit max_tokens — the JSON is truncated. Raise max_tokens.")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(f"No text block in response (stop_reason={response.stop_reason})")
    return json.loads(text)


def run_tests(client, playbook: str) -> int:
    """Score the classifier against the fixtures. Returns an exit code."""
    fixtures = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))["emails"]

    correct = 0
    draft_checked = 0
    draft_correct = 0
    unsafe = []

    for email in fixtures:
        try:
            result = classify(
                client, playbook, email["from"], email["subject"], email["body"]
            )
        except Exception as exc:  # noqa: BLE001 — surface any API failure per-email
            print(f"  {email['id']:<22} ERROR: {exc}")
            continue

        expected = email["expected_category"]
        hit = result["category_id"] == expected
        correct += hit
        mark = "PASS" if hit else "FAIL"
        got = result["category_id"] if hit else f"{result['category_id']} (expected {expected})"
        print(f"  {mark}  {email['id']:<22} -> {got}")
        print(f"        confidence={result['confidence']}  draft={result['should_draft']}")

        # Scored separately from the label, because it is the safety property.
        # Drafting a reply the playbook forbids is the failure that would cost
        # the boss's trust — getting the category right does not excuse it.
        if "expected_should_draft" in email:
            draft_checked += 1
            want_draft = email["expected_should_draft"]
            if result["should_draft"] == want_draft:
                draft_correct += 1
            else:
                verb = "drafted when it should not have" if result["should_draft"] else "declined to draft"
                print(f"        !! {verb}")
                if result["should_draft"] and not want_draft:
                    unsafe.append(email["id"])

        if result["blanks_to_fill"]:
            print(f"        blanks: {', '.join(result['blanks_to_fill'])}")

    total = len(fixtures)
    print(f"\n{correct}/{total} correctly classified")
    if draft_checked:
        print(f"{draft_correct}/{draft_checked} correct draft/no-draft decisions")
    if unsafe:
        print(f"\nUNSAFE: drafted a reply the playbook forbids -> {', '.join(unsafe)}")

    return 0 if (correct == total and not unsafe) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify email against the playbook")
    parser.add_argument("--test", action="store_true", help="Score against test fixtures")
    parser.add_argument("--file", help="JSON file with {from, subject, body}")
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY missing from .env", file=sys.stderr)
        return 1

    import anthropic

    client = anthropic.Anthropic()

    try:
        playbook = load_playbook()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.test:
        return run_tests(client, playbook)

    if args.file:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
        result = classify(
            client, playbook, data["from"], data["subject"], data["body"]
        )
        print(json.dumps(result, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

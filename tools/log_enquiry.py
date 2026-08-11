"""Append one enquiry to a CSV log. The record-keeping layer of the autoresponder.

Why a CSV: the business owner can open it in Excel or import it to Google
Sheets with no account, no login, and no training. Swap for the Sheets API
later if a client wants live sync.

Usage:
    python tools/log_enquiry.py --name "Ada" --email "ada@example.com" \
        --message "How much for 100 guests?" --out output/enquiries.csv

The `replied` column is written blank on purpose. It's what the weekly summary
counts to tell the owner "2 enquiries still unanswered" — the visible number
that justifies the monthly retainer.
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

FIELDNAMES = [
    "received_at",
    "name",
    "email",
    "phone",
    "message",
    "source",
    "replied",
]


def log_enquiry(
    path: Path,
    name: str,
    email: str,
    message: str,
    phone: str = "",
    source: str = "website",
) -> None:
    """Append one enquiry row, creating the file with a header if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new_file = not path.exists()

    # newline="" is required on Windows: without it csv writes \r\r\n and
    # every other row in the file comes out blank.
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        if is_new_file:
            writer.writeheader()
        writer.writerow(
            {
                "received_at": datetime.now().isoformat(timespec="seconds"),
                "name": name,
                "email": email,
                "phone": phone,
                "message": message,
                "source": source,
                "replied": "",
            }
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Append an enquiry to the CSV log")
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--phone", default="")
    parser.add_argument("--source", default="website")
    parser.add_argument("--out", default="output/enquiries.csv")
    args = parser.parse_args()

    try:
        log_enquiry(
            path=Path(args.out),
            name=args.name,
            email=args.email,
            message=args.message,
            phone=args.phone,
            source=args.source,
        )
    except OSError as exc:
        print(f"ERROR: could not write {args.out}: {exc}", file=sys.stderr)
        return 1

    print(f"Logged enquiry from {args.name} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

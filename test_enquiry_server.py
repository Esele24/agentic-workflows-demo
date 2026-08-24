"""Checks for the parts of the enquiry server that only matter in public.

Run:  python test_enquiry_server.py

⚠️ NO EMAIL IS SENT. `send_email` is replaced with a recorder, so this exercises
the routing, the honeypot, the validation and the rate limiter without touching
Gmail and without spending any of the account's daily send allowance. A test
suite that really sent mail would be a test suite nobody dares run twice.
"""

import os
import sys
from pathlib import Path

# Set before importing the server, because the module reads its limits at import
# time. Small numbers so the limiter can be driven to its ceiling in a few calls.
os.environ["RATE_LIMIT_PER_IP_HOUR"] = "3"
os.environ["RATE_LIMIT_GLOBAL_HOUR"] = "5"
os.environ["EPHEMERAL_STORAGE"] = "true"
os.environ.setdefault("BUSINESS_NAME", "Test Business")
os.environ.setdefault("OWNER_EMAIL", "owner@example.com")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import enquiry_server  # noqa: E402

sent: list[dict] = []


def fake_send_email(to, subject, text, html=None, reply_to=None):
    sent.append({"to": to, "subject": subject, "reply_to": reply_to})


enquiry_server.send_email = fake_send_email

# Writes go to a scratch file, never the real log.
enquiry_server.ENQUIRY_LOG = Path(__file__).resolve().parent / "output" / "test_enquiries.csv"

app = enquiry_server.app
app.config["TESTING"] = True

passed = failed = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  {detail}")


def reset_limits() -> None:
    enquiry_server._ip_hits.clear()
    enquiry_server._global_hits.clear()
    sent.clear()


def post(client, body, ip="203.0.113.10"):
    # X-Forwarded-For, because that is what the code reads in production and
    # testing remote_addr would exercise a path Render never takes.
    return client.post("/enquiry", json=body, headers={"X-Forwarded-For": ip})


GOOD = {"name": "Ada", "email": "ada@example.com", "message": "How much for 100 guests?"}

with app.test_client() as client:
    print("\nhealth")
    r = client.get("/health")
    body = r.get_json()
    check("returns 200", r.status_code == 200)
    check("admits the log is ephemeral", body["log_is_ephemeral"] is True)
    check("names the durable record", body["durable_record"] == "owner alert email")
    check("reports the rate limits", body["rate_limit_per_ip_hour"] == 3)

    print("\nvalidation")
    reset_limits()
    r = post(client, {"name": "Ada", "email": "ada@example.com"})
    check("missing message is rejected", r.status_code == 400)
    check("nothing was emailed", not sent, f"sent={sent}")

    reset_limits()
    r = post(client, {**GOOD, "email": "not-an-email"})
    check("bad email is rejected", r.status_code == 400)
    check("nothing was emailed", not sent)

    print("\nhoneypot")
    reset_limits()
    r = post(client, {**GOOD, "website": "http://spam.example"})
    check("bot gets 200 so it does not retry", r.status_code == 200)
    check("no mail sent to the bot", not sent, f"sent={sent}")
    check("honeypot did not spend the allowance", len(enquiry_server._global_hits) == 0)

    print("\nhappy path")
    reset_limits()
    r = post(client, GOOD)
    check("returns 200", r.status_code == 200, r.get_data(as_text=True))
    check("two emails sent", len(sent) == 2, f"sent={len(sent)}")
    check("customer gets the acknowledgement", sent[0]["to"] == "ada@example.com")
    check("customer reply-to is the owner", sent[0]["reply_to"] == "owner@example.com")
    check("owner gets the alert", sent[1]["to"] == "owner@example.com")
    check("owner reply-to is the customer", sent[1]["reply_to"] == "ada@example.com")

    print("\nper-IP rate limit (3/hour)")
    reset_limits()
    codes = [post(client, GOOD).status_code for _ in range(4)]
    check("first three accepted", codes[:3] == [200, 200, 200], f"codes={codes}")
    check("fourth refused with 429", codes[3] == 429, f"codes={codes}")
    check("only three sends happened", len(sent) == 6, f"emails={len(sent)}")

    print("\na different IP has its own allowance")
    r = post(client, GOOD, ip="198.51.100.7")
    check("other IP still accepted", r.status_code == 200)

    print("\nglobal rate limit (5/hour)")
    reset_limits()
    codes = []
    for i in range(7):
        codes.append(post(client, GOOD, ip=f"198.51.100.{i}").status_code)
    check("stops at the global ceiling", codes.count(200) == 5, f"codes={codes}")
    check("the rest are 429", codes.count(429) == 2, f"codes={codes}")

    print("\nCORS preflight")
    r = client.open("/enquiry", method="OPTIONS", headers={"Origin": "https://client.example"})
    check("preflight answered", r.status_code == 204, f"status={r.status_code}")
    check(
        "allow-origin header present",
        r.headers.get("Access-Control-Allow-Origin") == "https://client.example",
        f"headers={dict(r.headers)}",
    )
    check("POST is advertised", "POST" in r.headers.get("Access-Control-Allow-Methods", ""))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

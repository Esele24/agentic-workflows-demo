# Workflow: Enquiry Autoresponder (sellable client offer)

## Objective
When a customer submits an enquiry form on a client's website, respond within
seconds, alert the business owner, and make sure the lead can never be lost.
This is the automation layer that justifies the ₦25–30k/month retainer described
in `SECOND BRAIN/leads-bad-websites.md` — the client's own notes already price
this offer; this workflow is the thing being sold.

## The pain it solves
A PH caterer, clinic, or lounge gets "how much for 100 guests?" through a
contact form. Nobody checks that inbox for two days. The lead is gone. Speed of
first response is the single biggest lever on whether an enquiry converts, and
these businesses are losing enquiries they never even know arrived.

## Note: this is a service, not an agent-run tool
Unlike the other workflows here, nothing in this one is triggered by an agent.
`enquiry_server.py` runs unattended and is triggered by a *customer*. The files
in `tools/` are still ordinary WAT tools — importable and CLI-testable on their own.

## Components
1. `tools/send_email.py` — SMTP sending layer. Test standalone:
   ```
   python tools/send_email.py --to you@example.com --subject "Test" --text "Hello"
   ```
2. `tools/log_enquiry.py` — appends one row to the CSV log. Test standalone:
   ```
   python tools/log_enquiry.py --name "Ada" --email "a@b.com" --message "Hi"
   ```
3. `enquiry_server.py` — the Flask service that ties them together.
   ```
   python enquiry_server.py          # http://localhost:5000
   ```
   `GET /health` confirms config is loaded. `POST /enquiry` accepts JSON or
   form-encoded `name`, `email`, `message`, optional `phone`.

## Required .env
```
SMTP_USER        Gmail address that sends the mail
SMTP_PASSWORD    Google App Password, 16 chars, NO SPACES
FROM_NAME        display name recipients see
BUSINESS_NAME    the client's business name
OWNER_EMAIL      where owner alerts go
REPLY_WINDOW     optional, default "within 24 hours"
ENQUIRY_LOG      optional, default output/enquiries.csv
```

## Expected outputs
- Customer receives a branded acknowledgement within seconds, `Reply-To` set to
  the owner.
- Owner receives an alert with `Reply-To` set to the **customer** — hitting
  reply goes straight to the lead, no copying addresses.
- `output/enquiries.csv` gains a row. The blank `replied` column is what the
  weekly summary will count.

## Design decisions worth keeping
- **Log before sending, and never let a mail failure lose the lead.** Email is
  the impressive part; the CSV is the part the business cannot afford to lose.
  Only if *both* the log and all mail fail does the customer see an error
  telling them to phone instead — better than a silent false success.
- **Honeypot field** (`website`) — hidden with CSS, invisible to humans, filled
  by bots. Filled means silently accept with 200 so the bot doesn't retry.
- **Plain text is always sent alongside HTML.** HTML-only mail scores worse with
  spam filters, and an auto-reply in spam is a broken product.
- **App Password space check** happens before any connection, because pasting
  Google's display spaces is the most common setup failure by a wide margin.

## Verified working 2026-07-20
Full chain tested end to end: `POST /enquiry` → `ok: true`, no warnings, both
emails accepted by Gmail, CSV row written with correct quoting.

## Not built yet (next session)
- [ ] **Weekly summary email** — "7 enquiries this week, 2 still unanswered".
      This is the retainer justifier; the client sees value every week without
      having to think about it. Reads `replied` from the CSV.
- [ ] **Deployment.** Currently localhost only, which means it dies when the
      laptop closes. Needs a free host (Render / Railway) before any client
      demo. A demo that only runs on Esele's laptop cannot be sold.
- [ ] **Rate limiting** on `/enquiry` — a public endpoint will get hammered.
- [ ] **Per-client config.** Today one instance serves one client via `.env`.
      Fine for the first two or three; revisit if it sells.
- [ ] **Sending from the client's own domain** (Resend) so mail comes from
      `hello@theirclinic.com`, not Esele's Gmail. Required before charging.
- [ ] A drop-in HTML form snippet to paste into any site he builds.

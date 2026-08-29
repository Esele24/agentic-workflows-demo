# Deploying the enquiry autoresponder

Repo: https://github.com/Esele24/agentic-workflows-demo (**public**)
Blueprint: `render.yaml` · Server: `enquiry_server.py` · Checks: `test_enquiry_server.py`

The code is ready and pushed. What is left is six clicks in the Render dashboard,
which cannot be done from a terminal: Render has no CLI for creating a service,
and the step that matters asks for a Gmail App Password that should be typed by
Esele and by nobody else.

**There is now a second route** that needs one click instead of six and retypes
nothing. See *The API route* below. The six clicks remain the guaranteed path.

---

## The API route (one click, added 2026-08-29)

Render has no CLI, but it does have a REST API, and `deploy_render.py` drives it.
It reads the five prompted values straight out of `.env`, so the App Password is
never retyped into a browser field.

```powershell
# One click: Render, Account Settings, API Keys, Create API Key.
$env:RENDER_API_KEY = "rnd_..."

cd "CLAUDE\AGENTIC WORKFLOWS DEMO"
python deploy_render.py            # dry run. Sends nothing. Masks secrets.
python deploy_render.py --create    # provision it
```

**Why this matters beyond today.** This service is meant to be sold, and every
client needs their own deployment with their own `BUSINESS_NAME`, `OWNER_EMAIL`
and sending account. Six clicks and a hand typed password *per client* is where
mistakes live. Point the script at a per client env file instead:

```powershell
python deploy_render.py --env-file clients/best-smilez.env --create
```

🚨 **The `--create` path has never been run against the live Render API.** There
was no API key on the machine when it was written, so the request shape is built
from Render's documented v1 schema and is **unconfirmed**. Every failure prints
Render's own response body verbatim so a wrong field is legible in one read. If
it fails, use the six clicks below and tell me what the body said.

✅ **What IS verified:** `python test_deploy_render.py`, **25 checks, all
passing** — the App Password rules (spaces refused, wrong length refused), every
required value, payload construction, and that `SMTP_PASSWORD` cannot appear in
terminal output. Confirmed separately that the real `.env` passes validation and
that a bad key is reported as a key problem rather than as a code problem.

⚠️ **The script also needs the Render account to have GitHub access to
`agentic-workflows-demo` already.** If that authorization has never been granted,
the API cannot grant it and the create fails. That is a browser flow, once.

---

## Before you start

You need a **Gmail App Password**, not the account password.

1. The Google account in `SMTP_USER` must have **2 Step Verification ON**. App
   Passwords cannot be created until it is.
2. Google shows the password in four groups of four for readability.
   **Store it as 16 characters with the spaces removed.** Pasting the spaces is
   the single most common setup mistake and `send_email.py` refuses it with a
   specific error rather than failing vaguely at login.

The value is already in your local `.env`. That file is gitignored and confirmed
absent from the repo's history, so it is on your machine only.

---

## The six steps

1. **render.com** → **New** → **Blueprint**.
2. Connect the **`agentic-workflows-demo`** repo. Render finds `render.yaml` and
   proposes a service called **enquiry-autoresponder**.
3. It prompts for the five values marked `sync: false`. Fill them from `.env`:

   | Variable | What it is |
   |---|---|
   | `SMTP_USER` | the full Gmail address that sends |
   | `SMTP_PASSWORD` | the App Password, **16 chars, no spaces** |
   | `OWNER_EMAIL` | where enquiry alerts land |
   | `FROM_NAME` | display name the customer sees |
   | `BUSINESS_NAME` | used in the auto reply wording |

   Everything else is set by the blueprint and needs no input.
4. **Apply**. First build takes a few minutes.
5. Copy the service URL. ⚠️ **It is not derivable.** Render appends a random
   suffix when the plain name is taken, exactly as it did for
   `ai-lab-backend-hhrb`. Two probe attempts were wasted guessing that one. Read
   the real hostname off the dashboard.
6. Run the two checks below.

---

## Verify it, and do not skip the second one

```powershell
# 1. Config visible? Replace the host with the real one from step 5.
curl.exe https://enquiry-autoresponder-XXXX.onrender.com/health
```

Expect `smtp_user_set: true`, `smtp_password_set: true`, `owner_email_set: true`,
and `log_is_ephemeral: true`.

⚠️ **`/health` reports what is CONFIGURED, not what works.** `smtp_user_set: true`
means a value exists, not that Gmail will accept it. A 200 here proves nothing
about email.

```powershell
# 2. The only check that proves the chain. Use an address you can actually open.
curl.exe -X POST https://enquiry-autoresponder-XXXX.onrender.com/enquiry `
  -H "Content-Type: application/json" `
  -d '{\"name\":\"Ada\",\"email\":\"YOUR-OWN@gmail.com\",\"message\":\"Testing the deploy\"}'
```

**Two emails must arrive:** the branded acknowledgement to the address you gave,
and the alert to `OWNER_EMAIL`. Hit reply on each and check where it goes: the
acknowledgement replies to the owner, the alert replies to the customer. That
routing is the product.

---

## Two free tier facts that will look like bugs

**It sleeps after about 15 minutes idle.** The first request after that waits 30
to 60 seconds. **Warm the URL before showing it to anyone**, or the first click
of a demo is a spinner. Same as `ai-lab-backend`.

**The filesystem is ephemeral.** `output/enquiries.csv` is wiped on every deploy,
every restart, and every wake from sleep. On this deployment the durable record
of an enquiry is the **owner alert email**, and `/health` says so rather than
implying otherwise. `OWNER_EMAIL` is therefore not optional in production: unset
it and an enquiry can vanish with no trace at all.

---

## Wiring a real form to it

The endpoint accepts JSON or form encoded POST at `/enquiry` with `name`, `email`,
`message`, and optional `phone`.

Include the honeypot. It is a field hidden with CSS that humans never see and
bots fill in. Leave it out and the spam protection is gone.

```html
<input type="text" name="website" tabindex="-1" autocomplete="off"
       style="position:absolute;left:-9999px" aria-hidden="true">
```

⚠️ **Set `ALLOWED_ORIGINS` to the client's real domain** the moment a website
points here, for example `https://bestsmilez.com`. The `*` default is fine while
only curl is calling it. Leaving it open lets any site on the internet post
through the form and spend the rate limit that protects the Gmail account.

---

## Rate limits, and why they exist

Defaults: **5 per IP per hour**, **50 total per hour**, both tunable in Render.

This endpoint sends mail to an address a stranger types, signed by your Gmail
account. Uncapped that is an open relay: someone loops it, Google sees the
volume, and the account that sends every client's mail gets suspended. The
per IP cap stops one person hammering it; the global cap stops a spread out
flood and keeps the service well under Gmail's roughly 500 a day.

⚠️ **The limiter holds timestamps in process memory, so the blueprint pins
gunicorn to `--workers 1`.** Raise the worker count and each worker gets its own
private allowance, silently multiplying the real ceiling.

---

## The next change, and it is the one that unblocks the mobile app

Replace `log_enquiry` with a **Supabase insert**. It fixes three things at once:
the CSV stops evaporating, the durability caveat above disappears, and
`expo-app` finally has real data to read instead of its sample fixtures. The
schema and row level security policies already exist in `expo-app/supabase/schema.sql`.

`log_enquiry` is the seam. Keep the call signature, replace the body.

---

## Running the checks locally

```powershell
cd "CLAUDE\AGENTIC WORKFLOWS DEMO"
python test_enquiry_server.py     # 26 checks, sends no email
python enquiry_server.py          # local server on 127.0.0.1:5000
```

`send_email` is stubbed in the test file, so nothing is delivered and none of the
account's daily allowance is spent. Gunicorn does not run on Windows, which is
why the local path keeps the Flask server and only Render uses gunicorn.

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

## 🔴 THE BLOCKER: Render's free tier blocks SMTP. Email cannot send there.

**Measured 2026-08-29 on the live deployment**, not read in a doc first:
`GET /health` returned 200 in **0.9 s** with every value set, and
`POST /enquiry` **never returned** and was killed by gunicorn's 60 s timeout.

**Cause:** Render blocked outbound traffic to SMTP ports **25, 465 and 587** on
**free** web services in September 2025. `tools/send_email.py` connects to
`smtp.gmail.com:587`, so the connection hangs until something kills it.
Render's own changelog:
https://render.com/changelog/free-web-services-will-no-longer-allow-outbound-traffic-to-smtp-ports

⚠️ **Nothing in the code is wrong, and this is invisible to every check that was
run before deploying.** The 26 local checks stub `send_email`, so they pass. The
`/health` endpoint reports what is CONFIGURED, and every value really is set, so
it reports a healthy service. **A green health check on a service whose entire
purpose is sending email is exactly the "metric a broken output can satisfy"
lesson again** — the only thing that caught this was sending a real enquiry and
watching nothing arrive.

### The three ways out

| Option | Cost | Code change |
|---|---|---|
| **HTTP email API** (Resend, Brevo, SendGrid, Mailgun) | free tiers exist | replace the body of `send_email` |
| **Paid Render instance** | ~$7/month | none |
| **Another host** (Railway, Fly) | ~$5/month or free | none, but redo the deploy |

🔑 **The HTTP API route is the better answer even if the money were free**, and
for three reasons that have nothing to do with Render:
1. These APIs send over **HTTPS on 443**, which no host blocks.
2. **It removes the open relay risk at the root.** The worst case in this
   codebase was always "a stranger loops the endpoint and Google suspends the
   account that sends everything." A provider key is revocable and rate limited
   by the provider; his personal Gmail is neither.
3. **Sending client mail from `okogboesele@gmail.com` does not scale and does not
   look professional.** Gmail caps around 500 a day across every client.

`send_email` is the seam: keep the signature, replace the body. Everything above
it — the reply-to routing, the rate limiter, the honeypot, the 26 checks — is
unaffected.

### ✅ Chosen 2026-08-29: the HTTP API. Brevo. Already built.

`tools/send_email.py` now has **two transports behind one unchanged
`send_email()` signature**, so nothing that calls it had to change:

| Transport | How | Where it works |
|---|---|---|
| `smtp` | `smtp.gmail.com:587` | locally, and on paid hosts |
| `brevo` | `POST https://api.brevo.com/v3/smtp/email` on 443 | everywhere, including Render free |

**Which one runs:** `EMAIL_TRANSPORT` if set, otherwise Brevo whenever
`BREVO_API_KEY` exists. ⚠️ That default leans to Brevo deliberately. On a host
that blocks SMTP, defaulting the other way means **hanging**, and a hang is far
harder to diagnose than a missing key.

**Why Brevo and not Resend.** Resend's free tier only sends from
`onboarding@resend.dev` **to the address you signed up with** until you verify a
domain. For a tool whose whole job is emailing customers, that is unusable.
Brevo is 300 a day free and will verify a single sender address.

#### Setting it up

1. Sign up at brevo.com. No card.
2. **Senders, Domains & Dedicated IPs → Senders → Add a sender.** Use his Gmail
   for now. Brevo emails a confirmation code to that address.
3. **SMTP & API → API Keys → Generate.** ⚠️ Two different keys live on that
   page. You want the **v3 API key, which starts `xkeysib-`**. The SMTP key does
   not work against the HTTP API, and `deploy_render.py` refuses it by prefix.
4. Add to `.env`:
   ```
   BREVO_API_KEY=xkeysib-...
   BREVO_SENDER_EMAIL=okogboesele@gmail.com
   ```
5. Test locally before touching Render:
   ```powershell
   python tools/send_email.py --to okogboesele@gmail.com --subject "Brevo test" --text "Hello"
   ```
   It prints the transport it used. If it says `via smtp`, the key is not being
   read.

#### 🚨 The deliverability caveat, and it is not a code problem

**Brevo cannot authenticate a free webmail domain.** Its own documentation:
domains such as `@gmail.com` and `@yahoo.com` *"cannot be authenticated"*. Since
February 2024 Gmail and Yahoo require authentication from bulk senders, so mail
sent from a gmail.com address is **more likely to land in spam**. It sends. It
just does not arrive as reliably.

🔑 **The fix is a domain, and it is already on his list for another reason.**
[business.md](../SECOND%20BRAIN/business.md) records a real domain and mailbox as
the prerequisite gating the UK/US cold email channel. **One `.com.ng` at ₦2,000
to ₦6,000 a year unblocks both.** Authenticate it in Brevo, point
`BREVO_SENDER_EMAIL` at it, and **no code changes.**

⚠️ **Unverified and worth checking on the first real send:** whether Brevo's free
plan stamps its own branding on transactional emails. If it does, a client's
customer sees a Brevo logo on a branded acknowledgement, which is not sellable.
Look at the first email that arrives rather than assuming either way.

#### Updating the service that already exists

The service `enquiry-autoresponder` was created before this change, so it still
carries the SMTP variables. `deploy_render.py` creates services and will not
update one whose name is taken. In the Render dashboard, on that service,
**Environment**: add `BREVO_API_KEY`, `BREVO_SENDER_EMAIL` and
`EMAIL_TRANSPORT=brevo`, and delete `SMTP_PASSWORD`. Saving redeploys it.

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

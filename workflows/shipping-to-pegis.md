# Shipping the Inbox Assistant to the Boss

What to do and what to say, from "yes I'm interested" through to it running.
Written 2026-07-21. Nothing here has been executed yet — this is the plan.

Read with [enquiry_autoresponder.md](enquiry_autoresponder.md) (the other email
build) and [../config/email_playbook.md](../config/email_playbook.md) (the
categories, still unconfirmed).

---

## The one-line version

It reads his inbox, writes replies into his own Gmail drafts folder, and he sends
them. It cannot send mail itself. He keeps working exactly the way he already
does — the replies are just already written when he gets there.

---

## Stage 0 — The demo. Say this before you build anything else.

**Show him the drafts on the fake emails** ([expected_drafts.md](../tests/fixtures/expected_drafts.md)).
Nothing touches his real mail. No permissions, no IT, no risk.

What to say — plain, not salesy:

> "I made eight example emails like the ones I think you get, and had it write
> the replies. Have a look and tell me two things: which of these are actually
> the ones you're tired of, and what have I got wrong?"

**Why this framing works:** you are asking him to correct you, not to buy
something. He is your boss — being asked for his expertise is comfortable for
him in a way that being pitched is not.

**Do not say:**
- ❌ "AI will handle your emails" — he hears *losing control*
- ❌ "It will reply for you" — it will not, and if he believes that once, you
  have lost him permanently
- ❌ Any promise about time saved. You have no data yet.

**Do say:**
- ✅ "It writes the draft, you read it and send it"
- ✅ "It cannot send anything — I built it so it physically can't"
- ✅ "Where it doesn't know something it leaves a blank for you to fill"
- ✅ "It's new, so the first week is about finding out where it's wrong"

---

## Stage 1 — Two questions to get answered

Before any setup. Both fit in one conversation.

1. **What does his work mail actually run on?** Gmail / Google Workspace,
   Microsoft 365 / Outlook, or webmail on the company domain?
   → If it is **not** Google, `tools/gmail_inbox.py` is the wrong layer and
   needs rebuilding against Microsoft Graph. The playbook, classifier and
   fixtures all survive unchanged. Find this out **before** promising a date.

2. **Which categories are really his?** Hand him the eight, get his edits. If
   most of his volume turns out to be `internal` or `other`, **tell him this
   won't help much** and say what would. See the honest note at the bottom of
   the playbook.

---

## Stage 2 — The pilot. One week, his real mail.

Only after stage 1. Roughly $4 in API cost for the week.

### What you set up (before involving him)

1. Google Cloud project → enable Gmail API → OAuth client, type **Desktop app**
2. OAuth consent screen → **add his email as a test user**
3. Confirm scopes are `gmail.readonly` + `gmail.compose` only. **Never add a
   send scope.** This is the promise the whole pitch rests on.
4. `ANTHROPIC_API_KEY` in `.env`, billing on a card that works

### What he does — once, about two minutes

He runs the authorization on **his own machine**, signed into **his own**
account.

> **You never ask for his password. Not once, not "just to set it up."**
> If you ever find yourself typing his password, stop — you have built the
> wrong thing and you are now a security problem.

Warn him about the scary screen before he sees it:

> "Google will show a warning that says 'this app isn't verified'. That's
> normal — it means I built it myself and haven't paid Google to review it.
> Click Advanced, then Continue. If you'd rather not, that's completely fine
> and we stop here."

### The 7-day thing

In testing mode the access expires **every 7 days** and he re-authorizes.
Annoying for production, fine for a one-week pilot — and it means the access
dies by itself if you both drop it. Tell him that; it reassures.

### Running it

You run it manually each morning. Drafts appear in his Gmail. He reviews.

**End of the week, ask exactly this:**
> "How many did you send without changing anything? How many did you have to
> rewrite? And was there anything it drafted that you'd have been embarrassed
> to send?"

That third question is the one that matters. One embarrassing draft costs more
than ten useful ones earn.

---

## Stage 3 — Production. Where it stops being a side project.

Do not promise this until stage 2 has actually run.

- **Deployed** on Render or Railway, scheduled every 30 minutes
- **His refresh token stored somewhere real** — encrypted, not in a file next to
  the code. This is his mailbox access. Treat it that way.
- **Billing on the company account, not yours.** See the money note below.
- **Pegis IT and their Google Workspace admin.** Non-negotiable and unavoidable:
  `gmail.readonly` is a restricted scope. Google normally requires a paid
  third-party security assessment — but an app used only inside **one** Workspace
  organisation can be trusted internally by their admin, skipping verification.
  That is your route and it does not exist without IT.

**Go to IT early and openly.** An intern discovered wiring an unapproved tool
into company mail is a serious problem, regardless of good intentions. Being the
person who brought it to them first is a completely different conversation.

---

## Do you need to be there for it to work?

Three separate answers, and conflating them is how people over-promise.

| Stage | Runs without you? |
|---|---|
| Pilot (stage 2) | **No.** You run it by hand each morning. Nothing happens on days you don't. |
| Production (stage 3) | **Yes.** Deployed with a scheduler, runs unattended, survives your laptop being off. |
| Any stage | **He is always needed.** Nothing reaches a customer unless he presses send. |

That last row is permanent and by design. "Fully automatic" is never the goal —
a tool that mails his customers unsupervised is the version that ends the
relationship. When he asks "so it just runs by itself?", the answer is:

> "The writing runs by itself. The sending is always you."

**The honest caveat:** during the pilot, if you travel or get busy, it stops.
Say that upfront rather than letting him discover it. It is also the reason not
to let a pilot drift on for a month — either it earns stage 3 or it ends.

---

## The money conversation

Do not skip this because he is your boss and it feels awkward.

- The API cost is roughly **$0.03 per email** — about **$18/month** at 20 emails
  a day. Recurring, forever, from whoever's card is on the account.
- For the one-week pilot, paying the ~$4 yourself is fine. It buys you the
  answer.
- **Do not run stage 3 on your own card.** A student quietly subsidising an oil
  servicing company's operating costs is a bad deal that gets worse every month,
  and it is much harder to renegotiate later than to set correctly now.

Wording that works, offered once and without apology:

> "The running cost is about $20 a month in API fees — that would go on the
> company account. My time for building it we can talk about separately."

---

## Two lines you must not cross

1. **Never point this at his inbox before he has personally authorized it.**
   Develop and test against **your own** Gmail. Always.
2. **Never route his mail through your personal Claude subscription.** Anthropic
   permits subscription use for you working; other people's requests flowing
   through your seat is a different thing and risks the account. Production runs
   on an API key, on the company's billing.

---

## When to walk away

Say so plainly if any of these turn out to be true. Losing the build is cheaper
than losing your standing with him.

- Most of his volume is `internal` / `other` → email drafting won't help him
- IT says no → that is a full stop, not an obstacle to route around
- He wants it to send automatically → the answer is no, and explain why once
- His mail isn't Google and there's no time to rebuild → say so before promising

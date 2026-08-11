# Email Playbook — Pegis Global Services (oil servicing)

> ⚠️ **EVERY CATEGORY BELOW IS AN ASSUMPTION.** Written 2026-07-20 by guessing what
> a manager at a wellhead maintenance / intervention / fabrication company gets
> repeatedly. **None of it is confirmed by the boss.**
>
> **This file is also the question.** Send him this list and ask: *"which of these
> are the ones you're tired of replying to — and what's missing?"* His answer
> replaces this file. Nothing in the code needs to change when it does.

## How this file is used

The assistant reads the inbox, matches each message to a category below, and
writes a Gmail **draft** using that category's guidance. Categories marked
`automate: no` are flagged for attention and never drafted.

Editing rules: keep the `id`, `automate`, and `signals` fields. Everything else
is free text the model reads as instructions. Add or delete whole categories
freely.

---

## Global tone

- Professional, warm, brief. Nigerian business English — not American breeziness.
- Never invent facts: no prices, dates, job statuses, or commitments.
- Where a real detail is required, leave a visible blank like `[CONFIRM: date]`
  so the boss must fill it before sending. **A visible gap is safe; a plausible
  invention is not.**
- Sign off as the boss, not as an assistant. Never mention that AI drafted it.

## When an email is two things at once

Real mail often carries two asks — an RFQ that ends with "and when can we visit?".
Classify by **the sender's main ask**: the thing the email exists to get. Usually
it is the first substantive paragraph, not the afterthought at the end.

Then **answer both in the draft.** The category picks the tone and the guardrails;
it does not license ignoring half the message. A reply that silently drops the
second question makes more work than it saves, because the boss now has to notice
the omission before sending.

If the second ask belongs to a category marked `automate: no`, address the
draftable part and leave `[CONFIRM: ...]` for the rest. Never draft past a
`no`.

---

## Categories

### 1. Quote / RFQ request
- **id:** `rfq`
- **automate:** draft-only
- **signals:** "request for quotation", "RFQ", "kindly quote", "pricing for", "scope of work"
- **Draft approach:** acknowledge receipt, confirm the scope as understood, state
  when a full quotation will follow (`[CONFIRM: turnaround]`). **Never quote a
  figure.** Pricing is a commercial decision, not an automation one.

### 2. Job status enquiry
- **id:** `status`
- **automate:** draft-only
- **signals:** "any update", "status of", "how far with", "progress on"
- **Draft approach:** acknowledge, then leave `[CONFIRM: current status]` for the
  boss. The tool cannot know operational reality and must not imply it does.
  Genuinely useful anyway — most of the effort here is the courtesy wrapper.

### 3. Prequalification / compliance documents
- **id:** `compliance`
- **automate:** draft-only
- **signals:** "prequalification", "HSE", "certificate", "tax clearance", "CAC",
  "DPR", "NCDMB", "insurance certificate", "vendor registration"
- **Draft approach:** likely the highest-volume repetitive category in Nigerian
  oil servicing — the same document bundle requested endlessly. Acknowledge and
  list what's being attached as `[ATTACH: ...]`. **Never attach files
  automatically.** If this is the big one, a shared document pack solves more of
  it than email automation does — say so.

### 4. Invoice / payment follow-up
- **id:** `payment`
- **automate:** draft-only
- **signals:** "invoice", "payment", "outstanding", "remittance", "PO number"
- **Draft approach:** acknowledge, confirm the invoice reference, leave
  `[CONFIRM: payment status]`. **Never state that anything has been paid.**
- **Check the direction first — the two cases need opposite replies:**
  - **A supplier chasing us** (we owe them). Acknowledge without admitting or
    disputing the debt, confirm the invoice reference, leave
    `[CONFIRM: payment status]`. Never apologise for a delay you cannot verify —
    an apology is an admission.
  - **A customer we are chasing** (they owe us). Polite, firm, restate the
    invoice and terms, leave `[CONFIRM: amount outstanding]`. Never threaten
    escalation, suspension, or interest — that is the boss's call, not a draft's.

### 5. Meeting / visit scheduling
- **id:** `scheduling`
- **automate:** draft-only
- **signals:** "available", "schedule", "meeting", "visit", "call on"
- **Draft approach:** acknowledge and propose `[CONFIRM: two time options]`.
  Cheap to draft, saves a genuinely annoying reply.

### 6. Unsolicited job applications
- **id:** `jobseeker`
- **automate:** draft-only
- **signals:** "attached my CV", "seeking employment", "job opportunity", "IT placement", "SIWES"
- **Draft approach:** brief, kind decline-or-hold: CV received, kept on file, no
  current opening implied. High volume, near-zero judgment — probably the safest
  category to automate first, and a good demo.

### 7. Internal staff requests
- **id:** `internal`
- **automate:** **no**
- **signals:** **sender's domain is the company's own** — this is the strongest
  and fastest signal, check it before reading the body. Then: leave requests,
  approvals, purchase requisitions, handover notes, staff matters.
- **Why not:** approvals are judgment and carry authority. Flag, never draft.
- A colleague writing about a customer's job is still `internal`. The test is who
  sent it, not what it is about. When the domain says internal and the content
  says otherwise, **internal wins** — the cost of wrongly drafting a reply to
  staff is higher than the cost of flagging one customer email for a human.

### 8. Anything else
- **id:** `other`
- **automate:** **no**
- **Why not:** if it doesn't match a known category, a draft is a guess. Flag it
  for the boss and stay quiet.

---

## Honest note to carry into the conversation

If most of his volume turns out to be category 7 or 8, **tell him email
automation won't help much** and say what would. Selling him a tool that drafts
replies he can't use costs the relationship, and the relationship is worth more
than this build.

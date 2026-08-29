# LinkedIn caption — enquiry autoresponder

Text post, no media needed. Put the repo link in the **first comment**, not the body.
LinkedIn suppresses reach on posts carrying an external link in the caption.

---

## Caption

> My contact form worked perfectly on my laptop. Putting it online exactly as it was
> would have cost me the email account I send everything from.
>
> The thing itself is small. Someone fills in a form on a business website, they get an
> instant branded reply, and the owner gets an alert with the customer's details and a
> reply button that goes straight back to them. I had that working end to end weeks ago.
>
> Then I went to deploy it, and found that "works on localhost" and "safe on a public
> URL" are two different questions. Four things were hiding.
>
> The debugger was on. Flask's debug mode opens an interactive Python console on any
> unhandled crash. On a public URL that is a stranger running code on the machine holding
> my email password.
>
> It was an open mail relay. The endpoint sends a branded email to any address a stranger
> types, signed by my own Gmail account. Uncapped, somebody loops it, Google sees the
> volume, and the account is suspended. That does not break this demo. That breaks every
> piece of mail I send.
>
> There were no CORS headers. curl worked. The health check was green. And a real form on
> a real website would have done nothing at all when clicked, with the reason visible only
> in the browser console.
>
> And a comment in my own code was lying. It said the log file was "the part the business
> cannot afford to lose." True on a laptop. On free hosting the filesystem is wiped on
> every restart, so the honest answer is that the durable record is the alert email. The
> code says that now, and the health endpoint admits it out loud.
>
> All four are fixed, with 26 checks covering them, including one that a caught bot does
> not spend a real visitor's allowance.
>
> The lesson I keep paying for: a green check mark tells you the code ran. It does not
> tell you the code is right.
>
> If enquiries reach your business through a form or a DM, how long does somebody usually
> wait before anyone answers them?
>
> #BuildInPublic #Nigeria

---

## First comment

> The code, including the 26 checks and the deploy notes:
> https://github.com/Esele24/agentic-workflows-demo

---

## Notes

- **The first line is the whole hook.** It is all that shows before "…see more", so it
  opens on the loss, not on "I built something". Same shape as the post that did 95
  impressions, which opened on a concrete event rather than an announcement.
- ⚠️ **It deliberately does NOT say "every client's mail."** He has had one yes. Implying a
  book of clients is invented social proof, and it is the kind that is trivially caught.
- **The close asks about response time, not about websites.** No stranger is hiring a
  contact form. The businesses that will pay are the ones where messages sit unanswered,
  and the question makes them count the wait themselves rather than being told a number.
  There is no invented statistic anywhere in the post for the same reason.
- **Nothing here claims the service is live.** The post is about the review, and it stands
  on its own with only the repo link. ⚠️ **Once the Render deploy is done, do not rewrite
  the caption** — add a second line to the first comment with the live URL, and warm the
  URL first, because the free tier sleeps after about 15 minutes and a cold first click is
  a 30 to 60 second spinner.
- Publishing "I nearly shipped a security hole" is the point, not a risk: he caught all
  four before anything was public, and catching them is the part a client is buying.

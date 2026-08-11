# Workflow: Scrape DailyRemote Jobs to Excel

## Objective
Collect every job listing for a given DailyRemote search term and maintain a
master Excel workbook the user can filter, sort, and track over time.

## Required Inputs
- **search term** (required) — e.g. `social media`, `data entry`
- **max pages** (optional) — safety cap; default lets the scraper run to the last page

## Tools (run in this order)
1. `tools/scrape_dailyremote.py`
   ```
   python tools/scrape_dailyremote.py --search "<term>" --out "tmp/<slug>_raw.json"
   ```
   Scrapes all listing pages (~30 jobs/page) into JSON. Prints per-page progress.
2. `tools/update_job_workbook.py`
   ```
   python tools/update_job_workbook.py --in "tmp/<slug>_raw.json" --workbook "output/dailyremote_<slug>.xlsx"
   ```
   Merges into the master workbook. Dedupes by `job_id`; new jobs get
   `is_new = TRUE` and `first_seen`; vanished jobs stay with `active = FALSE`.

Use a filesystem-safe slug for filenames: lowercase, spaces → underscores
(e.g. `social media` → `social_media`).

## Expected Outputs
- `tmp/<slug>_raw.json` — raw scrape of the current run (disposable)
- `output/dailyremote_<slug>.xlsx` — master workbook, sheet "Jobs", one row per
  job ever seen, new/active rows sorted to the top, clickable URLs

## Fields Captured
job_id, title, company (rarely shown by the site), job_type, posted date
(relative + estimated absolute), location, experience, salary (raw + parsed
min/max/currency), category, role tags, AI snippet, url, search_term, plus
tracking columns (first_seen, last_seen, is_new, active).

## Edge Cases & Learned Constraints
- **Detail pages are paywalled.** Company names are hidden, descriptions are
  Lorem-Ipsum placeholders, and Apply buttons route to DailyRemote Premium.
  Do NOT scrape detail pages — everything real lives on the listing cards.
  (If the user ever gets a Premium account, the scraper can be extended with a
  session cookie to unlock them.)
- **Result counts fluctuate daily** as jobs expire; don't treat a mismatch with
  a previously quoted total as an error.
- **The site occasionally stalls.** One request during development took >30s.
  The tool uses a 45s timeout with 3 retries and exponential backoff.
- **Rate limiting is self-imposed** (1–1.5s between pages); robots.txt sets no
  crawl-delay and only disallows `/apply/`.
- **If the scraper exits with BLOCKED (403/503)**: the site started bot
  blocking. Fall back to the Firecrawl MCP server (`firecrawl_scrape` per page
  URL, format rawHtml), save the HTML, and reuse `parse_card()` from the tool.
- **If 0 jobs parse**: the site layout changed. Save one page to `tmp/`,
  inspect the card markup, and update the selectors in `parse_card()`.
- **Salary label quirk**: some cards show a bare "💵 Salary" tag with no
  figures — the tool treats that as no salary.
- **Salary format quirk**: ~12% of salaries omit the currency symbol entirely
  (e.g. "15000 - 25000 per month"). These parse to numbers with
  `salary_currency` left blank — the currency is unknown, often local to the
  job's country. Pay period (year/month/week/day/hour) is captured in
  `salary_period`; don't compare salary_min across rows without checking it.

## When to Re-run
Re-running is cheap and safe: only new jobs are appended (`is_new = TRUE`),
existing rows get `last_seen` refreshed, and expired jobs are marked
`active = FALSE` but never deleted.

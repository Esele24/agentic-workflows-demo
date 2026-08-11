"""Scrape DailyRemote search results into a JSON file of job records.

Usage:
    python tools/scrape_dailyremote.py --search "social media" --out tmp/social_media_raw.json
    python tools/scrape_dailyremote.py --search "data entry" --max-pages 2 --out tmp/data_entry_raw.json

Only listing-card data is scraped. Job detail pages are paywalled on
DailyRemote (hidden companies, placeholder descriptions) and are skipped
on purpose — see workflows/scrape_dailyremote_jobs.md.
"""

import argparse
import json
import random
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://dailyremote.com/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 45  # seconds; the site occasionally stalls past 30s
MAX_RETRIES = 3
DELAY_RANGE = (1.0, 1.5)  # polite delay between page fetches

RELATIVE_DATE_RE = re.compile(
    r"(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago", re.IGNORECASE
)
SALARY_RANGE_RE = re.compile(
    r"([$€£])?\s*([\d,.]+)\s*(K)?\s*(?:-\s*[$€£]?\s*([\d,.]+)\s*(K)?)?",
    re.IGNORECASE,
)
SALARY_PERIOD_RE = re.compile(r"per\s+(year|month|week|day|hour)", re.IGNORECASE)


def fetch_page(session: requests.Session, search: str, page: int) -> str:
    url = f"{BASE_URL}?search={quote(search)}&page={page}"
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (403, 503):
                raise BlockedError(
                    f"HTTP {resp.status_code} on page {page} — possible bot "
                    "blocking. Fall back to Firecrawl MCP (see workflow doc)."
                )
            last_error = f"HTTP {resp.status_code}"
        except BlockedError:
            raise
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(2**attempt)  # 2s, 4s, 8s backoff
    raise RuntimeError(f"Page {page} failed after {MAX_RETRIES} retries: {last_error}")


class BlockedError(RuntimeError):
    pass


def parse_relative_date(text: str, now: datetime) -> str:
    """Convert '13 hours ago' / 'Yesterday' / '13 Weeks Ago' to YYYY-MM-DD."""
    text = text.strip()
    lowered = text.lower()
    if lowered in ("today", "just now"):
        return now.date().isoformat()
    if lowered == "yesterday":
        return (now - timedelta(days=1)).date().isoformat()
    match = RELATIVE_DATE_RE.search(text)
    if not match:
        return ""
    amount = int(match.group(1))
    unit = match.group(2).lower()
    delta = {
        "minute": timedelta(minutes=amount),
        "hour": timedelta(hours=amount),
        "day": timedelta(days=amount),
        "week": timedelta(weeks=amount),
        "month": timedelta(days=30 * amount),
        "year": timedelta(days=365 * amount),
    }[unit]
    return (now - delta).date().isoformat()


def parse_salary(raw: str) -> dict:
    """Parse '$110K - $125K per year' or '15000 - 25000 per month' into parts.

    Some listings omit the currency symbol entirely — those parse to numbers
    with salary_currency left blank (currency unknown, often local to the
    job's country).
    """
    out = {
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "",
        "salary_period": "",
    }
    period = SALARY_PERIOD_RE.search(raw)
    if period:
        out["salary_period"] = period.group(1).lower()
    match = SALARY_RANGE_RE.search(raw)
    if not match:
        return out
    currency, lo, lo_k, hi, hi_k = match.groups()
    if currency:
        out["salary_currency"] = {"$": "USD", "€": "EUR", "£": "GBP"}.get(
            currency, currency
        )

    def to_number(value: str, has_k: str) -> float:
        number = float(value.replace(",", ""))
        return number * 1000 if has_k else number

    out["salary_min"] = to_number(lo, lo_k)
    out["salary_max"] = to_number(hi, hi_k) if hi else out["salary_min"]
    return out


def parse_card(card, now: datetime) -> dict:
    job_id = card.get("data-id", "").strip()
    title_link = card.select_one("h2.job-position a")
    title = title_link.get_text(strip=True) if title_link else ""
    href = title_link.get("href", "") if title_link else ""
    url = f"https://dailyremote.com{href}" if href.startswith("/") else href

    # .company-name holds: [optional company text/link] · job type · posted
    company, job_type, posted_relative = "", "", ""
    meta_div = card.select_one("div.company-name")
    if meta_div:
        parts = [
            s.strip()
            for s in meta_div.stripped_strings
            if s.strip() and s.strip() != "·"
        ]
        for part in parts:
            if re.search(r"ago|yesterday|today|just now", part, re.IGNORECASE):
                posted_relative = part
            elif re.fullmatch(
                r"(full|part)[\s-]?time|internship|contract|freelance|temporary",
                part,
                re.IGNORECASE,
            ):
                job_type = part
            else:
                company = part
    if not company:
        logo = card.select_one(".pic-container img[alt]")
        if logo and logo["alt"].strip().lower() not in ("", "logo", "company logo"):
            company = logo["alt"].strip()

    location, experience, salary_raw = "", "", ""
    for tag in card.select(".job-meta .card-tag"):
        text = tag.get_text(" ", strip=True)
        if "🌎" in text:
            location = text.replace("🌎", "").strip()
        elif "⭐" in text:
            experience = text.replace("⭐", "").strip()
        elif "💵" in text:
            salary_raw = text.replace("💵", "").strip()
            if salary_raw.lower() == "salary":  # bare label, no actual figures
                salary_raw = ""

    category_tag = card.select_one(".job-category .category-tag")
    category = (
        category_tag.get_text(strip=True).lstrip("💼").strip() if category_tag else ""
    )
    role_tags = [t.get_text(strip=True) for t in card.select("a.role-tag")]

    snippet_div = card.select_one(".ai-responsibilities")
    snippet = snippet_div.get_text(" ", strip=True) if snippet_div else ""

    record = {
        "job_id": job_id,
        "title": title,
        "company": company,
        "job_type": job_type,
        "posted_relative": posted_relative,
        "posted_date_est": parse_relative_date(posted_relative, now),
        "location": location,
        "experience": experience,
        "salary_raw": salary_raw,
        "category": category,
        "tags": ", ".join(role_tags),
        "snippet": snippet,
        "url": url,
    }
    record.update(parse_salary(salary_raw))
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape DailyRemote job listings")
    parser.add_argument("--search", required=True, help='Search term, e.g. "social media"')
    parser.add_argument("--out", required=True, help="Output JSON path, e.g. tmp/jobs_raw.json")
    parser.add_argument("--max-pages", type=int, default=100, help="Safety cap on pages")
    args = parser.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    now = datetime.now()

    jobs: dict[str, dict] = {}
    pages_fetched = 0
    for page in range(1, args.max_pages + 1):
        try:
            html = fetch_page(session, args.search, page)
        except BlockedError as exc:
            print(f"BLOCKED: {exc}", file=sys.stderr)
            return 2
        cards = BeautifulSoup(html, "html.parser").select("article.js-card")
        new_ids = 0
        for card in cards:
            record = parse_card(card, now)
            if record["job_id"] and record["job_id"] not in jobs:
                jobs[record["job_id"]] = record
                new_ids += 1
        pages_fetched += 1
        print(f"page {page}: {len(cards)} cards, {new_ids} new (total {len(jobs)})")
        if new_ids == 0:  # past the last page, or pages started repeating
            break
        time.sleep(random.uniform(*DELAY_RANGE))

    if not jobs:
        print(
            "ERROR: 0 jobs parsed. The site layout may have changed — inspect the "
            "HTML and update the selectors in parse_card().",
            file=sys.stderr,
        )
        return 1

    records = list(jobs.values())
    for record in records:
        record["search_term"] = args.search

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDone: {len(records)} jobs from {pages_fetched} pages -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

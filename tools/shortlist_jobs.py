"""Merge scraped DailyRemote runs and shortlist what Esele can realistically apply to.

Filters for the constraint set that actually applies: a 300-level student in
Port Harcourt, available part-time / contract alongside school and SIWES.

    python tools/shortlist_jobs.py --in tmp/react_raw.json tmp/frontend_raw.json \
        --out output/shortlist.csv

Prints a funnel so it is obvious how many jobs each constraint removes -- the
counts matter more than the list.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

# Locations that do not exclude a Nigeria-based applicant outright. DailyRemote
# writes a country name when the role is country-restricted, so anything naming
# a specific foreign country is a hard filter.
OPEN_LOCATIONS = {
    "", "anywhere", "worldwide", "global", "remote",
    "nigeria", "africa", "emea",
}

JUNIOR_EXPERIENCE = {"", "0-2 yrs exp"}

FLEXIBLE_TYPES = {"part time", "contract", "freelance", "internship", "temporary"}

SENIOR_TITLE_WORDS = (
    "senior", "staff", "principal", "lead ", "head of", "director",
    "vp ", "architect", "manager",
)


def load(paths: list[Path]) -> list[dict]:
    seen: dict[str, dict] = {}
    for p in paths:
        for job in json.loads(p.read_text(encoding="utf-8")):
            seen.setdefault(job["job_id"], job)
    return list(seen.values())


def location_is_open(loc: str) -> bool:
    parts = [x.strip().lower() for x in loc.split(",")]
    return any(p in OPEN_LOCATIONS for p in parts)


def title_is_junior(title: str) -> bool:
    t = title.lower()
    return not any(w in t for w in SENIOR_TITLE_WORDS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inputs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    jobs = load([Path(p) for p in args.inputs])
    print(f"merged, deduped:            {len(jobs)}")

    open_loc = [j for j in jobs if location_is_open(j["location"])]
    print(f"  location open to Nigeria: {len(open_loc)}")

    junior = [j for j in open_loc if j["experience"] in JUNIOR_EXPERIENCE]
    print(f"  0-2 yrs or unstated:      {len(junior)}")

    junior = [j for j in junior if title_is_junior(j["title"])]
    print(f"  title not senior-coded:   {len(junior)}")

    flexible = [j for j in junior if j["job_type"].strip().lower() in FLEXIBLE_TYPES]
    print(f"  part-time/contract/intern:{len(flexible)}")

    # Keep both tiers: the flexible ones are the real targets, the rest are
    # full-time roles worth knowing about but not worth an application today.
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["tier", "title", "job_type", "experience", "location",
              "salary_raw", "category", "posted_relative", "url"]
    flexible_ids = {j["job_id"] for j in flexible}
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for j in flexible:
            w.writerow({"tier": "apply", **j})
        for j in junior:
            if j["job_id"] not in flexible_ids:
                w.writerow({"tier": "full-time", **j})

    print(f"\nwrote {out} -- {len(flexible)} to apply to, "
          f"{len(junior) - len(flexible)} full-time also open to you")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

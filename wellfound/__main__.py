#!/usr/bin/env python3
"""CLI: fetch Wellfound SEO role/location jobs via Playwright."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from paths import portal_output_dir
from wellfound.browser import (
    DEFAULT_BUCKET,
    DEFAULT_MAX_PAGES,
    DEFAULT_PAGE_DELAY_SECONDS,
    DEFAULT_STORAGE,
    DEFAULT_WAIT_SECONDS,
    collect_search_batches,
    listing_url,
    seed_from_url,
)
from wellfound.criteria import filter_jobs
from wellfound.filter_sort import process_jobs
from wellfound.locations import (
    TARGET_CITIES,
    count_jobs_by_experience,
    group_by_experience_city_company,
    matching_cities,
)
from wellfound.output import print_jobs_by_experience_city_company, write_jobs_json
from wellfound.skills_bank import (
    DEFAULT_SKILLS_FILE,
    top_skills_summary,
    update_skills_bank,
)

_PKG_DIR = Path(__file__).resolve().parent
DEFAULT_URLS_FILE = str(_PKG_DIR / "urls.txt")
DEFAULT_OUT = str(portal_output_dir("wellfound") / "jobs.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract Wellfound jobs from SEO /role/l/{role}/{location} pages "
            "using headed Playwright (DataDome/Turnstile). Defaults: "
            f"urls from wellfound/urls.txt, bucket={DEFAULT_BUCKET}, "
            f"cities={', '.join(TARGET_CITIES)}, output {DEFAULT_OUT}."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--all",
        action="store_true",
        help="Fetch all paginated jobs for each listing URL",
    )
    mode.add_argument(
        "--fresh",
        type=int,
        metavar="MINUTES",
        help="Keep only jobs with liveStartAt in the last N minutes",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help=f"Output JSON path (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--urls-file",
        default=DEFAULT_URLS_FILE,
        help=f"Wellfound /role/l/… URLs (default: {DEFAULT_URLS_FILE})",
    )
    parser.add_argument(
        "--url",
        action="append",
        dest="urls",
        default=None,
        help="Listing URL (repeatable). Overrides --urls-file when set.",
    )
    parser.add_argument(
        "--role",
        default="",
        help="Role slug (e.g. backend-engineer). Used with --location.",
    )
    parser.add_argument(
        "--location",
        default="india",
        help="Location slug (default: india). Used with --role.",
    )
    parser.add_argument(
        "--bucket",
        default=DEFAULT_BUCKET,
        help=(
            "Outer JSON key (Wellfound SEO is not split by YOE like Instahyre). "
            f"Default: {DEFAULT_BUCKET}"
        ),
    )
    parser.add_argument(
        "--experience-years",
        default="",
        help=(
            "Optional local YOE overlap filter, e.g. 3,4. Jobs with null "
            "yearsExperience* are kept unless --drop-unknown-experience."
        ),
    )
    parser.add_argument(
        "--drop-unknown-experience",
        action="store_true",
        help="Drop jobs with missing yearsExperienceMin/Max when filtering YOE",
    )
    parser.add_argument(
        "--storage",
        default=DEFAULT_STORAGE,
        help=f"Playwright storage_state path (default: {DEFAULT_STORAGE})",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=DEFAULT_WAIT_SECONDS,
        help=f"Seconds to wait for challenge/Apollo (default: {DEFAULT_WAIT_SECONDS})",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Max pages per listing (default: {DEFAULT_MAX_PAGES})",
    )
    parser.add_argument(
        "--page-delay",
        type=float,
        default=DEFAULT_PAGE_DELAY_SECONDS,
        help=(
            "Seconds between page navigations "
            f"(default: {DEFAULT_PAGE_DELAY_SECONDS})"
        ),
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chromium headless (CAPTCHA harder; headed is default)",
    )
    parser.add_argument(
        "--skills-out",
        default=DEFAULT_SKILLS_FILE,
        help=f"Skills JSON (default: {DEFAULT_SKILLS_FILE})",
    )
    return parser


def _load_urls_file(path: str | Path) -> list[str]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    urls: list[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for token in line.split():
            if token.startswith("http://") or token.startswith("https://"):
                urls.append(token)
    return urls


def _parse_years(raw: str) -> list[int]:
    years: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        years.append(int(part))
    return years


def _in_target_cities(job: dict[str, Any]) -> bool:
    return bool(matching_cities(str(job.get("location") or "")))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.fresh is not None and args.fresh <= 0:
        parser.error("--fresh MINUTES must be a positive integer")
    fresh_minutes = args.fresh if args.fresh is not None else None

    experience_years: list[int] = []
    if args.experience_years:
        try:
            experience_years = _parse_years(args.experience_years)
        except ValueError:
            parser.error("--experience-years must be comma-separated integers")

    urls: list[str] = []
    if args.urls:
        urls = list(args.urls)
    elif args.role:
        urls = [listing_url(args.role.strip(), (args.location or "india").strip())]
    elif args.urls_file:
        urls_path = Path(args.urls_file)
        if not urls_path.exists():
            print(f"Error: urls file not found: {args.urls_file}", file=sys.stderr)
            return 1
        urls = _load_urls_file(urls_path)

    # Drop unrecognized lines early with a clear error.
    valid = [url for url in urls if seed_from_url(url) is not None]
    if not valid:
        print(
            "Error: no Wellfound /role/l/{role}/{location} URLs. "
            "Pass --url, --role/--location, or wellfound/urls.txt.",
            file=sys.stderr,
        )
        return 1
    for url in urls:
        if seed_from_url(url) is None:
            host = urlparse(url).netloc
            print(f"Warning: skipping non-listing URL ({host}): {url}")

    mode = f"--fresh {fresh_minutes}" if fresh_minutes is not None else "--all"
    print(
        f"Will fetch Wellfound ({mode}, {len(valid)} listing(s), "
        f"max_pages={args.max_pages}, page_delay={args.page_delay}s, "
        f"headless={args.headless})."
    )
    print(
        "Note: salary/YOE are often empty on SEO cards; "
        "skills are usually absent. Expect CAPTCHA on first run."
    )

    try:
        batches = collect_search_batches(
            valid,
            storage_path=args.storage,
            wait_seconds=args.wait_seconds,
            max_pages=args.max_pages,
            page_delay_seconds=args.page_delay,
            headless=args.headless,
        )
    except Exception as exc:
        print(f"Error while fetching Wellfound: {exc}", file=sys.stderr)
        return 1

    raw_jobs: list[dict[str, Any]] = []
    for batch in batches:
        raw_jobs.extend(batch.jobs)

    before = len(raw_jobs)
    jobs = filter_jobs(
        raw_jobs,
        fresh_minutes=fresh_minutes,
        experience_years=experience_years or None,
        keep_unknown_experience=not args.drop_unknown_experience,
    )
    after_filter = len(jobs)
    jobs = [job for job in jobs if _in_target_cities(job)]
    jobs = process_jobs(jobs)
    print(
        f"{before} raw → {after_filter} after title/fresh/YOE filter → "
        f"{len(jobs)} in {', '.join(TARGET_CITIES)}"
    )

    bucket = args.bucket or DEFAULT_BUCKET
    jobs_by_exp = {bucket: jobs}
    grouped = group_by_experience_city_company(
        jobs_by_exp, experience_keys=[bucket]
    )
    for city in TARGET_CITIES:
        companies = grouped[bucket][city]
        print(
            f"  [{bucket}] {city}: "
            f"{sum(len(v) for v in companies.values())} jobs "
            f"({len(companies)} cos)"
        )

    print_jobs_by_experience_city_company(grouped)
    out_path = write_jobs_json(jobs_by_exp, args.out, experience_keys=[bucket])
    print(
        f"Saved JSON: {out_path} "
        f"({len(jobs)} unique jobs; "
        f"{count_jobs_by_experience(grouped)} city placements)"
    )

    skills_path, prev_count, new_count = update_skills_bank(jobs, args.skills_out)
    print(
        f"Saved skills referrals: {skills_path} "
        f"({new_count} skills from {len(jobs)} jobs; was {prev_count})"
    )
    print(f"Top skills: {top_skills_summary(skills_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

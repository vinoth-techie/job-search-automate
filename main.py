#!/usr/bin/env python3
"""CLI: fetch Naukri search jobs via Playwright API capture."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from naukri.browser import (
    DEFAULT_STORAGE,
    collect_search_batches,
    expected_keyword_from_listing_url,
)
from naukri.criteria import (
    filter_by_keywords,
    keywords_from_listing_slug,
    split_by_criteria,
)
from naukri.extract import extract_jobs_from_payload
from naukri.filter_sort import dedupe_across_experience_keys, process_jobs
from naukri.locations import (
    TARGET_CITIES,
    count_jobs_by_experience,
    group_by_experience_city_company,
)
from naukri.output import print_jobs_by_experience_city_company, write_jobs_json
from naukri.skills_bank import (
    DEFAULT_SKILLS_FILE,
    top_skills_summary,
    update_skills_bank,
)
from paths import REPO_ROOT, portal_output_dir

_NAUKRI_DIR = REPO_ROOT / "naukri"
_OUT_DIR = portal_output_dir("naukri")
DEFAULT_URLS_FILE = str(_NAUKRI_DIR / "urls.txt")
DEFAULT_OUT = str(_OUT_DIR / "jobs.json")
DEFAULT_NO_SALARY_OUT = str(_OUT_DIR / "jobs_no_salary.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract Naukri jobs by opening listing page(s) in Playwright "
            "and capturing /jobapi/v3/search responses. "
            f"Pass many URLs via --urls-file (default: {DEFAULT_URLS_FILE}). "
            "Each URL is run with experience=3 and experience=4, then grouped as "
            "experience → city → company. Titles with test/support are ignored. "
            "Skills/title must match at least one keyword from that listing URL."
        )
    )
    parser.add_argument(
        "--url",
        action="append",
        dest="urls",
        default=None,
        help="Listing URL (repeatable). If omitted, uses --urls-file.",
    )
    parser.add_argument(
        "--urls-file",
        default=DEFAULT_URLS_FILE,
        help=f"Text file with one Naukri URL per line (default: {DEFAULT_URLS_FILE})",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--fresh",
        type=int,
        metavar="MINUTES",
        help="Keep only jobs with createdDate within the last N minutes",
    )
    mode.add_argument(
        "--all",
        action="store_true",
        help="Keep all jobs returned by the search (all pages)",
    )

    parser.add_argument(
        "--storage",
        default=DEFAULT_STORAGE,
        help=f"Playwright storage_state path (default: {DEFAULT_STORAGE})",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help=f"Matched jobs JSON (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--no-salary-out",
        default=DEFAULT_NO_SALARY_OUT,
        help=f"No-salary jobs JSON (default: {DEFAULT_NO_SALARY_OUT})",
    )
    parser.add_argument(
        "--exp-min",
        type=float,
        default=3,
        help="Min years for experience overlap filter (default: 3)",
    )
    parser.add_argument(
        "--exp-max",
        type=float,
        default=4,
        help="Max years for experience overlap filter (default: 4)",
    )
    parser.add_argument(
        "--min-salary",
        type=float,
        default=10,
        help="Minimum salary in LPA for matched jobs (default: 10)",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=180,
        help="Seconds to wait for the first search API response (default: 180)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=50,
        help="Maximum search pages to fetch (default: 50)",
    )
    parser.add_argument(
        "--experience-years",
        default="3,4",
        help=(
            "Comma-separated Naukri experience= values to run "
            "(default: 3,4). Becomes top-level JSON keys."
        ),
    )
    parser.add_argument(
        "--skills-out",
        default=DEFAULT_SKILLS_FILE,
        help=f"Static unique skills JSON (default: {DEFAULT_SKILLS_FILE})",
    )
    return parser


def _parse_experience_years(raw: str) -> list[int]:
    years: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        years.append(int(part))
    if not years:
        raise ValueError("at least one experience year is required")
    return years


def _load_urls_file(path: str | Path) -> list[str]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"URLs file not found: {file_path}")
    urls: list[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Allow multiple URLs accidentally pasted on one line
        for token in line.split():
            if token.startswith("http://") or token.startswith("https://"):
                urls.append(token)
    if not urls:
        raise ValueError(f"no URLs found in {file_path}")
    return urls


def _resolve_urls(args: argparse.Namespace) -> list[str]:
    if args.urls:
        return args.urls
    return _load_urls_file(args.urls_file)


def _jobs_from_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for payload in payloads:
        jobs.extend(extract_jobs_from_payload(payload))
    return jobs


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.fresh is not None and args.fresh < 0:
        parser.error("--fresh must be >= 0")

    try:
        experience_years = _parse_experience_years(args.experience_years)
        listing_urls = _resolve_urls(args)
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))

    exp_keys = [str(year) for year in experience_years]

    try:
        print(f"URLs: {len(listing_urls)}")
        for index, url in enumerate(listing_urls, start=1):
            print(f"  {index}. {url}")
        print(
            f"Will run each URL with experience={experience_years} "
            f"({len(listing_urls) * len(experience_years)} searches total). "
            "Ignore titles with test/support; require skills/title keyword match."
        )
        batches = collect_search_batches(
            listing_urls,
            storage_path=args.storage,
            wait_seconds=args.wait,
            max_pages=args.max_pages,
            paginate=True,
            experience_years=experience_years,
        )
    except TimeoutError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error while capturing Naukri search: {exc}", file=sys.stderr)
        return 1

    fresh_minutes = None if args.all else args.fresh
    matched_by_exp: dict[str, list[dict[str, Any]]] = {key: [] for key in exp_keys}
    no_salary_by_exp: dict[str, list[dict[str, Any]]] = {key: [] for key in exp_keys}

    for batch in batches:
        slug = expected_keyword_from_listing_url(batch.listing_url)
        keywords = keywords_from_listing_slug(slug)
        jobs = _jobs_from_payloads(batch.payloads)
        before = len(jobs)
        jobs = filter_by_keywords(jobs, keywords)
        print(
            f"[{batch.experience}] {slug or '?'}: "
            f"{before} → {len(jobs)} after skills/title keyword filter "
            f"(need any of: {', '.join(keywords[:6])}{'…' if len(keywords) > 6 else ''})"
        )
        jobs = process_jobs(jobs, fresh_minutes=fresh_minutes)
        matched, no_salary = split_by_criteria(
            jobs,
            exp_min=args.exp_min,
            exp_max=args.exp_max,
            min_salary_lpa=args.min_salary,
        )
        matched_by_exp.setdefault(batch.experience, []).extend(matched)
        no_salary_by_exp.setdefault(batch.experience, []).extend(no_salary)

    for key in exp_keys:
        matched_by_exp[key] = process_jobs(
            matched_by_exp.get(key) or [], fresh_minutes=None
        )
        no_salary_by_exp[key] = process_jobs(
            no_salary_by_exp.get(key) or [], fresh_minutes=None
        )

    # One jobId only under 3 OR 4 (prefer earlier key, usually 3)
    matched_by_exp = dedupe_across_experience_keys(matched_by_exp, exp_keys)
    no_salary_by_exp = dedupe_across_experience_keys(no_salary_by_exp, exp_keys)

    for key in exp_keys:
        print(
            f"experience={key}: "
            f"matched={len(matched_by_exp[key])} "
            f"no_salary={len(no_salary_by_exp[key])}"
        )

    print(
        f"Criteria: experience overlaps {args.exp_min}-{args.exp_max} yrs, "
        f"salary >= {args.min_salary} LPA, "
        "title ignores test/support, "
        "skills/title must match listing keyword, "
        "jobId unique across experience keys (prefer 3 over 4)"
    )
    print(
        f"Grouping: experience → city → company "
        f"({', '.join(TARGET_CITIES)})"
    )

    matched_grouped = group_by_experience_city_company(
        matched_by_exp, experience_keys=exp_keys
    )
    no_salary_grouped = group_by_experience_city_company(
        no_salary_by_exp, experience_keys=exp_keys
    )

    for key in exp_keys:
        for city in TARGET_CITIES:
            m_companies = matched_grouped[key][city]
            n_companies = no_salary_grouped[key][city]
            print(
                f"  [{key}] {city}: "
                f"matched={sum(len(v) for v in m_companies.values())} "
                f"({len(m_companies)} cos), "
                f"no_salary={sum(len(v) for v in n_companies.values())} "
                f"({len(n_companies)} cos)"
            )

    print_jobs_by_experience_city_company(matched_grouped)
    out_path = write_jobs_json(
        matched_by_exp, args.out, experience_keys=exp_keys
    )
    no_salary_path = write_jobs_json(
        no_salary_by_exp, args.no_salary_out, experience_keys=exp_keys
    )
    matched_unique = sum(len(matched_by_exp.get(key) or []) for key in exp_keys)
    no_salary_unique = sum(len(no_salary_by_exp.get(key) or []) for key in exp_keys)
    print(
        f"Saved JSON: {out_path} "
        f"({matched_unique} unique jobs; "
        f"{count_jobs_by_experience(matched_grouped)} city placements)"
    )
    print(
        f"Saved no-salary JSON: {no_salary_path} "
        f"({no_salary_unique} unique jobs; "
        f"{count_jobs_by_experience(no_salary_grouped)} city placements)"
    )

    # Only skills from jobs that passed our filters (matched + no-salary).
    kept_for_skills: list[dict[str, Any]] = []
    for key in exp_keys:
        kept_for_skills.extend(matched_by_exp.get(key) or [])
        kept_for_skills.extend(no_salary_by_exp.get(key) or [])
    skills_path, prev_count, new_count = update_skills_bank(
        kept_for_skills, args.skills_out
    )
    print(
        f"Saved skills referrals: {skills_path} "
        f"({new_count} skills from {len(kept_for_skills)} jobs; "
        f"was {prev_count})"
    )
    print(f"Top skills: {top_skills_summary(skills_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

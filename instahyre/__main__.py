#!/usr/bin/env python3
"""CLI: fetch Instahyre opportunity jobs via /api/v1/job_search."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from instahyre.api import (
    DEFAULT_MAX_PAGES,
    DEFAULT_PAGE_DELAY_SECONDS,
    collect_search_batches,
)
from instahyre.criteria import (
    filter_jobs,
    interest_keywords_from_urls,
)
from instahyre.extract import extract_jobs_from_payload
from instahyre.filter_sort import dedupe_across_experience_keys, process_jobs
from instahyre.locations import (
    TARGET_CITIES,
    count_jobs_by_experience,
    group_by_experience_city_company,
    matching_cities,
)
from instahyre.output import print_jobs_by_experience_city_company, write_jobs_json
from instahyre.skills_bank import DEFAULT_SKILLS_FILE, update_skills_bank

DEFAULT_URLS_FILE = "urls.txt"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract Instahyre jobs from /api/v1/job_search "
            "(opportunities feed). Runs years=3 and years=4 by default, "
            "paginates via offset, ignores test/support titles, keeps "
            "target cities, optionally filters by interest keywords from "
            "urls.txt, groups as years → city → company."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--all",
        action="store_true",
        help="Fetch all paginated jobs for each years= value",
    )
    mode.add_argument(
        "--fresh",
        type=int,
        metavar="MINUTES",
        help=(
            "Not supported: Instahyre job_search objects have no createdDate. "
            "Use --all."
        ),
    )
    parser.add_argument(
        "--out",
        default="instahyre_jobs.json",
        help="Output JSON path (default: instahyre_jobs.json)",
    )
    parser.add_argument(
        "--experience-years",
        default="3,4",
        help="Comma-separated years= values (default: 3,4)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Max pages per years= value (default: {DEFAULT_MAX_PAGES})",
    )
    parser.add_argument(
        "--page-delay",
        type=float,
        default=DEFAULT_PAGE_DELAY_SECONDS,
        help=(
            "Seconds to wait between page requests "
            f"(default: {DEFAULT_PAGE_DELAY_SECONDS})"
        ),
    )
    parser.add_argument(
        "--urls-file",
        default=DEFAULT_URLS_FILE,
        help=(
            "Optional Naukri-style URLs file; skill tokens from URL slugs "
            f"filter Instahyre keywords/title (default: {DEFAULT_URLS_FILE}). "
            "Pass empty string to disable keyword filter."
        ),
    )
    parser.add_argument(
        "--no-keyword-filter",
        action="store_true",
        help="Keep all non-ignored titles in target cities (skip skill filter)",
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


def _jobs_from_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for payload in payloads:
        jobs.extend(extract_jobs_from_payload(payload))
    return jobs


def _in_target_cities(job: dict[str, Any]) -> bool:
    return bool(matching_cities(str(job.get("location") or "")))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.fresh is not None:
        print(
            "Error: Instahyre /api/v1/job_search objects do not include "
            "createdDate, so --fresh is unavailable. Use --all.",
            file=sys.stderr,
        )
        return 2

    try:
        experience_years = _parse_experience_years(args.experience_years)
    except ValueError as exc:
        parser.error(str(exc))

    exp_keys = [str(year) for year in experience_years]

    keywords: list[str] = []
    if not args.no_keyword_filter and args.urls_file:
        urls = _load_urls_file(args.urls_file)
        keywords = interest_keywords_from_urls(urls)
        if urls:
            print(
                f"Interest keywords from {args.urls_file} "
                f"({len(urls)} URLs): {', '.join(keywords[:12])}"
                f"{'…' if len(keywords) > 12 else ''}"
            )
        else:
            print(
                f"No URLs in {args.urls_file}; "
                "running without skill keyword filter."
            )

    try:
        print(
            f"Will fetch Instahyre opportunities for years={experience_years} "
            f"(max_pages={args.max_pages}, page_delay={args.page_delay}s each)."
        )
        batches = collect_search_batches(
            experience_years=experience_years,
            max_pages=args.max_pages,
            page_delay_seconds=args.page_delay,
        )
    except Exception as exc:
        print(f"Error while fetching Instahyre search: {exc}", file=sys.stderr)
        return 1

    jobs_by_exp: dict[str, list[dict[str, Any]]] = {key: [] for key in exp_keys}

    for batch in batches:
        jobs = _jobs_from_payloads(batch.payloads)
        before = len(jobs)
        jobs = filter_jobs(jobs, keywords=keywords or None)
        after_kw = len(jobs)
        jobs = [job for job in jobs if _in_target_cities(job)]
        jobs = process_jobs(jobs)
        print(
            f"[years={batch.years}] {before} raw → {after_kw} after "
            f"title/keyword filter → {len(jobs)} in "
            f"{', '.join(TARGET_CITIES)}"
        )
        jobs_by_exp.setdefault(batch.years, []).extend(jobs)

    for key in exp_keys:
        jobs_by_exp[key] = process_jobs(jobs_by_exp.get(key) or [])

    jobs_by_exp = dedupe_across_experience_keys(jobs_by_exp, exp_keys)

    for key in exp_keys:
        print(f"years={key}: kept={len(jobs_by_exp[key])}")

    print(
        "Note: Instahyre search has no per-job salary/createdDate; "
        "experience is the years= filter. "
        "jobId unique across years keys (prefer 3 over 4)."
    )
    print(f"Grouping: years → city → company ({', '.join(TARGET_CITIES)})")

    grouped = group_by_experience_city_company(
        jobs_by_exp, experience_keys=exp_keys
    )
    for key in exp_keys:
        for city in TARGET_CITIES:
            companies = grouped[key][city]
            print(
                f"  [{key}] {city}: "
                f"{sum(len(v) for v in companies.values())} jobs "
                f"({len(companies)} cos)"
            )

    print_jobs_by_experience_city_company(grouped)
    out_path = write_jobs_json(jobs_by_exp, args.out, experience_keys=exp_keys)
    print(
        f"Saved JSON: {out_path} "
        f"({count_jobs_by_experience(grouped)} jobs)"
    )

    # Only skills from jobs that passed filters (keyword/title/city/dedupe).
    kept_for_skills: list[dict[str, Any]] = []
    for key in exp_keys:
        kept_for_skills.extend(jobs_by_exp.get(key) or [])
    skills_path, prev_count, new_count = update_skills_bank(
        kept_for_skills, args.skills_out
    )
    print(
        f"Saved skills bank (from kept jobs only): {skills_path} "
        f"({prev_count} → {new_count} unique skills)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

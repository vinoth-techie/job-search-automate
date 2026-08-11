#!/usr/bin/env python3
"""CLI: fetch Hirist jobs via gladiator keyword/category APIs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from hirist.api import (
    DEFAULT_LOC,
    DEFAULT_MAX_PAGES,
    DEFAULT_PAGE_DELAY_SECONDS,
    collect_search_batches,
    hirist_slug_from_token,
    parse_experience_ranges,
    resolve_keywords,
    slug_from_hirist_url,
)
from hirist.criteria import (
    filter_jobs,
    interest_keywords_from_urls,
    slug_from_naukri_url,
)
from hirist.extract import extract_jobs_from_payload
from hirist.filter_sort import dedupe_across_experience_keys, process_jobs
from hirist.locations import (
    TARGET_CITIES,
    count_jobs_by_experience,
    group_by_experience_city_company,
    matching_cities,
)
from hirist.output import print_jobs_by_experience_city_company, write_jobs_json
from hirist.skills_bank import (
    DEFAULT_SKILLS_FILE,
    top_skills_summary,
    update_skills_bank,
)
from paths import portal_output_dir

_PKG_DIR = Path(__file__).resolve().parent
DEFAULT_URLS_FILE = str(_PKG_DIR / "urls.txt")
DEFAULT_OUT = str(portal_output_dir("hirist") / "jobs.json")
DEFAULT_EXPERIENCE_RANGES = "2-3"
DEFAULT_POSTING = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract Hirist jobs from gladiator /job/keyword/ (skill pages "
            "like /k/python-jobs) or /job/category/. Defaults: skills from "
            f"hirist/urls.txt, exp {DEFAULT_EXPERIENCE_RANGES}, "
            f"posting={DEFAULT_POSTING} days, "
            f"loc=Naukri target cities ({', '.join(TARGET_CITIES)}), "
            f"output {DEFAULT_OUT}."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--all",
        action="store_true",
        help="Fetch all paginated jobs for each experience range",
    )
    mode.add_argument(
        "--fresh",
        type=int,
        metavar="MINUTES",
        help="Keep only jobs with createdTimeMs in the last N minutes",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help=f"Output JSON path (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--experience-ranges",
        default=DEFAULT_EXPERIENCE_RANGES,
        help=(
            "Comma-separated minexp-maxexp ranges "
            f"(default: {DEFAULT_EXPERIENCE_RANGES})"
        ),
    )
    parser.add_argument(
        "--posting",
        type=int,
        default=DEFAULT_POSTING,
        metavar="DAYS",
        help=(
            "Hirist posting= filter in days "
            f"(default: {DEFAULT_POSTING}). Pass 0 for all ages."
        ),
    )
    parser.add_argument(
        "--keywords",
        default="",
        help=(
            "Comma-separated Hirist skills (python,java,spring-boot). "
            "If omitted, skills are derived from --urls-file "
            "(Hirist /k/… or Naukri …-jobs URLs)."
        ),
    )
    parser.add_argument(
        "--category",
        action="store_true",
        help="Use broad /job/category/ instead of skill /job/keyword/",
    )
    parser.add_argument(
        "--loc",
        default=DEFAULT_LOC,
        help=f"Hirist loc= ids (default: target cities {DEFAULT_LOC})",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Max pages per skill×range (default: {DEFAULT_MAX_PAGES})",
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
            "URLs file for Hirist /k/ skill pages and/or Naukri skill slugs "
            f"(default: {DEFAULT_URLS_FILE}). "
            "Pass empty string to skip."
        ),
    )
    parser.add_argument(
        "--local-keyword-filter",
        action="store_true",
        help=(
            "Also apply local title/skills keyword filter from Naukri slugs "
            "(usually unnecessary when using /job/keyword/)."
        ),
    )
    parser.add_argument(
        "--skills-out",
        default=DEFAULT_SKILLS_FILE,
        help=f"Static unique skills JSON (default: {DEFAULT_SKILLS_FILE})",
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


def _skill_tokens_from_urls(urls: list[str]) -> list[str]:
    """Prefer Hirist /k/ slugs; else Naukri listing slugs."""
    tokens: list[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        token = hirist_slug_from_token(token)
        if token and token not in seen:
            seen.add(token)
            tokens.append(token)

    for url in urls:
        host = urlparse(url).netloc.lower()
        if "hirist.tech" in host:
            slug = slug_from_hirist_url(url)
            if slug:
                add(slug)
            continue
        naukri_slug = slug_from_naukri_url(url)
        if naukri_slug:
            add(naukri_slug)
    return tokens


def _parse_keywords_arg(raw: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        slug = hirist_slug_from_token(part)
        if slug not in seen:
            seen.add(slug)
            tokens.append(slug)
    return tokens


def _filters_from_hirist_urls(urls: list[str]) -> tuple[str | None, int | None]:
    """Read minexp/maxexp/posting from the first Hirist /k/ URL that has them."""
    exp_raw: str | None = None
    posting: int | None = None
    for url in urls:
        if "hirist.tech" not in urlparse(url).netloc.lower():
            continue
        qs = parse_qs(urlparse(url).query)
        minexp = (qs.get("minexp") or [None])[0]
        maxexp = (qs.get("maxexp") or [None])[0]
        if minexp is not None and maxexp is not None and exp_raw is None:
            exp_raw = f"{minexp}-{maxexp}"
        if posting is None and qs.get("posting"):
            try:
                posting = int(qs["posting"][0])
            except (TypeError, ValueError):
                pass
        if exp_raw is not None and posting is not None:
            break
    return exp_raw, posting


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

    if args.fresh is not None and args.fresh <= 0:
        parser.error("--fresh MINUTES must be a positive integer")
    fresh_minutes = args.fresh if args.fresh is not None else None

    urls: list[str] = []
    if args.urls_file:
        urls_path = Path(args.urls_file)
        if not urls_path.exists():
            print(
                f"Error: urls file not found: {args.urls_file}",
                file=sys.stderr,
            )
            return 1
        urls = _load_urls_file(urls_path)

    url_exp, url_posting = _filters_from_hirist_urls(urls)

    # Prefer filters embedded in hirist/urls.txt when CLI left the defaults.
    experience_raw = args.experience_ranges
    if url_exp and args.experience_ranges == DEFAULT_EXPERIENCE_RANGES:
        experience_raw = url_exp

    try:
        experience_ranges = parse_experience_ranges(experience_raw)
    except ValueError as exc:
        parser.error(str(exc))

    exp_keys = [item.key for item in experience_ranges]

    posting = args.posting
    if posting == 0:
        posting = None
    elif url_posting is not None and args.posting == DEFAULT_POSTING:
        posting = url_posting

    skill_tokens = _parse_keywords_arg(args.keywords)
    if not skill_tokens and urls:
        skill_tokens = _skill_tokens_from_urls(urls)

    keyword_refs = None
    if not args.category:
        if not skill_tokens:
            print(
                "Error: no Hirist skills found. Pass --keywords, skill URLs "
                "in --urls-file, or use --category for the broad category feed.",
                file=sys.stderr,
            )
            return 1
        print(f"Resolving {len(skill_tokens)} Hirist skill page(s)…")
        keyword_refs = resolve_keywords(skill_tokens)
        if not keyword_refs:
            print(
                "Error: could not resolve any Hirist keywordIds.",
                file=sys.stderr,
            )
            return 1

    local_keywords: list[str] = []
    if args.local_keyword_filter and urls:
        local_keywords = interest_keywords_from_urls(urls)
        if local_keywords:
            print(
                f"Local keyword filter: {', '.join(local_keywords[:12])}"
                f"{'…' if len(local_keywords) > 12 else ''}"
            )

    try:
        mode = (
            f"--fresh {fresh_minutes}"
            if fresh_minutes is not None
            else "--all"
        )
        api_mode = (
            f"keyword×{len(keyword_refs)}"
            if keyword_refs
            else "category"
        )
        posting_label = f"posting={posting}" if posting is not None else "posting=all"
        print(
            f"Will fetch Hirist ({mode}, {api_mode}, {posting_label}) "
            f"for ranges={exp_keys} loc={args.loc} "
            f"(max_pages={args.max_pages}, page_delay={args.page_delay}s)."
        )
        batches = collect_search_batches(
            experience_ranges=experience_ranges,
            keywords=keyword_refs,
            max_pages=args.max_pages,
            loc=args.loc,
            posting=posting,
            page_delay_seconds=args.page_delay,
        )
    except Exception as exc:
        print(f"Error while fetching Hirist search: {exc}", file=sys.stderr)
        return 1

    jobs_by_exp: dict[str, list[dict[str, Any]]] = {key: [] for key in exp_keys}

    for batch in batches:
        jobs = _jobs_from_payloads(batch.payloads)
        before = len(jobs)
        jobs = filter_jobs(
            jobs,
            keywords=local_keywords or None,
            fresh_minutes=fresh_minutes,
        )
        after_kw = len(jobs)
        jobs = [job for job in jobs if _in_target_cities(job)]
        jobs = process_jobs(jobs)
        print(
            f"[{batch.experience_key}] {before} raw → {after_kw} after "
            f"title/keyword/fresh filter → {len(jobs)} in "
            f"{', '.join(TARGET_CITIES)}"
        )
        jobs_by_exp.setdefault(batch.experience_key, []).extend(jobs)

    for key in exp_keys:
        jobs_by_exp[key] = process_jobs(jobs_by_exp.get(key) or [])

    jobs_by_exp = dedupe_across_experience_keys(jobs_by_exp, exp_keys)

    for key in exp_keys:
        print(f"exp={key}: kept={len(jobs_by_exp[key])}")

    print(
        "Note: Hirist minexp/maxexp is an overlap filter on job bands; "
        "jobId unique across ranges (prefer earlier ranges). "
        "Grouping: exp → city → company "
        f"({', '.join(TARGET_CITIES)})"
    )

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
    unique_kept = sum(len(jobs_by_exp.get(key) or []) for key in exp_keys)
    print(
        f"Saved JSON: {out_path} "
        f"({unique_kept} unique jobs; "
        f"{count_jobs_by_experience(grouped)} city placements)"
    )

    kept_for_skills: list[dict[str, Any]] = []
    for key in exp_keys:
        kept_for_skills.extend(jobs_by_exp.get(key) or [])
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

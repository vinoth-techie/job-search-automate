"""Extract and normalize job fields from Wellfound Apollo / __NEXT_DATA__."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

JOB_URL_TEMPLATE = "https://wellfound.com/jobs/{job_id}-{slug}"


def _ref_id(node: Any) -> str | None:
    if isinstance(node, dict) and isinstance(node.get("__ref"), str):
        return node["__ref"]
    if isinstance(node, str) and ":" in node:
        return node
    return None


def _resolve(data: dict[str, Any], node: Any) -> Any:
    ref = _ref_id(node)
    if ref is None:
        return node
    return data.get(ref)


def _location_label(job: dict[str, Any]) -> str:
    locs = job.get("locationNames") or []
    if not isinstance(locs, list):
        return ""
    names = [str(item).strip() for item in locs if str(item).strip()]
    remote_names = job.get("acceptedRemoteLocationNames") or []
    if isinstance(remote_names, list):
        for item in remote_names:
            name = str(item).strip()
            if name and name not in names:
                names.append(name)
    if job.get("remote") and not names:
        return "Remote"
    return ",".join(names)


def _experience_label(job: dict[str, Any]) -> str:
    raw_min = job.get("yearsExperienceMin")
    raw_max = job.get("yearsExperienceMax")
    if raw_min is None and raw_max is None:
        return ""
    try:
        min_y = int(raw_min) if raw_min is not None else None
        max_y = int(raw_max) if raw_max is not None else None
    except (TypeError, ValueError):
        return ""
    if min_y is None and max_y is None:
        return ""
    if min_y is not None and max_y is not None:
        return f"{min_y}-{max_y} yrs"
    if max_y is not None:
        return f"0-{max_y} yrs"
    return f"{min_y}+ yrs"


def _created_ms(job: dict[str, Any]) -> int:
    raw = job.get("liveStartAt")
    if raw is None:
        return 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    if value <= 0:
        return 0
    # Wellfound uses unix seconds.
    if value < 10_000_000_000:
        value *= 1000
    return value


def _posted_label(created_ms: int) -> str:
    if created_ms <= 0:
        return ""
    try:
        from zoneinfo import ZoneInfo

        ist = ZoneInfo("Asia/Kolkata")
        dt = datetime.fromtimestamp(created_ms / 1000.0, tz=timezone.utc).astimezone(
            ist
        )
    except (OverflowError, OSError, ValueError):
        return ""
    return dt.strftime("%Y-%m-%d")


def extract_job(
    job: dict[str, Any],
    *,
    company: str,
) -> dict[str, Any] | None:
    job_id = job.get("id")
    if job_id is None:
        return None
    slug = str(job.get("slug") or "").strip("-")
    created_ms = _created_ms(job)
    return {
        "jobId": str(job_id),
        "title": str(job.get("title") or ""),
        "company": company,
        "skills": "",
        "experience": _experience_label(job),
        "location": _location_label(job),
        "salary": str(job.get("compensation") or "").strip(),
        "createdDate": created_ms,
        "posted": _posted_label(created_ms),
        "url": JOB_URL_TEMPLATE.format(job_id=job_id, slug=slug or "job"),
        "yearsExperienceMin": job.get("yearsExperienceMin"),
        "yearsExperienceMax": job.get("yearsExperienceMax"),
    }


def _apollo_data_from_next(next_data: dict[str, Any]) -> dict[str, Any]:
    page_props = next_data.get("props", {}).get("pageProps", {})
    apollo = page_props.get("apolloState") or {}
    data = apollo.get("data")
    return data if isinstance(data, dict) else {}


def _search_results_node(data: dict[str, Any]) -> dict[str, Any] | None:
    root = data.get("ROOT_QUERY") or {}
    talent = root.get("talent")
    if not isinstance(talent, dict):
        return None
    for key, value in talent.items():
        if key.startswith("seoLandingPageJobSearchResults") and isinstance(value, dict):
            return value
    return None


def extract_jobs_from_apollo(data: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Flatten StartupResult → JobListingSearchResult into normalized jobs.

    Returns (jobs, meta) where meta has pageCount / totalJobCount when present.
    """
    results = _search_results_node(data)
    meta: dict[str, Any] = {}
    if not isinstance(results, dict):
        return [], meta

    for key in ("pageCount", "perPage", "totalJobCount", "totalStartupCount"):
        if key in results:
            meta[key] = results.get(key)

    jobs: list[dict[str, Any]] = []
    startups = results.get("startups") or []
    if not isinstance(startups, list):
        return jobs, meta

    for startup_ref in startups:
        startup = _resolve(data, startup_ref)
        if not isinstance(startup, dict):
            continue
        company = str(startup.get("name") or "").strip() or "Unknown"
        listings = startup.get("highlightedJobListings") or []
        if not isinstance(listings, list):
            continue
        for listing_ref in listings:
            listing = _resolve(data, listing_ref)
            if not isinstance(listing, dict):
                continue
            normalized = extract_job(listing, company=company)
            if normalized:
                jobs.append(normalized)
    return jobs, meta


def extract_jobs_from_next_data(next_data: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return extract_jobs_from_apollo(_apollo_data_from_next(next_data))


def extract_jobs_from_html(html: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    if not match:
        return [], {}
    try:
        next_data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return [], {}
    if not isinstance(next_data, dict):
        return [], {}
    return extract_jobs_from_next_data(next_data)

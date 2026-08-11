"""Local filters: ignored titles, freshness from liveStartAt."""

from __future__ import annotations

import re
import time
from typing import Any

_TITLE_IGNORE = re.compile(
    r"\b("
    r"test|tests|tester|testers|testing|tested|"
    r"qa|q\.?a\.?|"
    r"quality\s*assurance|quality\s*analyst|quality\s*engineer|"
    r"sdet|"
    r"support|supports|supporting|"
    r"sap|abap|fiori|ui5|"
    r"shopify|"
    r"manual\s*testing|automation\s*test"
    r")\b",
    re.IGNORECASE,
)


def title_is_ignored(title: str) -> bool:
    return bool(_TITLE_IGNORE.search(title or ""))


def job_is_ignored(job: dict[str, Any]) -> bool:
    return title_is_ignored(str(job.get("title") or ""))


def filter_ignored_titles(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [job for job in jobs if not job_is_ignored(job)]


def filter_fresh(
    jobs: list[dict[str, Any]],
    *,
    minutes: int,
    now_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Keep jobs whose createdDate (ms) is within the last N minutes."""
    if minutes <= 0:
        return list(jobs)
    cutoff = (now_ms if now_ms is not None else int(time.time() * 1000)) - (
        minutes * 60 * 1000
    )
    kept: list[dict[str, Any]] = []
    for job in jobs:
        try:
            created = int(job.get("createdDate") or 0)
        except (TypeError, ValueError):
            continue
        if created >= cutoff:
            kept.append(job)
    return kept


def experience_overlaps(
    job: dict[str, Any],
    *,
    years: list[int],
    keep_unknown: bool = True,
) -> bool:
    """
    True if job YOE band overlaps any requested year.

    When min/max are missing, keep_unknown decides whether to keep the row.
    """
    if not years:
        return True
    raw_min = job.get("yearsExperienceMin")
    raw_max = job.get("yearsExperienceMax")
    if raw_min is None and raw_max is None:
        return keep_unknown
    try:
        min_y = int(raw_min) if raw_min is not None else 0
        max_y = int(raw_max) if raw_max is not None else 99
    except (TypeError, ValueError):
        return keep_unknown
    if max_y < min_y:
        max_y = min_y
    return any(min_y <= year <= max_y for year in years)


def filter_jobs(
    jobs: list[dict[str, Any]],
    *,
    fresh_minutes: int | None = None,
    experience_years: list[int] | None = None,
    keep_unknown_experience: bool = True,
) -> list[dict[str, Any]]:
    result = filter_ignored_titles(jobs)
    if experience_years:
        result = [
            job
            for job in result
            if experience_overlaps(
                job,
                years=experience_years,
                keep_unknown=keep_unknown_experience,
            )
        ]
    if fresh_minutes is not None:
        result = filter_fresh(result, minutes=fresh_minutes)
    return result

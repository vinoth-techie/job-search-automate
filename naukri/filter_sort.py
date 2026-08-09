"""Dedupe, freshness filter, and sort helpers."""

from __future__ import annotations

import time
from typing import Any


def dedupe_by_job_id(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first occurrence of each jobId."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for job in jobs:
        job_id = job.get("jobId")
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        unique.append(job)
    return unique


def filter_by_freshness(
    jobs: list[dict[str, Any]],
    minutes: int,
    *,
    now_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Keep jobs whose createdDate is within the last `minutes`."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    cutoff = now_ms - (minutes * 60 * 1000)
    return [job for job in jobs if int(job.get("createdDate") or 0) >= cutoff]


def sort_by_created_date_desc(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Newest createdDate first."""
    return sorted(jobs, key=lambda job: int(job.get("createdDate") or 0), reverse=True)


def process_jobs(
    jobs: list[dict[str, Any]],
    *,
    fresh_minutes: int | None = None,
) -> list[dict[str, Any]]:
    """Dedupe, optional freshness filter, then sort newest first."""
    result = dedupe_by_job_id(jobs)
    if fresh_minutes is not None:
        result = filter_by_freshness(result, fresh_minutes)
    return sort_by_created_date_desc(result)


def dedupe_across_experience_keys(
    jobs_by_experience: dict[str, list[dict[str, Any]]],
    experience_keys: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """
    Ensure each jobId appears under only one experience key.

    Keys are processed in order (e.g. 3 then 4); the first key that has the
    job keeps it, later keys drop that jobId.
    """
    seen: set[str] = set()
    result: dict[str, list[dict[str, Any]]] = {}

    for key in experience_keys:
        kept: list[dict[str, Any]] = []
        for job in jobs_by_experience.get(key) or []:
            job_id = str(job.get("jobId") or "")
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            kept.append(job)
        result[key] = kept

    return result

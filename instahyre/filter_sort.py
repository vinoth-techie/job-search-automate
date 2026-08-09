"""Dedupe and sort helpers."""

from __future__ import annotations

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


def sort_by_job_id_desc(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Newest-looking ids first (Instahyre has no createdDate on search)."""

    def key(job: dict[str, Any]) -> int:
        try:
            return int(job.get("jobId") or 0)
        except (TypeError, ValueError):
            return 0

    return sorted(jobs, key=key, reverse=True)


def process_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe then sort."""
    return sort_by_job_id_desc(dedupe_by_job_id(jobs))


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

"""Dedupe and sort helpers."""

from __future__ import annotations

from typing import Any


def dedupe_by_job_id(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for job in jobs:
        job_id = job.get("jobId")
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        unique.append(job)
    return unique


def sort_by_created_desc(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(job: dict[str, Any]) -> tuple[int, int]:
        try:
            created = int(job.get("createdDate") or 0)
        except (TypeError, ValueError):
            created = 0
        try:
            job_id = int(job.get("jobId") or 0)
        except (TypeError, ValueError):
            job_id = 0
        return (created, job_id)

    return sorted(jobs, key=key, reverse=True)


def process_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sort_by_created_desc(dedupe_by_job_id(jobs))

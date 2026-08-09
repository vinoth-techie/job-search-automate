"""Terminal and JSON output for extracted Instahyre jobs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from instahyre.locations import (
    TARGET_CITIES,
    count_jobs_by_experience,
    group_by_experience_city_company,
)

JOB_FIELDS = [
    "jobId",
    "title",
    "company",
    "experience",
    "location",
    "salary",
    "posted",
    "createdDate",
    "skills",
    "url",
]

SEPARATOR = "-" * 50


def format_job_block(job: dict[str, Any]) -> str:
    return "\n".join(
        [
            SEPARATOR,
            f"Title: {job.get('title', '')}",
            f"Company: {job.get('company', '')}",
            f"Experience: {job.get('experience', '') or '(via years filter)'}",
            f"Location: {job.get('location', '')}",
            f"Salary: {job.get('salary', '') or 'Not disclosed'}",
            f"Posted: {job.get('posted', '') or 'n/a'}",
            f"URL: {job.get('url', '')}",
            SEPARATOR,
        ]
    )


def _job_row_for_json(job: dict[str, Any]) -> dict[str, Any]:
    return {field: job.get(field, "") for field in JOB_FIELDS}


def print_jobs_by_experience_city_company(
    grouped: dict[str, dict[str, dict[str, list[dict[str, Any]]]]],
) -> None:
    total = 0
    for exp_key, by_city in grouped.items():
        exp_count = sum(
            len(jobs)
            for companies in by_city.values()
            for jobs in companies.values()
        )
        total += exp_count
        print(f"\n########## years={exp_key} ({exp_count}) ##########")
        for city in TARGET_CITIES:
            companies = by_city.get(city) or {}
            city_count = sum(len(jobs) for jobs in companies.values())
            print(f"\n===== {city} ({city_count}) =====")
            if not companies:
                print("(none)")
                continue
            for company, jobs in companies.items():
                print(f"\n--- {company} ({len(jobs)}) ---")
                for job in jobs:
                    print(format_job_block(job))
    print(f"\nTotal jobs (years/city/company): {total}")


def write_jobs_json(
    jobs_by_experience: dict[str, list[dict[str, Any]]],
    path: str | Path = "instahyre_jobs.json",
    *,
    experience_keys: list[str] | None = None,
) -> Path:
    json_path = Path(path)
    grouped = group_by_experience_city_company(
        jobs_by_experience,
        experience_keys=experience_keys,
    )
    payload: dict[str, Any] = {}
    for exp_key, by_city in grouped.items():
        payload[exp_key] = {
            city: {
                company: [_job_row_for_json(job) for job in company_jobs]
                for company, company_jobs in (by_city.get(city) or {}).items()
            }
            for city in TARGET_CITIES
        }

    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return json_path


# Re-export for callers that print counts
__all__ = [
    "format_job_block",
    "print_jobs_by_experience_city_company",
    "write_jobs_json",
    "count_jobs_by_experience",
]

"""Terminal and JSON output for extracted jobs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from naukri.locations import (
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

IST = ZoneInfo("Asia/Kolkata")
SEPARATOR = "-" * 50


def created_date_to_ist(created_ms: Any) -> str:
    """Convert epoch milliseconds to IST string, e.g. '2026-08-09 12:21:58 IST'."""
    try:
        ms = int(created_ms or 0)
    except (TypeError, ValueError):
        return ""
    if ms <= 0:
        return ""
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(IST)
    return dt.strftime("%Y-%m-%d %H:%M:%S IST")


def format_job_block(job: dict[str, Any]) -> str:
    return "\n".join(
        [
            SEPARATOR,
            f"Title: {job.get('title', '')}",
            f"Company: {job.get('company', '')}",
            f"Experience: {job.get('experience', '')}",
            f"Location: {job.get('location', '')}",
            f"Salary: {job.get('salary', '')}",
            f"Posted: {job.get('posted', '')}",
            f"Created: {created_date_to_ist(job.get('createdDate'))}",
            f"Skills: {job.get('skills', '') or 'n/a'}",
            f"URL: {job.get('url', '')}",
            SEPARATOR,
        ]
    )


def _job_row_for_json(job: dict[str, Any]) -> dict[str, Any]:
    row = {field: job.get(field, "") for field in JOB_FIELDS}
    row["createdDate"] = created_date_to_ist(job.get("createdDate"))
    return row


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
        print(f"\n########## experience={exp_key} ({exp_count}) ##########")
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
    print(f"\nTotal jobs (experience/city/company): {total}")


def write_jobs_json(
    jobs_by_experience: dict[str, list[dict[str, Any]]],
    path: str | Path | None = None,
    *,
    experience_keys: list[str] | None = None,
) -> Path:
    """
    Write jobs JSON grouped as:

    {
      "3": {
        "Bengaluru": { "Company A": [ ... ] },
        "Chennai": { ... }
      },
      "4": { ... }
    }
    """
    json_path = Path(path) if path is not None else Path(__file__).resolve().parents[1] / "output" / "naukri" / "jobs.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
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

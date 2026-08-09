"""Extract and normalize job fields from Instahyre job_search objects."""

from __future__ import annotations

from typing import Any


def _skills_label(keywords: Any) -> str:
    if not isinstance(keywords, list):
        return ""
    parts = [str(item).strip() for item in keywords if str(item).strip()]
    return ",".join(parts)


def extract_job(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Map one raw Instahyre object to a normalized job dict."""
    job_id = obj.get("id")
    if job_id is None:
        return None

    employer = obj.get("employer") if isinstance(obj.get("employer"), dict) else {}
    company = str(employer.get("company_name") or "")

    return {
        "jobId": str(job_id),
        "title": str(obj.get("title") or obj.get("candidate_title") or ""),
        "company": company,
        "skills": _skills_label(obj.get("keywords")),
        "experience": "",  # Instahyre search is filtered by years=; no per-job band
        "location": str(obj.get("locations") or ""),
        "salary": "",  # Not present on job_search objects
        "createdDate": 0,  # Not present on job_search objects
        "posted": "",
        "url": str(obj.get("public_url") or ""),
    }


def extract_jobs_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalized jobs from a /api/v1/job_search JSON payload."""
    objects = payload.get("objects")
    if not isinstance(objects, list):
        return []

    jobs: list[dict[str, Any]] = []
    for item in objects:
        if not isinstance(item, dict):
            continue
        normalized = extract_job(item)
        if normalized:
            jobs.append(normalized)
    return jobs

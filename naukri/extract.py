"""Extract and normalize job fields from Naukri jobDetails payloads."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

NAUKRI_ORIGIN = "https://www.naukri.com"


def _placeholder_label(placeholders: list[dict[str, Any]] | None, ptype: str) -> str:
    if not placeholders:
        return ""
    for item in placeholders:
        if item.get("type") == ptype:
            return str(item.get("label") or "")
    return ""


def _experience_label(job: dict[str, Any]) -> str:
    label = _placeholder_label(job.get("placeholders"), "experience")
    if label:
        return label
    minimum = job.get("minimumExperience")
    maximum = job.get("maximumExperience")
    if minimum is not None and maximum is not None:
        return f"{minimum}-{maximum} Yrs"
    if minimum is not None:
        return f"{minimum}+ Yrs"
    return ""


def _full_jd_url(jd_url: str | None) -> str:
    if not jd_url:
        return ""
    if jd_url.startswith("http://") or jd_url.startswith("https://"):
        return jd_url
    return urljoin(NAUKRI_ORIGIN, jd_url)


def extract_job(job: dict[str, Any]) -> dict[str, Any] | None:
    """Map one raw jobDetails item to a normalized job dict."""
    job_id = job.get("jobId")
    if not job_id:
        return None

    created = job.get("createdDate")
    try:
        created_date = int(created) if created is not None else 0
    except (TypeError, ValueError):
        created_date = 0

    return {
        "jobId": str(job_id),
        "title": str(job.get("title") or ""),
        "company": str(job.get("companyName") or ""),
        "skills": str(job.get("tagsAndSkills") or ""),
        "experience": _experience_label(job),
        "location": _placeholder_label(job.get("placeholders"), "location"),
        "salary": _placeholder_label(job.get("placeholders"), "salary"),
        "createdDate": created_date,
        "posted": str(job.get("footerPlaceholderLabel") or ""),
        "url": _full_jd_url(job.get("jdURL")),
    }


def extract_jobs_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalized jobs from a /jobapi/v3/search JSON payload."""
    details = payload.get("jobDetails")
    if not isinstance(details, list):
        return []

    jobs: list[dict[str, Any]] = []
    for item in details:
        if not isinstance(item, dict):
            continue
        normalized = extract_job(item)
        if normalized:
            jobs.append(normalized)
    return jobs

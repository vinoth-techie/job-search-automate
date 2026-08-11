"""Extract and normalize job fields from Hirist /job/category/ data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

JOB_URL_TEMPLATE = "https://www.hirist.tech/j/{job_id}"


def _skills_label(tags: Any) -> str:
    if not isinstance(tags, list):
        return ""
    parts: list[str] = []
    for item in tags:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item).strip()
        if name:
            parts.append(name)
    return ",".join(parts)


def _location_label(job: dict[str, Any]) -> str:
    locs = job.get("locations") or job.get("location") or []
    if not isinstance(locs, list):
        return ""
    names: list[str] = []
    for item in locs:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if name:
                names.append(name)
    return ",".join(names)


def _salary_label(job: dict[str, Any]) -> str:
    try:
        hide = int(job.get("hideSal") or 0)
    except (TypeError, ValueError):
        hide = 1
    if hide:
        return ""
    try:
        min_sal = int(job.get("minSal") or 0)
        max_sal = int(job.get("maxSal") or 0)
    except (TypeError, ValueError):
        return ""
    if min_sal <= 0 and max_sal <= 0:
        return ""
    if min_sal > 0 and max_sal > 0:
        return f"{min_sal}-{max_sal} LPA"
    if max_sal > 0:
        return f"up to {max_sal} LPA"
    return f"{min_sal}+ LPA"


def _created_ms(job: dict[str, Any]) -> int:
    for key in ("createdTimeMs", "createdTime"):
        raw = job.get(key)
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        # 0/negative createdTimeMs must not block a valid createdTime fallback.
        if value <= 0:
            continue
        # Hirist sometimes stores seconds; normalize to ms.
        if value < 10_000_000_000:
            value *= 1000
        return value
    return 0


def _posted_label(created_ms: int) -> str:
    """Date-only label in IST (matches Naukri-style local day)."""
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


def _experience_label(job: dict[str, Any]) -> str:
    try:
        min_exp = int(job.get("min") or 0)
        max_exp = int(job.get("max") or 0)
    except (TypeError, ValueError):
        return ""
    if min_exp <= 0 and max_exp <= 0:
        return ""
    if min_exp > 0 and max_exp > 0:
        return f"{min_exp}-{max_exp} yrs"
    if max_exp > 0:
        return f"0-{max_exp} yrs"
    return f"{min_exp}+ yrs"


def extract_job(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Map one raw Hirist row to a normalized job dict."""
    job_id = obj.get("id")
    if job_id is None:
        return None

    company_data = (
        obj.get("companyData") if isinstance(obj.get("companyData"), dict) else {}
    )
    company = str(company_data.get("companyName") or "")
    created_ms = _created_ms(obj)

    return {
        "jobId": str(job_id),
        "title": str(obj.get("title") or ""),
        "company": company,
        "skills": _skills_label(obj.get("tags")),
        "experience": _experience_label(obj),
        "location": _location_label(obj),
        "salary": _salary_label(obj),
        "createdDate": created_ms,
        "posted": _posted_label(created_ms),
        "url": JOB_URL_TEMPLATE.format(job_id=job_id),
    }


def extract_jobs_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalized jobs from a /job/category/ JSON payload."""
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []

    jobs: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        normalized = extract_job(item)
        if normalized:
            jobs.append(normalized)
    return jobs

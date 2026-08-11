"""Group / filter jobs by target cities and company."""

from __future__ import annotations

from typing import Any

# Canonical city -> substrings that appear in Wellfound locationNames
CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "Bengaluru": ("bengaluru", "bangalore", "bengalooru"),
    "Chennai": ("chennai", "madras"),
    "Hyderabad": ("hyderabad", "secunderabad"),
    "Coimbatore": ("coimbatore", "kovai"),
}

TARGET_CITIES = tuple(CITY_ALIASES.keys())


def matching_cities(location: str) -> list[str]:
    """Return target cities mentioned in a location string (stable order)."""
    text = (location or "").lower()
    matched: list[str] = []
    for city, aliases in CITY_ALIASES.items():
        if any(alias in text for alias in aliases):
            matched.append(city)
    return matched


def _company_key(job: dict[str, Any]) -> str:
    name = str(job.get("company") or "").strip()
    return name or "Unknown"


def group_by_city(
    jobs: list[dict[str, Any]],
    *,
    cities: tuple[str, ...] = TARGET_CITIES,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {city: [] for city in cities}
    seen_in_city: dict[str, set[str]] = {city: set() for city in cities}

    for job in jobs:
        for city in matching_cities(str(job.get("location") or "")):
            if city not in grouped:
                continue
            job_id = str(job.get("jobId") or "")
            if job_id and job_id in seen_in_city[city]:
                continue
            if job_id:
                seen_in_city[city].add(job_id)
            grouped[city].append(job)

    return grouped


def group_by_city_and_company(
    jobs: list[dict[str, Any]],
    *,
    cities: tuple[str, ...] = TARGET_CITIES,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    by_city = group_by_city(jobs, cities=cities)
    nested: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for city in cities:
        companies: dict[str, list[dict[str, Any]]] = {}
        for job in by_city.get(city) or []:
            company = _company_key(job)
            companies.setdefault(company, []).append(job)
        nested[city] = {name: companies[name] for name in sorted(companies)}

    return nested


def count_jobs_grouped(
    grouped: dict[str, dict[str, list[dict[str, Any]]]],
) -> int:
    return sum(
        len(jobs)
        for companies in grouped.values()
        for jobs in companies.values()
    )


def group_by_experience_city_company(
    jobs_by_experience: dict[str, list[dict[str, Any]]],
    *,
    experience_keys: list[str] | None = None,
    cities: tuple[str, ...] = TARGET_CITIES,
) -> dict[str, dict[str, dict[str, list[dict[str, Any]]]]]:
    keys = experience_keys or list(jobs_by_experience.keys())
    return {
        key: group_by_city_and_company(
            jobs_by_experience.get(key) or [], cities=cities
        )
        for key in keys
    }


def count_jobs_by_experience(
    grouped: dict[str, dict[str, dict[str, list[dict[str, Any]]]]],
) -> int:
    return sum(count_jobs_grouped(by_city) for by_city in grouped.values())

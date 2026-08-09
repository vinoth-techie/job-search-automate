"""Local filters: experience band and salary threshold."""

from __future__ import annotations

import re
from typing import Any


_EXP_RANGE = re.compile(
    r"(?P<min>\d+(?:\.\d+)?)\s*[-–to]+\s*(?P<max>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_EXP_PLUS = re.compile(r"(?P<min>\d+(?:\.\d+)?)\s*\+", re.IGNORECASE)
_EXP_SINGLE = re.compile(r"(?P<min>\d+(?:\.\d+)?)\s*(?:yrs?|years?)?", re.IGNORECASE)

_SALARY_RANGE = re.compile(
    r"(?P<min>\d+(?:\.\d+)?)\s*[-–]\s*(?P<max>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>lacs?|lakhs?|cr|crore)",
    re.IGNORECASE,
)
_SALARY_SINGLE = re.compile(
    r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>lacs?|lakhs?|cr|crore)",
    re.IGNORECASE,
)

# Ignore QA / SAP / support-style roles even if skills mention java/react/etc.
_TITLE_IGNORE = re.compile(
    r"\b("
    r"test|tests|tester|testers|testing|tested|"
    r"qa|q\.?a\.?|"
    r"quality\s*assurance|quality\s*analyst|quality\s*engineer|"
    r"sdet|"
    r"support|supports|supporting|"
    r"sap|abap|fiori|ui5|"
    r"manual\s*testing|automation\s*test"
    r")\b",
    re.IGNORECASE,
)

# Extra skill/title tokens for common Naukri URL slugs
_SLUG_ALIASES: dict[str, tuple[str, ...]] = {
    "react-dot-js": ("react", "react.js", "reactjs", "react js"),
    "java-script": ("javascript", "java script", "js"),
    "data-structure": (
        "data structure",
        "data structures",
        "datastructure",
        "dsa",
    ),
    "postgresql": ("postgresql", "postgres", "psql"),
    "microservices": ("microservice", "microservices", "micro services"),
    "code-review": ("code review", "code-review", "codereview"),
    # Broad "software *" phrases must hit TITLE (see _TITLE_REQUIRED_KEYWORDS)
    "software-engineering": (
        "software engineer",
        "software engineering",
        "sde",
    ),
    "software-development": (
        "software developer",
        "software development",
        "software development engineer",
        "sde",
    ),
    "software-solutions": ("software solutions", "software solution"),
    "aws": ("aws", "amazon web services"),
    "git": ("git", "github", "gitlab"),
    "debugging": ("debug", "debugging"),
    "spring-boot": ("spring boot", "springboot", "spring-boot"),
}

# Standalone tokens too broad to match (e.g. "development" → SAP ABAP Development)
_GENERIC_PARTS = frozenset(
    {
        "dot",
        "js",
        "development",
        "developer",
        "develop",
        "engineering",
        "engineer",
        "solutions",
        "solution",
        "structure",
        "structures",
        "data",
        "review",
        "code",
        "script",
        "software",
        "jobs",
        "service",
        "services",
    }
)


def title_is_ignored(title: str) -> bool:
    """True if title contains test or support (case-insensitive whole words)."""
    return bool(_TITLE_IGNORE.search(title or ""))


def filter_ignored_titles(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [job for job in jobs if not title_is_ignored(str(job.get("title") or ""))]


def keywords_from_listing_slug(slug: str | None) -> list[str]:
    """Build skill-match tokens from a listing slug like 'react-dot-js'."""
    if not slug:
        return []

    slug = slug.lower().strip("-")
    keywords: list[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        token = token.strip().lower()
        # Skip 1-letter noise (e.g. bare "c" matching Embedded C)
        if not token or len(token) < 2 or token in _GENERIC_PARTS:
            return
        if token not in seen:
            seen.add(token)
            keywords.append(token)

    # Prefer curated aliases for known slugs (avoids generic leftovers)
    if slug in _SLUG_ALIASES:
        for alias in _SLUG_ALIASES[slug]:
            add(alias)
        # Also keep the human phrase form, e.g. "software development"
        phrase = slug.replace("-dot-", ".").replace("-", " ")
        if phrase not in _GENERIC_PARTS:
            add(phrase)
        return keywords

    dotted = slug.replace("-dot-", ".")
    add(dotted)
    add(dotted.replace(".", " "))
    add(dotted.replace(".", ""))
    add(slug.replace("-", " "))

    for part in slug.split("-"):
        if part in _GENERIC_PARTS:
            continue
        if len(part) >= 2:
            add(part)

    return keywords


def _haystack_has_keyword(haystack: str, kw: str) -> bool:
    if any(ch in kw for ch in ".-"):
        return kw in haystack
    if " " in kw:
        # Phrase match with non-letter boundaries so
        # "software engineering" in skills does not alone approve SAP roles
        # when we require title match for broad phrases — handled by caller.
        return kw in haystack
    return bool(
        re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", haystack)
    )


# Broad phrases that appear as generic skill tags on unrelated jobs
_TITLE_REQUIRED_KEYWORDS = frozenset(
    {
        "software engineering",
        "software engineer",
        "software development",
        "software developer",
        "software develop",
        "software development engineer",
        "software solutions",
        "software solution",
    }
)


def job_matches_keywords(job: dict[str, Any], keywords: list[str]) -> bool:
    """
    True if skills or title contains at least one keyword.

    Broad phrases like "software engineering" must appear in the TITLE
    (skills-only tags are too noisy on SAP/embedded/etc.).
    No keywords => reject.
    """
    if not keywords:
        return False

    title = str(job.get("title") or "").lower()
    skills = str(job.get("skills") or "").lower()
    combined = f"{skills} {title}".strip()
    if not combined:
        return False

    for keyword in keywords:
        kw = keyword.lower().strip()
        if not kw or len(kw) < 2 or kw in _GENERIC_PARTS:
            continue
        if kw in _TITLE_REQUIRED_KEYWORDS:
            if _haystack_has_keyword(title, kw):
                return True
            continue
        if _haystack_has_keyword(combined, kw):
            return True
    return False


def filter_by_keywords(
    jobs: list[dict[str, Any]],
    keywords: list[str],
) -> list[dict[str, Any]]:
    return [job for job in jobs if job_matches_keywords(job, keywords)]


def parse_experience_years(experience: str) -> tuple[float | None, float | None]:
    """Return (min_years, max_years) from labels like '3-4 Yrs' or '3+ Yrs'."""
    text = (experience or "").strip()
    if not text:
        return None, None

    match = _EXP_RANGE.search(text)
    if match:
        return float(match.group("min")), float(match.group("max"))

    match = _EXP_PLUS.search(text)
    if match:
        return float(match.group("min")), None

    match = _EXP_SINGLE.search(text)
    if match:
        value = float(match.group("min"))
        return value, value
    return None, None


def _to_lpa(amount: float, unit: str) -> float:
    unit = unit.lower()
    if unit.startswith("cr") or unit.startswith("crore"):
        return amount * 100.0  # 1 Cr = 100 LPA
    return amount  # Lacs / Lakhs


def parse_salary_lpa(salary: str) -> tuple[float | None, float | None]:
    """
    Return (min_lpa, max_lpa).

    'Not disclosed' / empty → (None, None)
    '12-16 Lacs PA' → (12, 16)
    '1-5 Cr' → (100, 500)
    """
    text = (salary or "").strip()
    if not text or "not disclosed" in text.lower():
        return None, None

    match = _SALARY_RANGE.search(text)
    if match:
        unit = match.group("unit")
        return (
            _to_lpa(float(match.group("min")), unit),
            _to_lpa(float(match.group("max")), unit),
        )

    match = _SALARY_SINGLE.search(text)
    if match:
        value = _to_lpa(float(match.group("amount")), match.group("unit"))
        return value, value
    return None, None


def is_salary_disclosed(salary: str) -> bool:
    min_lpa, max_lpa = parse_salary_lpa(salary)
    return min_lpa is not None or max_lpa is not None


def matches_experience(
    job: dict[str, Any],
    *,
    want_min: float = 3,
    want_max: float = 4,
) -> bool:
    """True if job experience range overlaps [want_min, want_max] (default 3–4 yrs)."""
    job_min, job_max = parse_experience_years(str(job.get("experience") or ""))
    if job_min is None and job_max is None:
        return False
    if job_min is None:
        job_min = 0.0
    if job_max is None:
        job_max = job_min
    # Ranges overlap if job_min <= want_max and job_max >= want_min
    return job_min <= want_max and job_max >= want_min


def matches_salary_above(
    job: dict[str, Any],
    *,
    min_lpa: float = 10,
) -> bool:
    """True if disclosed salary max (or single) is >= min_lpa."""
    low, high = parse_salary_lpa(str(job.get("salary") or ""))
    if low is None and high is None:
        return False
    top = high if high is not None else low
    assert top is not None
    return top >= min_lpa


def split_by_criteria(
    jobs: list[dict[str, Any]],
    *,
    exp_min: float = 3,
    exp_max: float = 4,
    min_salary_lpa: float = 10,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Returns (matched, no_salary).

    matched: experience overlaps 3–4 yrs AND salary disclosed AND >= min_salary_lpa
    no_salary: experience overlaps 3–4 yrs AND salary not disclosed
    (jobs failing experience are dropped)
    """
    matched: list[dict[str, Any]] = []
    no_salary: list[dict[str, Any]] = []

    for job in jobs:
        if title_is_ignored(str(job.get("title") or "")):
            continue
        if not matches_experience(job, want_min=exp_min, want_max=exp_max):
            continue
        if not is_salary_disclosed(str(job.get("salary") or "")):
            no_salary.append(job)
            continue
        if matches_salary_above(job, min_lpa=min_salary_lpa):
            matched.append(job)

    return matched, no_salary

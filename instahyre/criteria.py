"""Local filters: ignored titles and skill/title keyword match."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


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


def title_is_ignored(title: str) -> bool:
    return bool(_TITLE_IGNORE.search(title or ""))


def filter_ignored_titles(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [job for job in jobs if not title_is_ignored(str(job.get("title") or ""))]


def slug_from_naukri_url(url: str) -> str | None:
    path = urlparse(url).path.strip("/")
    if not path:
        return None
    slug = path.split("/")[-1].lower()
    slug = re.sub(r"-jobs(?:-in-.*)?$", "", slug)
    slug = slug.strip("-")
    return slug or None


def keywords_from_listing_slug(slug: str | None) -> list[str]:
    if not slug:
        return []

    slug = slug.lower().strip("-")
    keywords: list[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        token = token.strip().lower()
        if not token or len(token) < 2 or token in _GENERIC_PARTS:
            return
        if token not in seen:
            seen.add(token)
            keywords.append(token)

    if slug in _SLUG_ALIASES:
        for alias in _SLUG_ALIASES[slug]:
            add(alias)
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


def interest_keywords_from_urls(urls: list[str]) -> list[str]:
    """Build a union of skill tokens from Naukri-style listing URLs."""
    seen: set[str] = set()
    keywords: list[str] = []
    for url in urls:
        for token in keywords_from_listing_slug(slug_from_naukri_url(url)):
            if token not in seen:
                seen.add(token)
                keywords.append(token)
    return keywords


def _haystack_has_keyword(haystack: str, kw: str) -> bool:
    if any(ch in kw for ch in ".-"):
        return kw in haystack
    if " " in kw:
        return kw in haystack
    return bool(
        re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", haystack)
    )


def job_matches_keywords(job: dict[str, Any], keywords: list[str]) -> bool:
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


def filter_jobs(
    jobs: list[dict[str, Any]],
    *,
    keywords: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Drop ignored titles; optionally require interest-keyword match."""
    result = filter_ignored_titles(jobs)
    if keywords:
        result = filter_by_keywords(result, keywords)
    return result

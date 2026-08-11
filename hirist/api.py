"""Fetch Hirist gladiator job search with page pagination.

Supports:
- /job/keyword/  (skill pages like /k/python-jobs → keywordId)
- /job/category/ (broad category fallback)
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from hirist.locations import HIRIST_LOC_IDS

API_ORIGIN = "https://gladiator.hirist.tech"
KEYWORD_PATH = "/job/keyword/"
CATEGORY_PATH = "/job/category/"
SITE_ORIGIN = "https://www.hirist.tech"
DEFAULT_SIZE = 20
DEFAULT_MAX_PAGES = 50
DEFAULT_PAGE_DELAY_SECONDS = 1.5
DEFAULT_MAX_RETRIES = 6
DEFAULT_CATEGORY_ID = 1  # Software / tech category on homepage

DEFAULT_LOC = ",".join(str(HIRIST_LOC_IDS[c]) for c in HIRIST_LOC_IDS)

# Naukri listing slugs → Hirist /k/{slug} pages (only when names differ).
NAUKRI_SLUG_TO_HIRIST: dict[str, str] = {
    "react-dot-js": "reactjs-jobs",
    "java-script": "javascript-jobs",
    "node-js": "nodejs-jobs",
    "spring-boot": "spring-boot-jobs",
    "microservices": "microservices-architecture-jobs",
}

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


@dataclass(frozen=True)
class ExperienceRange:
    """minexp/maxexp filter pair, keyed as 'min-max'."""

    minexp: int
    maxexp: int

    @property
    def key(self) -> str:
        return f"{self.minexp}-{self.maxexp}"


@dataclass(frozen=True)
class KeywordRef:
    """Resolved Hirist skill tag used by /job/keyword/."""

    keyword_id: int
    title: str
    slug: str


@dataclass
class SearchBatch:
    """Jobs captured for one experience range (optionally across keywords)."""

    experience_key: str
    payloads: list[dict[str, Any]] = field(default_factory=list)
    total_jobs: int = 0


def parse_experience_ranges(raw: str) -> list[ExperienceRange]:
    """Parse '2-3,3-4' into ExperienceRange list."""
    ranges: list[ExperienceRange] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" not in part:
            raise ValueError(
                f"invalid experience range {part!r}; expected min-max like 2-3"
            )
        left, right = part.split("-", 1)
        minexp = int(left.strip())
        maxexp = int(right.strip())
        if minexp < 0 or maxexp < minexp:
            raise ValueError(f"invalid experience range {part!r}")
        ranges.append(ExperienceRange(minexp=minexp, maxexp=maxexp))
    if not ranges:
        raise ValueError("at least one experience range is required")
    return ranges


def hirist_slug_from_token(token: str) -> str:
    """Normalize a skill token / Naukri slug into a Hirist /k/ slug."""
    raw = (token or "").strip().lower()
    raw = raw.split("?")[0].strip("/")
    if "/" in raw:
        raw = raw.rstrip("/").split("/")[-1]
    raw = re.sub(r"\.html$", "", raw)
    if raw in NAUKRI_SLUG_TO_HIRIST:
        return NAUKRI_SLUG_TO_HIRIST[raw]
    if raw.endswith("-jobs"):
        base = raw[: -len("-jobs")]
        if base in NAUKRI_SLUG_TO_HIRIST:
            return NAUKRI_SLUG_TO_HIRIST[base]
        return raw
    if raw in NAUKRI_SLUG_TO_HIRIST:
        return NAUKRI_SLUG_TO_HIRIST[raw]
    return f"{raw}-jobs"


def slug_from_hirist_url(url: str) -> str | None:
    path = urllib.parse.urlparse(url).path.strip("/")
    if not path.startswith("k/"):
        return None
    slug = path.split("/", 1)[1].strip("/")
    return slug or None


def resolve_keyword(
    slug_or_token: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> KeywordRef | None:
    """Resolve /k/{slug} (or skill token) to keywordId via page __NEXT_DATA__."""
    slug = hirist_slug_from_token(slug_or_token)
    page_url = f"{SITE_ORIGIN}/k/{slug}"
    last_error: Exception | None = None

    for attempt in range(max_retries):
        req = urllib.request.Request(
            page_url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                html = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in {429, 500, 502, 503, 504} and attempt + 1 < max_retries:
                wait = min(60.0, (2**attempt) * 2.0)
                print(
                    f"  resolve {slug}: HTTP {exc.code}; "
                    f"retry in {wait:.1f}s ({attempt + 1}/{max_retries})"
                )
                time.sleep(wait)
                continue
            return None
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt + 1 < max_retries:
                wait = min(20.0, (2**attempt) * 1.0)
                print(
                    f"  resolve {slug}: network error; "
                    f"retry in {wait:.1f}s ({attempt + 1}/{max_retries})"
                )
                time.sleep(wait)
                continue
            return None

        match = _NEXT_DATA_RE.search(html)
        if not match:
            last_error = RuntimeError("missing __NEXT_DATA__")
            if attempt + 1 < max_retries:
                wait = min(10.0, (2**attempt) * 1.0)
                time.sleep(wait)
                continue
            return None
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            last_error = exc
            if attempt + 1 < max_retries:
                wait = min(10.0, (2**attempt) * 1.0)
                time.sleep(wait)
                continue
            return None

        page_props = (
            payload.get("props", {}).get("pageProps", {})
            if isinstance(payload, dict)
            else {}
        )
        if not isinstance(page_props, dict):
            return None

        raw_id = page_props.get("tagId")
        title = str(page_props.get("tagTitle") or slug).strip()
        try:
            keyword_id = int(str(raw_id).strip())
        except (TypeError, ValueError):
            return None
        if keyword_id <= 0:
            return None
        return KeywordRef(keyword_id=keyword_id, title=title, slug=slug)

    if last_error is not None:
        return None
    return None


def resolve_keywords(tokens: list[str]) -> list[KeywordRef]:
    """Resolve unique skill tokens; skip unknowns."""
    seen_ids: set[int] = set()
    resolved: list[KeywordRef] = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        ref = resolve_keyword(token)
        if ref is None:
            print(f"  skip unresolved Hirist skill: {token}")
            continue
        if ref.keyword_id in seen_ids:
            continue
        seen_ids.add(ref.keyword_id)
        resolved.append(ref)
        print(f"  skill {ref.title!r} → keywordId={ref.keyword_id} (/k/{ref.slug})")
        time.sleep(0.4)
    return resolved


def build_category_url(
    *,
    minexp: int,
    maxexp: int,
    page: int = 0,
    size: int = DEFAULT_SIZE,
    loc: str = DEFAULT_LOC,
    category_id: int = DEFAULT_CATEGORY_ID,
    posting: int | None = None,
) -> str:
    params: dict[str, str] = {
        "minexp": str(minexp),
        "maxexp": str(maxexp),
        "page": str(page),
        "concat": "false",
        "catOrTagId": str(category_id),
        "loc": loc,
        "categoryId": str(category_id),
        "size": str(size),
        "ref": "homepagecat",
        "referenceText": "homepagecat",
    }
    if posting is not None:
        params["posting"] = str(posting)
    return f"{API_ORIGIN}{CATEGORY_PATH}?{urllib.parse.urlencode(params)}"


def build_keyword_url(
    *,
    keyword: KeywordRef,
    minexp: int,
    maxexp: int,
    page: int = 0,
    size: int = DEFAULT_SIZE,
    loc: str = DEFAULT_LOC,
    posting: int | None = None,
) -> str:
    params: dict[str, str] = {
        "minexp": str(minexp),
        "maxexp": str(maxexp),
        "query": str(keyword.keyword_id),
        "page": str(page),
        "loc": loc,
        "industry": "",
        "keywordId": str(keyword.keyword_id),
        "size": str(size),
        "ref": "topnavigation",
        "referenceText": "topnavigation",
    }
    if posting is not None:
        params["posting"] = str(posting)
    return f"{API_ORIGIN}{KEYWORD_PATH}?{urllib.parse.urlencode(params)}"


def _request_json(
    url: str,
    *,
    referer: str | None = None,
    timeout: int = 30,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(max_retries):
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": referer or f"{SITE_ORIGIN}/",
                "Origin": SITE_ORIGIN,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(
                f"Hirist HTTP {exc.code} for {url}: {body[:200]}"
            )
            if exc.code in {429, 500, 502, 503, 504} and attempt + 1 < max_retries:
                wait = min(60.0, (2**attempt) * 2.0)
                print(
                    f"  rate-limited/HTTP {exc.code}; "
                    f"retry in {wait:.1f}s ({attempt + 1}/{max_retries})"
                )
                time.sleep(wait)
                continue
            raise last_error from exc
        except urllib.error.URLError as exc:
            last_error = RuntimeError(f"Hirist request failed for {url}: {exc}")
            if attempt + 1 < max_retries:
                wait = min(20.0, (2**attempt) * 1.0)
                time.sleep(wait)
                continue
            raise last_error from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            last_error = RuntimeError(f"Hirist returned non-JSON for {url}")
            if attempt + 1 < max_retries:
                wait = min(20.0, (2**attempt) * 1.0)
                print(
                    f"  non-JSON response; "
                    f"retry in {wait:.1f}s ({attempt + 1}/{max_retries})"
                )
                time.sleep(wait)
                continue
            raise last_error from exc

        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise RuntimeError(f"Unexpected Hirist payload shape for {url}")
        return data

    assert last_error is not None
    raise last_error


def _job_ids(payload: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in payload.get("data") or []:
        if isinstance(item, dict) and item.get("id") is not None:
            ids.add(str(item["id"]))
    return ids


def _paginate(
    *,
    label: str,
    build_url,
    referer: str,
    max_pages: int,
    page_delay_seconds: float,
) -> tuple[list[dict[str, Any]], int]:
    payloads: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    total_jobs = 0
    hit_max_pages = False

    for page_index in range(max_pages):
        if page_index > 0 and page_delay_seconds > 0:
            time.sleep(page_delay_seconds)

        url = build_url(page_index)
        payload = _request_json(url, referer=referer)
        rows = payload.get("data") or []
        if page_index == 0:
            try:
                total_jobs = int(payload.get("totalJobs") or 0)
            except (TypeError, ValueError):
                total_jobs = 0
            print(
                f"[{label}] {url}\n"
                f"  first page: {len(rows)} jobs "
                f"(totalJobs={total_jobs}, "
                f"totalPages={payload.get('totalPages')})"
            )

        if not rows:
            break

        new_ids = _job_ids(payload)
        if not new_ids or new_ids.issubset(seen_ids):
            print(
                f"  warning: pagination stopped early at page={page_index} "
                f"(duplicate/empty; unique={len(seen_ids)})"
            )
            break

        seen_ids.update(new_ids)
        payloads.append(payload)

        if page_index > 0:
            print(
                f"  fetched page={page_index} ({len(rows)} jobs, "
                f"unique={len(seen_ids)})"
            )

        if not payload.get("hasMore"):
            break

        if page_index + 1 >= max_pages:
            hit_max_pages = True

    if hit_max_pages:
        print(
            f"  warning: hit max_pages={max_pages} for {label}; "
            f"fetched {len(seen_ids)}"
            f"{f'/{total_jobs}' if total_jobs else ''} unique jobs. "
            "Raise --max-pages if results look incomplete."
        )

    return payloads, total_jobs


def fetch_keyword_pages(
    *,
    keyword: KeywordRef,
    experience: ExperienceRange,
    max_pages: int = DEFAULT_MAX_PAGES,
    size: int = DEFAULT_SIZE,
    loc: str = DEFAULT_LOC,
    posting: int | None = None,
    page_delay_seconds: float = DEFAULT_PAGE_DELAY_SECONDS,
) -> SearchBatch:
    label = f"{experience.key}/{keyword.title}"
    referer = f"{SITE_ORIGIN}/k/{keyword.slug}"

    def build_url(page: int) -> str:
        return build_keyword_url(
            keyword=keyword,
            minexp=experience.minexp,
            maxexp=experience.maxexp,
            page=page,
            size=size,
            loc=loc,
            posting=posting,
        )

    payloads, total_jobs = _paginate(
        label=label,
        build_url=build_url,
        referer=referer,
        max_pages=max_pages,
        page_delay_seconds=page_delay_seconds,
    )
    return SearchBatch(
        experience_key=experience.key,
        payloads=payloads,
        total_jobs=total_jobs,
    )


def fetch_category_pages(
    *,
    experience: ExperienceRange,
    max_pages: int = DEFAULT_MAX_PAGES,
    size: int = DEFAULT_SIZE,
    loc: str = DEFAULT_LOC,
    posting: int | None = None,
    page_delay_seconds: float = DEFAULT_PAGE_DELAY_SECONDS,
) -> SearchBatch:
    label = experience.key

    def build_url(page: int) -> str:
        return build_category_url(
            minexp=experience.minexp,
            maxexp=experience.maxexp,
            page=page,
            size=size,
            loc=loc,
            posting=posting,
        )

    payloads, total_jobs = _paginate(
        label=label,
        build_url=build_url,
        referer=f"{SITE_ORIGIN}/",
        max_pages=max_pages,
        page_delay_seconds=page_delay_seconds,
    )
    return SearchBatch(
        experience_key=experience.key,
        payloads=payloads,
        total_jobs=total_jobs,
    )


def collect_search_batches(
    *,
    experience_ranges: list[ExperienceRange] | None = None,
    keywords: list[KeywordRef] | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    size: int = DEFAULT_SIZE,
    loc: str = DEFAULT_LOC,
    posting: int | None = None,
    page_delay_seconds: float = DEFAULT_PAGE_DELAY_SECONDS,
) -> list[SearchBatch]:
    ranges = experience_ranges or [
        ExperienceRange(2, 3),
        ExperienceRange(3, 4),
    ]
    batches: list[SearchBatch] = []

    for exp_index, experience in enumerate(ranges):
        if exp_index > 0 and page_delay_seconds > 0:
            time.sleep(page_delay_seconds * 2)

        if keywords:
            payloads: list[dict[str, Any]] = []
            total = 0
            for kw_index, keyword in enumerate(keywords):
                if kw_index > 0 and page_delay_seconds > 0:
                    time.sleep(page_delay_seconds)
                part = fetch_keyword_pages(
                    keyword=keyword,
                    experience=experience,
                    max_pages=max_pages,
                    size=size,
                    loc=loc,
                    posting=posting,
                    page_delay_seconds=page_delay_seconds,
                )
                payloads.extend(part.payloads)
                total += part.total_jobs
            batches.append(
                SearchBatch(
                    experience_key=experience.key,
                    payloads=payloads,
                    total_jobs=total,
                )
            )
        else:
            batches.append(
                fetch_category_pages(
                    experience=experience,
                    max_pages=max_pages,
                    size=size,
                    loc=loc,
                    posting=posting,
                    page_delay_seconds=page_delay_seconds,
                )
            )
    return batches

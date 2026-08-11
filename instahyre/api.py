"""Fetch Instahyre /api/v1/job_search with offset pagination."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

API_ORIGIN = "https://www.instahyre.com"
SEARCH_PATH = "/api/v1/job_search"
DEFAULT_LIMIT = 20
DEFAULT_MAX_PAGES = 50
# ~3s/page keeps Cloudflare happier; full years=3,4 run is ~4–5 minutes.
DEFAULT_PAGE_DELAY_SECONDS = 3.0
DEFAULT_MAX_RETRIES = 6

DEFAULT_PARAMS = {
    "company_size": "0",
    "isLandingPage": "true",
    "job_type": "1",
    "source": "opportunities",
}


@dataclass
class SearchBatch:
    """Jobs captured for one years= value."""

    years: str
    payloads: list[dict[str, Any]] = field(default_factory=list)
    total_count: int = 0


def build_search_url(
    *,
    years: int,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    extra_params: dict[str, str] | None = None,
) -> str:
    params = dict(DEFAULT_PARAMS)
    if extra_params:
        params.update(extra_params)
    params["years"] = str(years)
    params["offset"] = str(offset)
    params["limit"] = str(limit)
    query = urllib.parse.urlencode(params)
    return f"{API_ORIGIN}{SEARCH_PATH}?{query}"


def _request_json(
    url: str,
    *,
    timeout: int = 30,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(max_retries):
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": f"{API_ORIGIN}/candidate/opportunities/",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(
                f"Instahyre HTTP {exc.code} for {url}: {body[:200]}"
            )
            if exc.code in {429, 500, 502, 503, 504} and attempt + 1 < max_retries:
                wait = min(60.0, (2**attempt) * 3.0)
                print(
                    f"  rate-limited/HTTP {exc.code}; "
                    f"retry in {wait:.1f}s ({attempt + 1}/{max_retries})"
                )
                time.sleep(wait)
                continue
            raise last_error from exc
        except urllib.error.URLError as exc:
            last_error = RuntimeError(
                f"Instahyre request failed for {url}: {exc}"
            )
            if attempt + 1 < max_retries:
                wait = min(20.0, (2**attempt) * 1.0)
                time.sleep(wait)
                continue
            raise last_error from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            last_error = RuntimeError(f"Instahyre returned non-JSON for {url}")
            if attempt + 1 < max_retries:
                wait = min(20.0, (2**attempt) * 1.5)
                print(
                    f"  non-JSON response; "
                    f"retry in {wait:.1f}s ({attempt + 1}/{max_retries})"
                )
                time.sleep(wait)
                continue
            raise last_error from exc

        if not isinstance(data, dict) or not isinstance(data.get("objects"), list):
            raise RuntimeError(f"Unexpected Instahyre payload shape for {url}")
        return data

    assert last_error is not None
    raise last_error


def _job_ids(payload: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in payload.get("objects") or []:
        if isinstance(item, dict) and item.get("id") is not None:
            ids.add(str(item["id"]))
    return ids


def fetch_search_pages(
    *,
    years: int,
    max_pages: int = DEFAULT_MAX_PAGES,
    limit: int = DEFAULT_LIMIT,
    page_delay_seconds: float = DEFAULT_PAGE_DELAY_SECONDS,
) -> SearchBatch:
    """
    Fetch job_search pages for a given years= filter.

    Pagination uses offset += limit until meta.next is null, objects empty,
    duplicate ids, or max_pages reached.
    """
    payloads: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    total_count = 0
    offset = 0
    stopped_early = False
    hit_max_pages = False

    for page_index in range(max_pages):
        if page_index > 0 and page_delay_seconds > 0:
            time.sleep(page_delay_seconds)

        url = build_search_url(years=years, offset=offset, limit=limit)
        payload = _request_json(url)
        objects = payload.get("objects") or []
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        if page_index == 0:
            try:
                total_count = int(meta.get("total_count") or 0)
            except (TypeError, ValueError):
                total_count = 0
            print(
                f"[years={years}] {url}\n"
                f"  first page: {len(objects)} jobs "
                f"(total_count={total_count})"
            )

        if not objects:
            break

        new_ids = _job_ids(payload)
        if not new_ids or new_ids.issubset(seen_ids):
            stopped_early = True
            print(
                f"  warning: pagination stopped early at offset={offset} "
                f"(duplicate/empty page; unique={len(seen_ids)}"
                f"{f', total_count={total_count}' if total_count else ''})"
            )
            break

        seen_ids.update(new_ids)
        payloads.append(payload)

        if page_index > 0:
            print(
                f"  fetched offset={offset} ({len(objects)} jobs, "
                f"unique={len(seen_ids)})"
            )

        next_path = meta.get("next")
        if not next_path:
            break

        # Prefer meta.next offset if present; else step by limit
        try:
            next_query = urllib.parse.parse_qs(
                urllib.parse.urlparse(str(next_path)).query
            )
            offset = int((next_query.get("offset") or [str(offset + limit)])[0])
        except (TypeError, ValueError):
            offset += limit

        if page_index + 1 >= max_pages:
            hit_max_pages = True

    if hit_max_pages:
        print(
            f"  warning: hit max_pages={max_pages} for years={years}; "
            f"fetched {len(seen_ids)}"
            f"{f'/{total_count}' if total_count else ''} unique jobs. "
            "Raise --max-pages if results look incomplete."
        )
    elif (
        not stopped_early
        and total_count > 0
        and len(seen_ids) < total_count
    ):
        print(
            f"  warning: fetched {len(seen_ids)}/{total_count} unique jobs "
            f"for years={years}; feed may be incomplete."
        )

    return SearchBatch(
        years=str(years),
        payloads=payloads,
        total_count=total_count,
    )


def collect_search_batches(
    *,
    experience_years: list[int] | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    limit: int = DEFAULT_LIMIT,
    page_delay_seconds: float = DEFAULT_PAGE_DELAY_SECONDS,
) -> list[SearchBatch]:
    years = experience_years if experience_years is not None else [3, 4]
    batches: list[SearchBatch] = []
    for index, year in enumerate(years):
        if index > 0 and page_delay_seconds > 0:
            time.sleep(page_delay_seconds * 2)
        batches.append(
            fetch_search_pages(
                years=year,
                max_pages=max_pages,
                limit=limit,
                page_delay_seconds=page_delay_seconds,
            )
        )
    return batches

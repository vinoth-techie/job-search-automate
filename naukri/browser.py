"""Playwright session: open listing page, capture /jobapi/v3/search, paginate."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.sync_api import BrowserContext, Page, Response, sync_playwright

SEARCH_API_MARKER = "/jobapi/v3/search"
DEFAULT_STORAGE = "naukri_storage.json"
DEFAULT_WAIT_SECONDS = 180
DEFAULT_MAX_PAGES = 50


@dataclass
class CapturedSearchRequest:
    url: str
    method: str
    headers: dict[str, str] = field(default_factory=dict)
    post_data: str | None = None


@dataclass
class CaptureResult:
    payloads: list[dict[str, Any]]
    request_template: CapturedSearchRequest | None


@dataclass
class SearchBatch:
    """One listing URL captured at one experience= value."""

    listing_url: str
    experience: str
    payloads: list[dict[str, Any]] = field(default_factory=list)


def _is_search_api_url(url: str) -> bool:
    return SEARCH_API_MARKER in url


def expected_keyword_from_listing_url(listing_url: str) -> str | None:
    """
    Derive the search keyword from a Naukri listing page URL.

    Examples:
      .../python-jobs?... -> python
      .../python-jobs-in-hyderabad -> python
      .../java-developer-jobs -> java-developer
    """
    path = urlparse(listing_url).path.strip("/")
    if not path:
        return None
    slug = path.split("/")[-1].lower()
    slug = re.sub(r"-jobs(?:-in-.*)?$", "", slug)
    slug = slug.strip("-")
    return slug or None


def _query_params(url: str) -> dict[str, str]:
    return {
        key.lower(): value
        for key, value in parse_qsl(urlparse(url).query, keep_blank_values=True)
    }


def _api_matches_listing(api_url: str, listing_url: str) -> bool:
    """
    Accept only the listing search API, not unrelated /jobapi/v3/search feeds.

    Naukri often fires multiple search calls (recommended/fresh jobs). Taking the
    first one caused Civil/Angular jobs to appear for a python-jobs URL.
    """
    expected = expected_keyword_from_listing_url(listing_url)
    if not expected:
        return True

    params = _query_params(api_url)
    keyword = (params.get("keyword") or params.get("k") or "").lower().replace(" ", "-")
    seo_key = (params.get("seokey") or "").lower()

    expected_compact = expected.replace(" ", "-")
    if keyword and (
        keyword == expected_compact
        or expected_compact in keyword
        or keyword in expected_compact
    ):
        return True
    if seo_key and expected_compact in seo_key:
        return True
    return False


def _safe_json(response: Response) -> dict[str, Any] | None:
    try:
        data = response.json()
    except Exception:
        try:
            text = response.text()
            data = json.loads(text)
        except Exception:
            return None
    if isinstance(data, dict) and isinstance(data.get("jobDetails"), list):
        return data
    return None


def _headers_for_replay(raw_headers: dict[str, str]) -> dict[str, str]:
    """Keep useful request headers; drop hop-by-hop / browser-managed ones."""
    skip = {
        "host",
        "content-length",
        "connection",
        "cookie",
        "accept-encoding",
    }
    headers: dict[str, str] = {}
    for key, value in raw_headers.items():
        if key.lower() in skip:
            continue
        headers[key] = value
    return headers


def _with_page_no(url: str, page_no: int) -> str:
    parsed = urlparse(url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    updated: list[tuple[str, str]] = []
    replaced = False
    for key, value in pairs:
        if key == "pageNo":
            if not replaced:
                updated.append((key, str(page_no)))
                replaced = True
            # Drop duplicate pageNo keys; keep a single updated value.
            continue
        updated.append((key, value))
    if not replaced:
        updated.append(("pageNo", str(page_no)))
    return urlunparse(parsed._replace(query=urlencode(updated, doseq=True)))


def _job_ids_from_payload(payload: dict[str, Any]) -> set[str]:
    details = payload.get("jobDetails") or []
    ids: set[str] = set()
    for item in details:
        if isinstance(item, dict) and item.get("jobId") is not None:
            ids.add(str(item["jobId"]))
    return ids


def _attach_search_listener(
    page: Page,
    listing_url: str,
) -> tuple[list[dict[str, Any]], list[CapturedSearchRequest | None], Any]:
    """Attach response listener before navigation; return shared capture state."""
    payloads: list[dict[str, Any]] = []
    template_box: list[CapturedSearchRequest | None] = [None]
    ignored = 0

    def on_response(response: Response) -> None:
        nonlocal ignored
        if not _is_search_api_url(response.url):
            return
        if response.status != 200:
            return
        if not _api_matches_listing(response.url, listing_url):
            ignored += 1
            print(f"Ignoring unrelated search API: {response.url[:120]}...")
            return
        payload = _safe_json(response)
        if payload is None:
            return
        payloads.append(payload)
        if template_box[0] is None:
            request = response.request
            template_box[0] = CapturedSearchRequest(
                url=request.url,
                method=request.method,
                headers=_headers_for_replay(request.headers),
                post_data=request.post_data,
            )

    page.on("response", on_response)
    return payloads, template_box, on_response


def wait_for_search_capture(
    page: Page,
    payloads: list[dict[str, Any]],
    template_box: list[CapturedSearchRequest | None],
    on_response: Any,
    *,
    listing_url: str,
    timeout_seconds: int = DEFAULT_WAIT_SECONDS,
) -> CaptureResult:
    """Wait until the listing-matching /jobapi/v3/search has been captured."""
    expected = expected_keyword_from_listing_url(listing_url)
    deadline = time.time() + timeout_seconds
    print(
        "Waiting for Naukri /jobapi/v3/search response"
        + (f" matching keyword/seoKey ~ '{expected}'" if expected else "")
        + "...\n"
        "If login or CAPTCHA appears, complete it in the browser window."
    )
    while time.time() < deadline:
        if payloads and template_box[0] is not None:
            break
        page.wait_for_timeout(250)

    page.remove_listener("response", on_response)

    if not payloads or template_box[0] is None:
        hint = (
            f" matching keyword '{expected}'" if expected else ""
        )
        raise TimeoutError(
            f"Timed out after {timeout_seconds}s waiting for "
            f"{SEARCH_API_MARKER}{hint} with jobDetails. "
            "Log in or reload the listing page in the open browser and retry."
        )

    return CaptureResult(payloads=payloads, request_template=template_box[0])


def fetch_search_page(
    context: BrowserContext,
    template: CapturedSearchRequest,
    page_no: int,
) -> dict[str, Any] | None:
    """Replay the captured search request with a different pageNo."""
    url = _with_page_no(template.url, page_no)
    method = (template.method or "GET").upper()
    response = context.request.fetch(
        url,
        method=method,
        headers=template.headers,
        data=template.post_data,
    )
    if response.status != 200:
        return None
    try:
        data = response.json()
    except Exception:
        return None
    if isinstance(data, dict) and isinstance(data.get("jobDetails"), list):
        return data
    return None


def paginate_search(
    context: BrowserContext,
    template: CapturedSearchRequest,
    first_payload: dict[str, Any],
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> list[dict[str, Any]]:
    """Collect page 1 payload plus subsequent pages by incrementing pageNo."""
    payloads = [first_payload]
    seen_ids = _job_ids_from_payload(first_payload)

    # Determine starting page from the captured URL (usually 1).
    query = dict(parse_qsl(urlparse(template.url).query, keep_blank_values=True))
    try:
        start_page = int(query.get("pageNo") or "1")
    except ValueError:
        start_page = 1

    for page_no in range(start_page + 1, start_page + max_pages):
        payload = fetch_search_page(context, template, page_no)
        if payload is None:
            break
        details = payload.get("jobDetails") or []
        if not details:
            break
        new_ids = _job_ids_from_payload(payload)
        if not new_ids or new_ids.issubset(seen_ids):
            break
        seen_ids.update(new_ids)
        payloads.append(payload)
        print(f"Fetched page {page_no} ({len(details)} jobs)")

    return payloads


def with_experience(listing_url: str, years: int) -> str:
    """Return listing URL with experience=<years> (replaces existing experience)."""
    parsed = urlparse(listing_url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    updated: list[tuple[str, str]] = []
    replaced = False
    for key, value in pairs:
        if key == "experience":
            if not replaced:
                updated.append((key, str(years)))
                replaced = True
            continue
        updated.append((key, value))
    if not replaced:
        updated.append(("experience", str(years)))
    return urlunparse(parsed._replace(query=urlencode(updated, doseq=True)))


def _capture_one_listing(
    page: Page,
    context: BrowserContext,
    listing_url: str,
    *,
    wait_seconds: int,
    max_pages: int,
    paginate: bool,
) -> list[dict[str, Any]]:
    payloads_buf, template_box, on_response = _attach_search_listener(
        page, listing_url
    )
    print(f"Opening {listing_url}")
    page.goto(listing_url, wait_until="domcontentloaded")
    capture = wait_for_search_capture(
        page,
        payloads_buf,
        template_box,
        on_response,
        listing_url=listing_url,
        timeout_seconds=wait_seconds,
    )
    assert capture.request_template is not None

    first = capture.payloads[0]
    print(f"Captured search API: {capture.request_template.url}")
    print(f"First page jobs: {len(first.get('jobDetails') or [])}")

    if paginate:
        return paginate_search(
            context,
            capture.request_template,
            first,
            max_pages=max_pages,
        )
    return [first]


def collect_search_batches(
    listing_urls: str | list[str],
    *,
    storage_path: str | Path = DEFAULT_STORAGE,
    wait_seconds: int = DEFAULT_WAIT_SECONDS,
    max_pages: int = DEFAULT_MAX_PAGES,
    paginate: bool = True,
    experience_years: list[int] | None = None,
) -> list[SearchBatch]:
    """
    Open listing URL(s) in a headed browser, capture /jobapi/v3/search.

    For each listing URL, runs each experience year (default 3 and 4),
    preserving other query params (jobAge, cityTypeGid, etc.).

    Returns one SearchBatch per (listing_url, experience) so callers can
    skill-filter using that listing's keyword.
    """
    if isinstance(listing_urls, str):
        urls_list = [listing_urls]
    else:
        urls_list = [url for url in listing_urls if url]

    if not urls_list:
        raise ValueError("at least one listing URL is required")

    years = experience_years if experience_years is not None else [3, 4]
    storage = Path(storage_path)
    storage_state = str(storage) if storage.exists() else None
    batches: list[SearchBatch] = []

    total = len(urls_list) * len(years)
    done = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(
            storage_state=storage_state,
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        try:
            for listing_url in urls_list:
                for year in years:
                    done += 1
                    key = str(year)
                    url = with_experience(listing_url, year)
                    print(
                        f"\n=== [{done}/{total}] experience={year} ===\n{url}"
                    )
                    payloads = _capture_one_listing(
                        page,
                        context,
                        url,
                        wait_seconds=wait_seconds,
                        max_pages=max_pages,
                        paginate=paginate,
                    )
                    batches.append(
                        SearchBatch(
                            listing_url=listing_url,
                            experience=key,
                            payloads=payloads,
                        )
                    )

            context.storage_state(path=str(storage))
            print(f"Saved browser session to {storage}")
            return batches
        finally:
            context.close()
            browser.close()


def collect_search_payloads(
    listing_urls: str | list[str],
    *,
    storage_path: str | Path = DEFAULT_STORAGE,
    wait_seconds: int = DEFAULT_WAIT_SECONDS,
    max_pages: int = DEFAULT_MAX_PAGES,
    paginate: bool = True,
    experience_years: list[int] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Compatibility helper: merge batches into experience -> payloads."""
    batches = collect_search_batches(
        listing_urls,
        storage_path=storage_path,
        wait_seconds=wait_seconds,
        max_pages=max_pages,
        paginate=paginate,
        experience_years=experience_years,
    )
    years = experience_years if experience_years is not None else [3, 4]
    by_experience: dict[str, list[dict[str, Any]]] = {str(y): [] for y in years}
    for batch in batches:
        by_experience.setdefault(batch.experience, []).extend(batch.payloads)
    return by_experience



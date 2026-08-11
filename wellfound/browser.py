"""Playwright session: open Wellfound SEO pages, wait out JS challenge, paginate."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.sync_api import Page, sync_playwright

from paths import portal_output_dir
from wellfound.extract import extract_jobs_from_html

DEFAULT_STORAGE = str(portal_output_dir("wellfound") / "storage.json")
DEFAULT_WAIT_SECONDS = 180
DEFAULT_MAX_PAGES = 50
DEFAULT_PAGE_DELAY_SECONDS = 5.0
DEFAULT_BUCKET = "all"

_ROLE_LOCATION_RE = re.compile(
    r"/role/l/(?P<role>[^/?#]+)/(?P<location>[^/?#]+)",
    re.IGNORECASE,
)


@dataclass
class ListingSeed:
    url: str
    role: str
    location: str


@dataclass
class SearchBatch:
    """Jobs collected for one role/location listing."""

    listing_url: str
    role: str
    location: str
    jobs: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def parse_role_location(url: str) -> tuple[str, str] | None:
    match = _ROLE_LOCATION_RE.search(urlparse(url).path)
    if not match:
        return None
    return match.group("role"), match.group("location")


def listing_url(role: str, location: str, *, page: int | None = None) -> str:
    base = f"https://wellfound.com/role/l/{role}/{location}"
    if page is None or page <= 1:
        return base
    return f"{base}?page={page}"


def with_page(url: str, page_no: int) -> str:
    parsed = urlparse(url)
    pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() != "page"
    ]
    if page_no > 1:
        pairs.append(("page", str(page_no)))
    query = urlencode(pairs)
    # Drop any existing page path segment noise; SEO uses query ?page=.
    return urlunparse(parsed._replace(query=query))


def seed_from_url(url: str) -> ListingSeed | None:
    parsed = parse_role_location(url)
    if not parsed:
        return None
    role, location = parsed
    return ListingSeed(url=listing_url(role, location), role=role, location=location)


def _page_blocked(page: Page) -> bool:
    try:
        text = page.locator("body").inner_text(timeout=2000)
    except Exception:
        text = ""
    lowered = (text or "").lower()
    if "access is temporarily restricted" in lowered or "unusual activity" in lowered:
        return True
    try:
        html_head = page.content()[:5000].lower()
    except Exception:
        html_head = ""
    return "captcha-delivery.com/interstitial" in html_head


def _has_apollo_jobs(html: str) -> bool:
    jobs, meta = extract_jobs_from_html(html)
    if jobs:
        return True
    # Empty result page still counts once pagination meta is present.
    return bool(meta.get("pageCount") is not None or meta.get("totalJobCount") is not None)


def wait_for_listing_html(
    page: Page,
    *,
    timeout_seconds: int = DEFAULT_WAIT_SECONDS,
) -> str:
    """
    Wait until SEO Apollo payload is present (after DataDome/Turnstile).

    If a hard block / CAPTCHA appears, leave the headed window open for the
    user to solve it before the timeout.
    """
    deadline = time.time() + timeout_seconds
    warned = False
    print(
        "Waiting for Wellfound __NEXT_DATA__ / Apollo job payload...\n"
        "If a CAPTCHA or 'Access is temporarily restricted' appears, "
        "solve it in the browser window."
    )
    while time.time() < deadline:
        try:
            html = page.content()
        except Exception:
            page.wait_for_timeout(500)
            continue

        if _has_apollo_jobs(html):
            return html

        if _page_blocked(page) and not warned:
            print(
                "Bot wall detected. Complete the challenge in the open browser; "
                "will keep waiting until timeout."
            )
            warned = True

        page.wait_for_timeout(500)

    raise TimeoutError(
        f"Timed out after {timeout_seconds}s waiting for Wellfound Apollo jobs. "
        "Solve CAPTCHA/login in the headed browser and retry."
    )


def _fetch_page_jobs(
    page: Page,
    url: str,
    *,
    wait_seconds: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    print(f"Opening {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=max(60_000, wait_seconds * 1000))
    html = wait_for_listing_html(page, timeout_seconds=wait_seconds)
    jobs, meta = extract_jobs_from_html(html)
    if not jobs and not meta:
        # Challenge/shell HTML — treat as wait failure for clearer retries.
        snippet = re.sub(r"\s+", " ", html[:240])
        raise RuntimeError(
            "Page loaded but Apollo job payload was missing "
            f"(title={page.title()!r}). Snippet: {snippet!r}"
        )
    print(
        f"  got {len(jobs)} jobs"
        + (
            f" (pageCount={meta.get('pageCount')}, "
            f"totalJobCount={meta.get('totalJobCount')})"
            if meta
            else ""
        )
    )
    return jobs, meta


def collect_listing(
    page: Page,
    seed: ListingSeed,
    *,
    wait_seconds: int = DEFAULT_WAIT_SECONDS,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_delay_seconds: float = DEFAULT_PAGE_DELAY_SECONDS,
) -> SearchBatch:
    """Paginate one role/location listing slowly."""
    all_jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    first_jobs, meta = _fetch_page_jobs(
        page, listing_url(seed.role, seed.location, page=1), wait_seconds=wait_seconds
    )
    for job in first_jobs:
        job_id = str(job.get("jobId") or "")
        if job_id and job_id not in seen:
            seen.add(job_id)
            all_jobs.append(job)

    try:
        page_count = int(meta.get("pageCount") or 1)
    except (TypeError, ValueError):
        page_count = 1
    page_count = max(1, min(page_count, max_pages))

    for page_no in range(2, page_count + 1):
        if page_delay_seconds > 0:
            print(f"  sleeping {page_delay_seconds}s before page {page_no}…")
            page.wait_for_timeout(int(page_delay_seconds * 1000))
        jobs, page_meta = _fetch_page_jobs(
            page,
            listing_url(seed.role, seed.location, page=page_no),
            wait_seconds=wait_seconds,
        )
        if page_meta:
            meta = {**meta, **page_meta}
        if not jobs:
            print(f"  page {page_no} empty — stopping pagination")
            break
        new = 0
        for job in jobs:
            job_id = str(job.get("jobId") or "")
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            all_jobs.append(job)
            new += 1
        if new == 0:
            print(f"  page {page_no} had no new jobIds — stopping")
            break

    return SearchBatch(
        listing_url=seed.url,
        role=seed.role,
        location=seed.location,
        jobs=all_jobs,
        meta=meta,
    )


def collect_search_batches(
    listing_urls: list[str],
    *,
    storage_path: str | Path = DEFAULT_STORAGE,
    wait_seconds: int = DEFAULT_WAIT_SECONDS,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_delay_seconds: float = DEFAULT_PAGE_DELAY_SECONDS,
    headless: bool = False,
) -> list[SearchBatch]:
    """
    Open each SEO listing in Chromium, clear JS challenge, paginate.

    Headed by default (same idea as Naukri) so CAPTCHA can be solved manually.
    """
    seeds: list[ListingSeed] = []
    for url in listing_urls:
        seed = seed_from_url(url)
        if seed is None:
            print(f"Skipping unrecognized Wellfound URL: {url}")
            continue
        seeds.append(seed)
    if not seeds:
        raise ValueError("no valid Wellfound /role/l/{role}/{location} URLs")

    storage = Path(storage_path)
    storage_state = str(storage) if storage.exists() else None
    batches: list[SearchBatch] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            storage_state=storage_state,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        try:
            for index, seed in enumerate(seeds, start=1):
                print(
                    f"\n=== [{index}/{len(seeds)}] {seed.role} / {seed.location} ==="
                )
                batch = collect_listing(
                    page,
                    seed,
                    wait_seconds=wait_seconds,
                    max_pages=max_pages,
                    page_delay_seconds=page_delay_seconds,
                )
                batches.append(batch)
                print(
                    f"Collected {len(batch.jobs)} unique jobs for "
                    f"{seed.role}/{seed.location}"
                )

            storage.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(storage))
            print(f"Saved browser session to {storage}")
            return batches
        finally:
            context.close()
            browser.close()

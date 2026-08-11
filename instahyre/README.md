# Instahyre

Fetch, filter, and group opportunity jobs from Instahyre’s public search API. Experience is applied via the API `years=` query (default `3` and `4`); results are filtered by ignored titles, optional skill keywords from Naukri URLs, and target cities, then written under `output/instahyre/`.

## Purpose / overview

The `instahyre` package is a CLI (`python -m instahyre`) that:

1. GETs `https://www.instahyre.com/api/v1/job_search` (opportunities feed).
2. Paginates with `offset` / `limit` until `meta.next` is empty (or stop conditions).
3. Normalizes each `objects[]` item into a flat job dict.
4. Drops test/QA/support/SAP-style titles; optionally keeps jobs whose title/skills match interest keywords derived from `naukri/urls.txt`.
5. Keeps jobs whose `location` matches Bengaluru, Chennai, Hyderabad, or Coimbatore.
6. Dedupes by `jobId` (prefer earlier `years=` key, e.g. `3` over `4`), sorts by `jobId` descending.
7. Groups as **years → city → company** and writes `jobs.json` plus a skills referral bank `skills.json`.

`--fresh` is **not** supported: search objects have no `createdDate`.

## Algorithm / end-to-end flow

```
CLI (--all)
  → parse years (default 3,4), load keywords from naukri/urls.txt
  → for each years value:
       HTTP GET /api/v1/job_search?years=N&offset=…&limit=20&…
       delay between pages; retry on 429/5xx and network errors
  → extract_jobs_from_payload (objects[])
  → filter_jobs (ignored titles + optional keywords)
  → keep only target cities
  → process_jobs (dedupe + sort by jobId desc)
  → dedupe_across_experience_keys (prefer first years key)
  → group years → city → company
  → write output/instahyre/jobs.json
  → rewrite output/instahyre/skills.json from kept jobs
```

### HTTP request

- **Method / URL:** `GET https://www.instahyre.com/api/v1/job_search`
- **Default query params** (`api.py`):

  | Param | Value |
  |-------|--------|
  | `company_size` | `0` |
  | `isLandingPage` | `true` |
  | `job_type` | `1` |
  | `source` | `opportunities` |
  | `years` | per batch (`3`, `4`, …) |
  | `offset` | pagination cursor |
  | `limit` | `20` |

- **Headers:** `Accept: application/json`, browser-like `User-Agent`, `Referer: https://www.instahyre.com/candidate/opportunities/`

### Pagination

For each `years` value (`fetch_search_pages`):

1. Start at `offset=0`.
2. After the first page, sleep `page_delay` seconds (default **3.0**).
3. Stop when any of:
   - `objects` is empty
   - page IDs are empty or a subset of already-seen IDs
   - `meta.next` is missing/null
   - `max_pages` reached (default **50**)
4. Next offset: prefer `offset` from `meta.next` query string; else `offset += limit`.

Between different `years` values, sleep `page_delay * 2`.

### Retries (`_request_json`)

- Up to **6** attempts.
- HTTP **429 / 502 / 503 / 504:** exponential backoff `min(60, 2^attempt * 3)` seconds.
- `URLError`: backoff `min(20, 2^attempt * 1)` seconds.
- Response must be JSON with an `objects` list.

### Post-fetch pipeline (per years batch, then globally)

1. Extract → normalize.
2. `filter_jobs` (titles + keywords).
3. City filter via `matching_cities(location)`.
4. `process_jobs`: dedupe by `jobId`, sort `jobId` desc.
5. Across years keys: `dedupe_across_experience_keys` — first key wins (default: keep under `3`, drop from `4`).
6. Group and write outputs; skills bank built only from jobs that survived all filters.

## API response shape

Top-level payload:

```json
{
  "objects": [ /* job objects */ ],
  "meta": {
    "next": "/api/v1/job_search?…&offset=20&…",
    "total_count": 1234
  }
}
```

- `objects[]` — page of jobs; required list (validated).
- `meta.next` — relative next URL or null/absent when done.
- `meta.total_count` — logged on first page; not used for stop logic beyond info.

### Job object fields used in extraction (`extract.py`)

| API field | Normalized field | Notes |
|-----------|------------------|--------|
| `id` | `jobId` | Required; object skipped if missing |
| `title` or `candidate_title` | `title` | Fallback chain |
| `employer.company_name` | `company` | `employer` must be a dict |
| `keywords` | `skills` | List → comma-joined string |
| `locations` | `location` | String as returned |
| `public_url` | `url` | |
| *(absent)* | `experience` | Always `""` (band comes from `years=` filter) |
| *(absent)* | `salary` | Always `""` |
| *(absent)* | `createdDate` | Always `0` |
| *(absent)* | `posted` | Always `""` |

## Extraction / normalization

`extract_job` maps one API object; `extract_jobs_from_payload` walks `objects[]` and skips non-dicts / missing `id`.

Skills: each non-empty keyword string is stripped and joined with `,` (no spaces after commas in the join).

**Missing on this endpoint:** per-job salary and `createdDate`. CLI and console notes reflect that; `--fresh MINUTES` exits with code `2` and tells you to use `--all`. Sort order uses numeric `jobId` descending as a stand-in for “newer”.

## Filters & criteria

### Ignored titles (`criteria.py`)

Regex (case-insensitive) drops titles matching word-boundary tokens such as: test/tester/testing, QA, quality assurance/analyst/engineer, SDET, support, SAP/ABAP/Fiori/UI5, manual testing, automation test.

### Interest keywords (optional)

- Default source: `naukri/urls.txt` (HTTP(S) URLs on non-comment lines).
- Slugs are parsed from URL paths; tokens expanded via aliases (e.g. `react-dot-js` → react / react.js / …).
- Generic parts (`engineer`, `jobs`, `software`, …) are dropped.
- Match haystack: lowercase `skills` + `title`.
- Most keywords match skills or title; a small set of “software engineer/developer/…” phrases must match **title** only.
- Disable with `--no-keyword-filter`, or `--urls-file ""`. If the file has no URLs, the run continues without a skill keyword filter.

### Cities

Keep job if `location` contains any alias for a target city (see [Target cities](#target-cities)).

### Deduping

- Within a list: first `jobId` wins, then sort by `jobId` descending.
- Across experience keys: process keys in CLI order; first key keeps the `jobId`.

## CLI

From the repo root (with deps installed):

```bash
python -m instahyre --all
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--all` | required* | Fetch all paginated jobs for each `years=` value |
| `--fresh MINUTES` | — | Unsupported; errors out |
| `--out` | `output/instahyre/jobs.json` | Jobs JSON path |
| `--experience-years` | `3,4` | Comma-separated `years=` values |
| `--max-pages` | `50` | Max pages per years value |
| `--page-delay` | `3.0` | Seconds between page requests |
| `--urls-file` | `naukri/urls.txt` | Naukri-style URLs for keywords; `""` disables |
| `--no-keyword-filter` | off | Skip skill keyword filter |
| `--skills-out` | `output/instahyre/skills.json` | Skills bank path |

\* Exactly one of `--all` or `--fresh` is required; `--fresh` always fails for this portal.

Example with options:

```bash
python -m instahyre --all --experience-years 3,4 --page-delay 3 --max-pages 50
```

## Output files

Directory: `output/instahyre/` (created if needed).

### `jobs.json`

Nested structure:

```text
{
  "<years>": {                 // e.g. "3", "4"
    "<city>": {                // Bengaluru, Chennai, Hyderabad, Coimbatore
      "<company>": [ { job fields… }, … ]
    }
  }
}
```

Each job row includes: `jobId`, `title`, `company`, `experience`, `location`, `salary`, `posted`, `createdDate`, `skills`, `url`.

### `skills.json`

Rewritten each successful run from **kept** jobs only (after title/keyword/city/dedupe):

```json
{
  "count": 279,
  "skills": {
    "Python": 149,
    "Java": 77
  }
}
```

- `skills`: skill name → how many jobs referred to that skill (at most once per job; case-insensitive merge, display name from first seen spelling).
- Ordered by count descending, then name.
- `count`: number of unique skills in the map.

## Target cities

Canonical names and location substrings (`locations.py`):

| City | Aliases matched in `location` |
|------|-------------------------------|
| Bengaluru | `bengaluru`, `bangalore`, `bengalooru` |
| Chennai | `chennai`, `madras` |
| Hyderabad | `hyderabad`, `secunderabad` |
| Coimbatore | `coimbatore`, `kovai` |

A job can appear under multiple cities if its `locations` string matches more than one (e.g. `Bangalore,Chennai,Pune`).

# Hirist job search

Fetch Hirist tech jobs via the public Gladiator API, filter them, and write grouped JSON under `output/hirist/`.

Package inputs live in `hirist/` (this module). Generated files go under `output/` via `paths.portal_output_dir("hirist")` → `output/hirist/`.

## Overview

```
python -m hirist --all
```

Default behavior:

1. Read skill pages from `hirist/urls.txt` (Hirist `/k/…-jobs` URLs, or Naukri-style slugs).
2. Resolve each slug to a Hirist `keywordId` from the skill page’s `__NEXT_DATA__` (`tagId`).
3. Call `https://gladiator.hirist.tech/job/keyword/` with experience, location, and optional `posting` filters; paginate with `page` / `hasMore`.
4. Normalize rows, drop ignored titles, optionally keep only fresh posts (`--fresh`), keep target cities only.
5. Dedupe by `jobId` within and across experience ranges (and across skills, since keyword results are merged per range).
6. Write `output/hirist/jobs.json` and rewrite `output/hirist/skills.json`.

Optional `--category` skips skill resolution and uses `/job/category/` (software/tech category) instead.

## Layout

| Role | Path |
|------|------|
| Skill URL list | `hirist/urls.txt` |
| Module code | `hirist/*.py` |
| Shared output helper | `paths.py` → `portal_output_dir("hirist")` |
| Jobs | `output/hirist/jobs.json` |
| Skills bank | `output/hirist/skills.json` |

```
output/
  hirist/
    jobs.json
    skills.json
```

## End-to-end flow

### 1. Skills from `urls.txt`

`hirist/urls.txt` lists Hirist skill pages, for example:

```text
https://www.hirist.tech/k/python-jobs?ref=topnavigation&minexp=2&maxexp=3&posting=3
```

- Lines starting with `#` are ignored.
- Query params on the first Hirist URL can override CLI defaults for experience (`minexp`/`maxexp`) and `posting` when those CLI flags are still at their defaults (`2-3`, `posting=3`).
- Tokens may also come from `--keywords python,java` or from Naukri listing URLs (mapped via `NAUKRI_SLUG_TO_HIRIST` / `hirist_slug_from_token`).

### 2. Slug → `keywordId`

For each skill token, `api.resolve_keyword`:

1. Normalizes to a `/k/{slug}` name (e.g. `python` → `python-jobs`).
2. GETs `https://www.hirist.tech/k/{slug}`.
3. Parses `<script id="__NEXT_DATA__">` and reads `props.pageProps.tagId` → `keywordId`, plus `tagTitle`.

`resolve_keywords` skips unresolved pages and **dedupes by `keywordId`**. So if two slugs resolve to the same tag (see [Node.js aliases](#nodejs-jobs-and-nodejs-jobs)), only one API search runs.

### 3. Gladiator keyword search

Per experience range × keyword:

```
GET https://gladiator.hirist.tech/job/keyword/
  ?minexp=&maxexp=
  &query={keywordId}
  &keywordId={keywordId}
  &page=0
  &loc=3,6,4,84
  &industry=
  &size=20
  &ref=topnavigation
  &referenceText=topnavigation
  &posting=3          # omitted when --posting 0
```

Pagination: start at `page=0`, follow while `data` has new job ids and `hasMore` is true (cap: `--max-pages`, default 50). Delay between pages: `--page-delay` (default 1.5s). Retries on 429/5xx.

### 4. Optional category mode

`--category` (or no resolvable skills) uses:

```
GET https://gladiator.hirist.tech/job/category/
  ?minexp=&maxexp=&page=&size=
  &catOrTagId=1&categoryId=1
  &loc=…
  &concat=false
  &ref=homepagecat
  &posting=…          # optional
```

Default `categoryId` is `1` (software/tech homepage category).

### 5. Local filters

Applied after extraction (`criteria.filter_jobs` + city check):

| Filter | Behavior |
|--------|----------|
| Ignored titles / skills | Drop QA/test/support/SAP/Shopify title matches; also drop any job whose skills list includes `Shopify` |
| `--fresh N` | Keep jobs with `createdDate` (epoch ms) within the last N minutes |
| Target cities | Keep only jobs whose location text matches Bengaluru / Chennai / Hyderabad / Coimbatore |
| `--local-keyword-filter` | Optional extra title/skills keyword match from Naukri-style slugs (usually unnecessary with `/job/keyword/`) |

API-side `loc=` already restricts search; the city step also groups and drops non-matching location strings.

### 6. Dedupe

- Within a range: `process_jobs` → unique `jobId`, newest `createdDate` first.
- Across skills in one range: keyword payloads are concatenated, then deduped by `jobId`.
- Across experience ranges: `dedupe_across_experience_keys` — each `jobId` kept under the **first** range that has it (earlier `--experience-ranges` wins).

Hirist `minexp`/`maxexp` is an overlap filter on job bands, so the same job can appear in multiple ranges until cross-range dedupe runs.

### 7. Output

- Terminal: exp → city → company blocks.
- `output/hirist/jobs.json`
- `output/hirist/skills.json` (rewritten from this run’s kept jobs)

## API response shape

Successful keyword/category responses are JSON objects with at least:

```json
{
  "data": [ /* job objects */ ],
  "totalJobs": 123,
  "hasMore": true,
  "page": 0,
  "totalPages": 7
}
```

Important fields on each job in `data`:

| Field | Use |
|-------|-----|
| `id` | Job id → `jobId`, URL |
| `title` | Title |
| `min` / `max` | Experience band (years) |
| `tags` | Skill tags (`[{ "name": "Python" }, …]`) |
| `locations` | Location objects with `name` |
| `companyData.companyName` | Company |
| `minSal` / `maxSal` / `hideSal` | Salary in LPA; empty if `hideSal` or both zeros |
| `createdTimeMs` (or `createdTime`) | Freshness / posted / created |

## Extraction

`extract.extract_job` maps one API row to:

| Field | Source |
|-------|--------|
| `jobId` | `id` (string) |
| `title` | `title` |
| `company` | `companyData.companyName` |
| `skills` | comma-joined `tags[].name` |
| `experience` | `{min}-{max} yrs` (variants for open ends) |
| `location` | comma-joined `locations[].name` |
| `salary` | `{minSal}-{maxSal} LPA` unless `hideSal` |
| `createdDate` | epoch **milliseconds** (seconds normalized ×1000) |
| `posted` | date-only IST `YYYY-MM-DD` from created time |
| `url` | `https://www.hirist.tech/j/{id}` |

When writing JSON, `output.write_jobs_json` converts `createdDate` to an IST timestamp string, e.g. `2026-08-07 17:28:26 IST`.

## Location IDs

Same target cities as Naukri. Passed as `loc=3,6,4,84` by default:

| City | Hirist `loc` id |
|------|-----------------|
| Bengaluru | 3 |
| Chennai | 6 |
| Hyderabad | 4 |
| Coimbatore | 84 |

City matching on job text also accepts aliases (e.g. Bangalore, Madras, Secunderabad, Kovai).

## CLI

Run from the repo root (package `hirist`):

```bash
# Defaults: urls.txt skills, exp 2-3, posting=3 days, target cities → output/hirist/jobs.json
python -m hirist --all

# Explicit skills + posting window
python -m hirist --all --keywords python,java --posting 3

# Only jobs created in the last 60 minutes
python -m hirist --fresh 60 --keywords python

# Multiple experience bands (dedupe prefers earlier keys)
python -m hirist --all --experience-ranges 2-3,3-4

# Broad category API instead of skill keywords
python -m hirist --all --category

# No posting age filter; custom output paths
python -m hirist --all --posting 0 --out output/hirist/jobs.json --skills-out output/hirist/skills.json

# Custom loc / pagination
python -m hirist --all --loc 3,6 --max-pages 10 --page-delay 2
```

`--all` and `--fresh` are mutually exclusive; one is required.

| Flag | Default | Notes |
|------|---------|--------|
| `--urls-file` | `hirist/urls.txt` | Empty string skips file |
| `--keywords` | (from urls) | Comma-separated skill tokens |
| `--experience-ranges` | `2-3` | `min-max` list |
| `--posting` | `3` | Days; `0` = omit posting filter |
| `--loc` | `3,6,4,84` | Hirist location ids |
| `--out` | `output/hirist/jobs.json` | |
| `--skills-out` | `output/hirist/skills.json` | |

## Output files

### `jobs.json`

Nested by experience key → city → company → jobs:

```json
{
  "2-3": {
    "Bengaluru": {
      "Some Company": [
        {
          "jobId": "1661560",
          "title": "…",
          "company": "…",
          "experience": "2-4 yrs",
          "location": "Bangalore",
          "salary": "10-12 LPA",
          "posted": "2026-08-07",
          "createdDate": "2026-08-07 17:28:26 IST",
          "skills": "Python,AWS,…",
          "url": "https://www.hirist.tech/j/1661560"
        }
      ]
    },
    "Chennai": {},
    "Hyderabad": {},
    "Coimbatore": {}
  }
}
```

Empty cities still appear as `{}`.

### `skills.json`

Rewritten each run from kept jobs. Counts how many jobs listed each skill (once per job):

```json
{
  "count": 89,
  "skills": {
    "Python": 12,
    "LLM": 6
  }
}
```

`skills` is ordered by descending count, then name.

## `nodejs-jobs` and `node.js-jobs`

`hirist/urls.txt` includes both:

- `/k/nodejs-jobs`
- `/k/node.js-jobs`

Those pages share the same Hirist `tagId` / `keywordId`. `resolve_keywords` keeps the first resolved id only, so both URLs do not double-fetch the same keyword search.

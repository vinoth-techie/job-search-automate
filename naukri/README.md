# Naukri job search

Capture Naukri listing searches via Playwright, normalize `/jobapi/v3/search` payloads, filter by local criteria, and write grouped JSON under `output/naukri/`.

Entry point: `main.py` at the repo root (`python main.py ...`).

## Purpose

- Open each URL from `naukri/urls.txt` (or `--url` / `--urls-file`) in a headed Chromium session.
- Capture the listing-matching `/jobapi/v3/search` response, then paginate by replaying that request with increasing `pageNo`.
- Run each URL with Naukri `experience=3` and `experience=4` (configurable).
- Filter jobs (title ignore, keyword from URL slug, experience overlap, salary, cities).
- Group results as **experience → city → company** and write `jobs.json`, `jobs_no_salary.json`, and `skills.json`. Persist browser login state in `storage.json`.

## End-to-end flow

1. **Load URLs** from `--url` (repeatable) or `--urls-file` (default `naukri/urls.txt`). Blank lines and `#` comments are skipped; multiple `http(s)` tokens on one line are accepted.
2. **Parse experience years** from `--experience-years` (default `3,4`). Each listing URL is opened once per year via `with_experience()` (sets/replaces the `experience` query param; other params like `jobAge`, `cityTypeGid` are kept).
3. **Playwright capture** (`naukri/browser.py`):
   - Launch headed Chromium; load `output/naukri/storage.json` if present.
   - Navigate to the listing URL and listen for responses containing `/jobapi/v3/search`.
   - Keep only responses whose `keyword` / `k` / `seoKey` matches the slug derived from the listing path (avoids unrelated “recommended” search calls).
   - Wait up to `--wait` seconds (default 180) for the first matching payload with `jobDetails`. Login/CAPTCHA can be completed in the open window.
4. **Pagination**: reuse the captured request template, bump `pageNo`, fetch until empty details, duplicate job IDs, non-200, or `--max-pages` (default 50).
5. **Extract** each payload’s `jobDetails` into normalized job dicts (`naukri/extract.py`).
6. **Keyword filter**: derive tokens from the listing URL slug (`expected_keyword_from_listing_url` → `keywords_from_listing_slug`); keep jobs whose skills/title match at least one keyword.
7. **Dedupe / freshness**: within the batch, dedupe by `jobId`, optionally keep only jobs with `createdDate` within `--fresh N` minutes (`--all` skips freshness).
8. **Criteria split** (`split_by_criteria`):
   - Drop ignored titles (test/QA/support/SAP, etc.).
   - Drop jobs whose experience range does not overlap `[--exp-min, --exp-max]` (default 3–4).
   - Disclosed salary ≥ `--min-salary` LPA (default 10) → **matched**.
   - Salary not disclosed → **no_salary**.
9. **Across batches**: merge into experience keys (`"3"`, `"4"`), dedupe again, then `dedupe_across_experience_keys` so each `jobId` appears under only one experience key (prefer earlier key, usually `3` over `4`).
10. **City / company grouping**: keep jobs whose `location` mentions a target city; nest as experience → city → company (companies A–Z). Multi-city listings appear under each matching city.
11. **Write outputs** under `output/naukri/` and update the skills bank from matched + no-salary jobs. Save Playwright `storage_state` to `storage.json`.

## Search API response shape

Captured JSON is a dict with a `jobDetails` array. Each item is mapped in `extract_job()`. Fields used:

| Raw (`jobDetails` item) | Used for |
|-------------------------|----------|
| `jobId` | Required id; skip if missing |
| `title` | Title |
| `companyName` | Company |
| `tagsAndSkills` | Comma-separated skills string |
| `placeholders[]` with `type == "experience"` / `"location"` / `"salary"` | Labels for experience, location, salary |
| `minimumExperience` / `maximumExperience` | Fallback experience label if no placeholder |
| `createdDate` | Epoch ms (freshness + sort) |
| `footerPlaceholderLabel` | Posted text (e.g. “1 Day Ago”) |
| `jdURL` | Job detail URL (absolutized against `https://www.naukri.com`) |

Unrelated top-level keys on the search payload are ignored; only `jobDetails` is read.

## Extraction / normalization

`extract_jobs_from_payload` → list of:

```text
jobId, title, company, skills, experience, location, salary,
createdDate (int ms), posted, url
```

- Experience label: placeholder `experience`, else `{min}-{max} Yrs` / `{min}+ Yrs`.
- Location / salary: placeholder labels only (empty if absent).
- URL: absolute `jdURL`.

JSON output additionally converts `createdDate` to IST strings via `output.py`.

## Filters and criteria

| Filter | Behavior |
|--------|----------|
| **Title ignore** | Drop if title matches whole-word patterns: test/tester/testing, QA, SDET, support, SAP/ABAP/Fiori/UI5, manual/automation test, etc. |
| **Keyword from slug** | Path segment like `python-jobs` → `python`; `react-dot-js-jobs` → aliases (`react`, `react.js`, …). At least one keyword must appear in skills or title. Broad “software engineer/development/…” phrases must appear in the **title**. No keywords → reject. Generic slug parts (`development`, `software`, …) are skipped as tokens. |
| **Experience overlap** | Parse labels like `3-4 Yrs`, `3+ Yrs`; keep if range overlaps `[exp_min, exp_max]` (default 3–4). |
| **Salary** | Parse Lacs/Lakhs/Cr; convert Cr → LPA × 100. Matched: disclosed and max (or single) ≥ `min_salary` LPA (default 10). No-salary bucket: experience OK, salary empty / “Not disclosed”. Below-threshold disclosed salaries are dropped. |
| **Freshness** | `--fresh N`: `createdDate >= now - N minutes`. `--all`: no freshness cut. |
| **Cities** | Location must mention a target city (alias substrings). Others discarded at grouping. |
| **jobId uniqueness** | Across experience keys, first key wins (prefer `3` over `4`). |

### Target cities

| City | Location aliases (substring) |
|------|------------------------------|
| Bengaluru | bengaluru, bangalore, bengalooru |
| Chennai | chennai, madras |
| Hyderabad | hyderabad, secunderabad |
| Coimbatore | coimbatore, kovai |

## CLI (from repo root)

Requires Playwright Chromium (`playwright install chromium`). Exactly one of `--fresh` or `--all` is required.

```bash
# All pages, default urls.txt, experience 3 and 4
python main.py --all

# Only jobs created in the last 60 minutes
python main.py --fresh 60

# Custom URLs / paths / thresholds
python main.py --all --url 'https://www.naukri.com/python-jobs?jobAge=1'
python main.py --all --urls-file naukri/urls.txt
python main.py --all --exp-min 3 --exp-max 4 --min-salary 10
python main.py --all --experience-years 3,4 --max-pages 50 --wait 180
python main.py --all --storage output/naukri/storage.json \
  --out output/naukri/jobs.json \
  --no-salary-out output/naukri/jobs_no_salary.json \
  --skills-out output/naukri/skills.json
```

| Flag | Default | Role |
|------|---------|------|
| `--url` | (none) | Listing URL; repeatable. If omitted, use `--urls-file`. |
| `--urls-file` | `naukri/urls.txt` | One URL per line |
| `--fresh MINUTES` / `--all` | (required, exclusive) | Freshness window vs keep all |
| `--storage` | `output/naukri/storage.json` | Playwright storage state |
| `--out` | `output/naukri/jobs.json` | Matched jobs |
| `--no-salary-out` | `output/naukri/jobs_no_salary.json` | Experience OK, salary undisclosed |
| `--exp-min` / `--exp-max` | `3` / `4` | Experience overlap band |
| `--min-salary` | `10` | Minimum disclosed salary (LPA) for matched |
| `--wait` | `180` | Seconds for first search API capture |
| `--max-pages` | `50` | Max search pages per (URL, experience) |
| `--experience-years` | `3,4` | Naukri `experience=` values → top-level JSON keys |
| `--skills-out` | `output/naukri/skills.json` | Skill referral counts |

## Output files (`output/naukri/`)

### `jobs.json` / `jobs_no_salary.json`

Same structure: experience → city → company → job arrays.

```json
{
  "3": {
    "Bengaluru": { "Company A": [ { "jobId": "...", "title": "...", ... } ] },
    "Chennai": {},
    "Hyderabad": {},
    "Coimbatore": {}
  },
  "4": { ... }
}
```

Each job row: `jobId`, `title`, `company`, `experience`, `location`, `salary`, `posted`, `createdDate` (IST string), `skills`, `url`.

- **jobs.json**: experience overlap + salary disclosed and ≥ min LPA.
- **jobs_no_salary.json**: experience overlap + salary not disclosed.

### `skills.json`

Rewritten each run from **matched + no-salary** jobs only (not raw search hits):

```json
{
  "count": 131,
  "skills": {
    "Java": 74,
    "Spring Boot": 65
  }
}
```

`skills` maps skill name → number of kept jobs that listed it (comma-split `tagsAndSkills`; at most once per job). Sorted by count descending.

### `storage.json`

Playwright `storage_state` (cookies/local storage) saved after a successful capture run so later runs can reuse login.

## Module map

| File | Role |
|------|------|
| `urls.txt` | Default listing URLs |
| `browser.py` | Playwright capture, pagination, slug/API matching |
| `extract.py` | `jobDetails` → normalized jobs |
| `criteria.py` | Title ignore, keywords, experience/salary parsing & split |
| `filter_sort.py` | Dedupe, freshness, cross-experience jobId uniqueness |
| `locations.py` | Target cities, grouping |
| `output.py` | Terminal print + JSON write |
| `skills_bank.py` | Skill → referral count file |
| `../main.py` | CLI orchestration |

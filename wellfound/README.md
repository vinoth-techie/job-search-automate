# Wellfound job search

Fetch Wellfound SEO role/location jobs with **headed Playwright** (DataDome + Turnstile), filter them, and write grouped JSON under `output/wellfound/`.

Package inputs live in `wellfound/`. Generated files go under `output/` via `paths.portal_output_dir("wellfound")`.

## Overview

```bash
python -m wellfound --all --max-pages 2
python -m wellfound --all --role backend-engineer --location india --max-pages 3
python -m wellfound --fresh 1440 --url 'https://wellfound.com/role/l/backend-engineer/india'
```

Default behavior:

1. Read listing URLs from `wellfound/urls.txt` (or `--url` / `--role` + `--location`).
2. Open each `/role/l/{role}/{location}` page in Chromium (**headed** by default).
3. Wait until `__NEXT_DATA__` Apollo payload appears (solve CAPTCHA in the window if prompted).
4. Paginate with `?page=N` and a delay between pages (`--page-delay`, default 5s).
5. Flatten `StartupResult` → `JobListingSearchResult`, drop ignored titles, keep target cities.
6. Write `output/wellfound/jobs.json` (bucket → city → company) and `skills.json`.

## Remaining problems / limits

| Issue | Impact |
|-------|--------|
| **Bot wall** | First runs often need a manual CAPTCHA. Rapid paging can still hit “Access is temporarily restricted”. Use slow `--page-delay` and reuse `output/wellfound/storage.json`. |
| **Headed browser** | Default is headed (like Naukri). `--headless` is more likely to fail the JS challenge. |
| **Thin salary / YOE** | SEO cards often have empty `compensation` and null `yearsExperience*`. Optional `--experience-years 3,4` keeps unknown YOE unless `--drop-unknown-experience`. |
| **No skills on list** | `skills` is usually empty; `skills.json` will stay sparse. |
| **Not a salary API** | Unlike Hirist Gladiator, there is no plain HTTP job API — HTML + Apollo only. |

## Layout

| Role | Path |
|------|------|
| URL list | `wellfound/urls.txt` |
| Module code | `wellfound/*.py` |
| Session | `output/wellfound/storage.json` |
| Jobs | `output/wellfound/jobs.json` |
| Skills bank | `output/wellfound/skills.json` |

## Data shape

Jobs come from `props.pageProps.apolloState.data`:

- `ROOT_QUERY.talent.seoLandingPageJobSearchResults({location,page,role})`
- `StartupResult` → `highlightedJobListings` → `JobListingSearchResult`

Normalized fields match other portals: `jobId`, `title`, `company`, `experience`, `location`, `salary`, `posted`, `createdDate`, `skills`, `url`.

Job URL: `https://wellfound.com/jobs/{id}-{slug}`.

`createdDate` / `--fresh` use `liveStartAt` (unix seconds → ms).

## CLI

```bash
python -m wellfound --all
python -m wellfound --all --max-pages 2 --page-delay 6
python -m wellfound --all --experience-years 3,4
python -m wellfound --fresh 60 --role software-engineer --location india
```

Grouping uses a single outer bucket (`--bucket all` by default) because SEO search is not split by YOE the way Instahyre `years=` is.

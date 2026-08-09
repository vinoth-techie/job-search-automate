# job-search-automate

Automate job discovery from **Naukri** and **Instahyre**: scrape/search, filter by criteria, and group results by experience → city → company.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Naukri

Captures `/jobapi/v3/search` responses via Playwright while opening listing URLs from `urls.txt`.

```bash
# First run: log in if prompted; session saved to naukri_storage.json
python main.py --all

# Only jobs created in the last N minutes
python main.py --fresh 60

# Custom URLs / output
python main.py --all --urls-file urls.txt --out jobs.json
```

## Instahyre

Fetches opportunities from `/api/v1/job_search` (years=3 and years=4 by default).

```bash
python -m instahyre --all
python -m instahyre --all --out instahyre_jobs.json
```

## Output

Matched jobs are written to JSON (defaults: `jobs.json` / `instahyre_jobs.json`). Generated data and browser storage files are gitignored.

# job-search-automate

Automate job discovery from **Naukri**, **Instahyre**, **Hirist**, and **Wellfound**: scrape/search, filter by criteria, and group results by experience → city → company.

## Docs (how each portal works)

| Portal | README — algorithm, API response, extraction |
|--------|-----------------------------------------------|
| Naukri | [naukri/README.md](naukri/README.md) |
| Instahyre | [instahyre/README.md](instahyre/README.md) |
| Hirist | [hirist/README.md](hirist/README.md) |
| Wellfound | [wellfound/README.md](wellfound/README.md) |

Each portal README covers end-to-end flow, response shape, field mapping, filters, CLI, and output files.

## Not supported

| Portal | Why we don’t scrape it |
|--------|------------------------|
| [Cutshort](https://cutshort.io/) | Authenticated `/profile/all-jobs` (login required for salary/exp/hiring filters). Public SEO category pages hard-cap at **50** jobs with no real pagination. |

## Layout

| | Paths |
|--|--|
| Naukri URLs | `naukri/urls.txt` |
| Hirist URLs | `hirist/urls.txt` |
| Wellfound URLs | `wellfound/urls.txt` |
| Outputs | `output/naukri/`, `output/instahyre/`, `output/hirist/`, `output/wellfound/` |

```
output/
  naukri/     jobs.json, jobs_no_salary.json, skills.json, storage.json
  instahyre/  jobs.json, skills.json
  hirist/     jobs.json, skills.json
  wellfound/  jobs.json, skills.json, storage.json
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Naukri

```bash
python main.py --all
python main.py --fresh 60
```

Details: [naukri/README.md](naukri/README.md)

## Instahyre

```bash
python -m instahyre --all
```

Details: [instahyre/README.md](instahyre/README.md)

## Hirist

Defaults: `hirist/urls.txt`, exp `2-3`, `posting=3`, Naukri cities (Bengaluru, Chennai, Hyderabad, Coimbatore).

```bash
python -m hirist --all
python -m hirist --all --keywords python,java --posting 3
python -m hirist --fresh 60 --keywords python
```

Details: [hirist/README.md](hirist/README.md)

## Wellfound

Defaults: `wellfound/urls.txt`, headed Playwright, `page_delay=5s`, cities Bengaluru / Chennai / Hyderabad / Coimbatore. CAPTCHA may appear on first run.

```bash
python -m wellfound --all --max-pages 2
python -m wellfound --all --role backend-engineer --location india --page-delay 6
python -m wellfound --fresh 1440 --url 'https://wellfound.com/role/l/software-engineer/india'
```

Details: [wellfound/README.md](wellfound/README.md)

## Push

```bash
gh auth login -h github.com
```

"""Persistent skills bank with per-skill job referral counts (Wellfound)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from paths import portal_output_dir

DEFAULT_SKILLS_FILE = str(portal_output_dir("wellfound") / "skills.json")


def split_skills(raw: str | None) -> list[str]:
    if not raw:
        return []
    skills: list[str] = []
    for part in str(raw).split(","):
        skill = part.strip()
        if skill:
            skills.append(skill)
    return skills


def collect_skill_counts(jobs: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for job in jobs:
        seen: set[str] = set()
        for skill in split_skills(job.get("skills")):
            key = skill.casefold()
            if key in seen:
                continue
            seen.add(key)
            names.setdefault(key, skill)
            counts[key] = counts.get(key, 0) + 1
    ordered = sorted(
        counts.keys(),
        key=lambda k: (-counts[k], names[k].casefold()),
    )
    return {names[key]: counts[key] for key in ordered}


def load_skill_counts(path: str | Path = DEFAULT_SKILLS_FILE) -> dict[str, int]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    if isinstance(data, dict) and isinstance(data.get("skills"), dict):
        out: dict[str, int] = {}
        for name, count in data["skills"].items():
            cleaned = str(name).strip()
            if not cleaned:
                continue
            try:
                out[cleaned] = int(count)
            except (TypeError, ValueError):
                out[cleaned] = 0
        return out
    return {}


def update_skills_bank(
    jobs: Iterable[dict[str, Any]],
    path: str | Path = DEFAULT_SKILLS_FILE,
) -> tuple[Path, int, int]:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    previous = len(load_skill_counts(file_path))
    job_list = list(jobs)
    counts = collect_skill_counts(job_list)
    if not counts and previous > 0:
        print(
            f"Keeping previous skills bank ({previous} skills); "
            f"this run produced no skill referrals from {len(job_list)} jobs."
        )
        return file_path, previous, previous
    payload = {"count": len(counts), "skills": counts}
    file_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return file_path, previous, len(counts)


def top_skills_summary(
    path: str | Path = DEFAULT_SKILLS_FILE,
    *,
    limit: int = 8,
) -> str:
    counts = load_skill_counts(path)
    if not counts:
        return "(none — SEO cards usually omit skills)"
    top = list(counts.items())[:limit]
    return ", ".join(f"{name}={count}" for name, count in top)

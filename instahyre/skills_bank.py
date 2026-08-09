"""Persistent unique skills bank from Instahyre keywords."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

DEFAULT_SKILLS_FILE = "skills.json"


def split_skills(raw: str | None) -> list[str]:
    if not raw:
        return []
    skills: list[str] = []
    for part in str(raw).split(","):
        skill = part.strip()
        if skill:
            skills.append(skill)
    return skills


def collect_skills_from_jobs(jobs: Iterable[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for job in jobs:
        found.extend(split_skills(job.get("skills")))
    return found


def load_skills(path: str | Path = DEFAULT_SKILLS_FILE) -> list[str]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    if isinstance(data, list):
        return [str(item).strip() for item in data if str(item).strip()]
    if isinstance(data, dict) and isinstance(data.get("skills"), list):
        return [str(item).strip() for item in data["skills"] if str(item).strip()]
    return []


def merge_unique_skills(*skill_lists: Iterable[str]) -> list[str]:
    by_key: dict[str, str] = {}
    for skills in skill_lists:
        for skill in skills:
            cleaned = str(skill).strip()
            if not cleaned:
                continue
            key = cleaned.casefold()
            if key not in by_key:
                by_key[key] = cleaned
    return sorted(by_key.values(), key=lambda value: value.casefold())


def update_skills_bank(
    jobs: Iterable[dict[str, Any]],
    path: str | Path = DEFAULT_SKILLS_FILE,
) -> tuple[Path, int, int]:
    file_path = Path(path)
    existing = load_skills(file_path)
    incoming = collect_skills_from_jobs(jobs)
    merged = merge_unique_skills(existing, incoming)
    file_path.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return file_path, len(existing), len(merged)

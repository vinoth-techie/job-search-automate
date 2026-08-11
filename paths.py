"""Repo paths: package inputs stay in modules; generated files go under output/."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = REPO_ROOT / "output"


def portal_output_dir(portal: str) -> Path:
    """Return output/<portal>/ and create it if missing."""
    path = OUTPUT_ROOT / portal
    path.mkdir(parents=True, exist_ok=True)
    return path

"""Filesystem layout. Every path in the project is derived from here."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CONFIG = ROOT / "config"
MODEL_CONFIG = CONFIG / "model.yaml"
ROSTER_CONFIG = CONFIG / "candidats_2027.yaml"

DATA = ROOT / "data"
CACHE = DATA / "cache"

SITE = ROOT / "site"
SITE_DATA = SITE / "data"

OUTPUTS = ROOT / "outputs"
RUNS = OUTPUTS / "runs"


def ensure_dirs() -> None:
    for p in (CACHE, SITE_DATA, RUNS):
        p.mkdir(parents=True, exist_ok=True)

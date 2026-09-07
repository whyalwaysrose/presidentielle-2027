"""Declared candidacies and withdrawals — facts, not proxies.

WHY THIS MATTERS
----------------
Ballot probabilities are otherwise derived from how often institutes test each
candidate, which is a proxy: it says a scenario is considered live, not that
the person is standing. When someone actually declares, or actually stands
down, that proxy should give way to the fact.

It is not a marginal correction. `candidats.csv` records **Jordan Bardella
withdrawing on 2026-07-07** — the same day Le Pen's ineligibility was cut to 15
months. Read only from testing frequency, the model gave him a 20% chance of
being on the ballot and about 14% of the presidency. He had stood down.

The two signals corroborate each other, which is what makes this trustworthy
rather than a single community-maintained field being taken on faith: the
polling record shows institutes stopping testing Bardella entirely from July
2026, independently and on the same date.

A DECLARATION IS NOT A CANDIDACY
--------------------------------
Withdrawal is treated as decisive; declaring is not. A declared candidate still
needs 500 validated *parrainages*, and can simply change their mind - the same
file has Gerald Darmanin declaring on 2026-08-17 and withdrawing on 2026-08-25,
eight days later. So a declaration raises the probability to a floor rather
than pinning it to one.

Both are applied only if dated on or before the as-of date, so a backtest
cannot see a candidacy that had not yet been announced.
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path

import requests

from ..paths import CACHE

log = logging.getLogger(__name__)

SOURCE_URL = (
    "https://raw.githubusercontent.com/MieuxVoter/presidentielle2027/main/candidats.csv"
)
CACHE_FILE = CACHE / "candidats_mieuxvoter.csv"


@dataclass(frozen=True)
class Candidacy:
    candidate_id: str
    nom: str
    annonce: dt.date | None
    retrait: dt.date | None

    def status(self, as_of: dt.date) -> str:
        """One of 'withdrawn', 'declared', 'unknown', as of a date."""
        if self.retrait and self.retrait <= as_of:
            return "withdrawn"
        if self.annonce and self.annonce <= as_of:
            return "declared"
        return "unknown"


def fetch(force: bool = False, timeout: int = 30) -> str:
    if CACHE_FILE.exists() and not force:
        return CACHE_FILE.read_text(encoding="utf-8")
    log.info("fetching %s", SOURCE_URL)
    resp = requests.get(SOURCE_URL, timeout=timeout)
    resp.raise_for_status()
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(resp.text, encoding="utf-8")
    return resp.text


def _parse(value: str | None) -> dt.date | None:
    v = (value or "").strip()
    if not v:
        return None
    try:
        return dt.date.fromisoformat(v[:10])
    except ValueError:
        return None


def load(path: Path | None = None) -> dict[str, Candidacy]:
    path = path or CACHE_FILE
    if not path.exists():
        fetch()
    out: dict[str, Candidacy] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            cid = (row.get("candidate_id") or "").strip()
            if not cid:
                continue
            out[cid] = Candidacy(
                candidate_id=cid,
                nom=(row.get("complete_name") or "").strip(),
                annonce=_parse(row.get("annonce_candidature")),
                retrait=_parse(row.get("retrait_candidature")),
            )
    return out


def hard_overrides(
    candidacies: dict[str, Candidacy],
    *,
    as_of: dt.date,
    declared_floor: float,
) -> tuple[dict[str, float], list[str]]:
    """Ballot probabilities implied by declarations and withdrawals.

    Returns the overrides and a human-readable list of what was applied, so a
    run reports the facts it acted on instead of them changing the forecast
    invisibly.
    """
    overrides: dict[str, float] = {}
    notes: list[str] = []
    for cid, c in sorted(candidacies.items()):
        state = c.status(as_of)
        if state == "withdrawn":
            overrides[cid] = 0.0
            notes.append(f"{c.nom or cid}: withdrew {c.retrait} -> not on the ballot")
        elif state == "declared":
            overrides[cid] = declared_floor
            notes.append(
                f"{c.nom or cid}: declared {c.annonce} -> at least {declared_floor:.0%}"
            )
    return overrides, notes

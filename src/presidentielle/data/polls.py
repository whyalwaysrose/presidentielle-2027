"""Ingest of French presidential voting-intention polls.

SOURCE
------
`MieuxVoter/presidentielle2027 <https://github.com/MieuxVoter/presidentielle2027>`_,
MIT licensed, auto-updated as notices appear. It is the working successor to
nsppolls, which compiled the 2022 cycle and stopped in May 2022.

Every record carries the filename of its **Commission des sondages** notice.
That commission is the statutory regulator: a poll published in France must be
filed with it, so the notice - not the newspaper write-up, and not this
repository - is the primary source for any number shown on the site.

SHAPE OF THE DATA, AND WHY IT IS AWKWARD
----------------------------------------
A French presidential poll does not test one race. It tests several
*hypotheses*: different candidate fields, priced off the same sample. Recent
surveys average 5.6 first-round hypotheses each and go up to 13.

Two consequences run through the whole project:

1. The hypotheses are **not independent observations**. One sample of ~1500
   people was asked repeatedly. :mod:`presidentielle.data.surveys` handles the
   down-weighting.
2. The candidate field is **itself unknown**. Le Pen appears in 86 records and
   Bardella in 79 - they are alternatives, not rivals. A model that picked one
   hypothesis would throw away half the file; a model that pooled them naively
   would have the RN running two candidates at once.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import requests

from ..paths import CACHE

log = logging.getLogger(__name__)

SOURCE_URL = (
    "https://raw.githubusercontent.com/MieuxVoter/presidentielle2027/main/presidentielle2027.json"
)
ROSTER_URL = "https://raw.githubusercontent.com/MieuxVoter/presidentielle2027/main/candidats.csv"
NOTICE_BASE = "http://www.commission-des-sondages.fr/notices/files/notices/"

CACHE_FILE = CACHE / "presidentielle2027.json"


@dataclass(frozen=True)
class Hypothese:
    """One candidate field priced by one survey."""

    poll_id: str
    institut: str
    commanditaire: str
    debut: dt.date
    fin: dt.date
    echantillon: int
    population: str
    hypothese: str
    tour: int
    notice: str
    shares: dict[str, float]  # candidate_id -> share of expressed votes, sums to 1

    @property
    def survey_key(self) -> tuple[str, dt.date, dt.date]:
        """Hypotheses sharing this key were asked of the same sample."""
        return (self.institut, self.debut, self.fin)

    @property
    def field(self) -> frozenset[str]:
        return frozenset(self.shares)

    @property
    def midpoint(self) -> dt.date:
        return self.debut + (self.fin - self.debut) / 2


def fetch(force: bool = False, timeout: int = 30) -> list[dict]:
    """Download the poll file, caching it so a run is reproducible offline."""
    if CACHE_FILE.exists() and not force:
        log.info("using cached polls at %s", CACHE_FILE)
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))

    log.info("fetching %s", SOURCE_URL)
    resp = requests.get(SOURCE_URL, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    log.info("cached %d records", len(payload))
    return payload


def _parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value.strip())


def _parse_tour(value: str) -> int:
    """'1er Tour' / '2nd Tour' -> 1 / 2."""
    v = (value or "").strip().lower()
    if v.startswith("1"):
        return 1
    if v.startswith("2"):
        return 2
    raise ValueError(f"unrecognised tour {value!r}")


def parse(
    payload: list[dict],
    *,
    roster,
    history_start: dt.date | None = None,
) -> tuple[list[Hypothese], list[str]]:
    """Turn raw records into :class:`Hypothese` objects.

    Returns the parsed hypotheses and a list of human-readable reasons for
    every record dropped, so a run can report what it ignored instead of
    quietly shrinking.

    THE ROSTER FAILS CLOSED. If any candidate in a hypothesis is not in
    ``config/candidats_2027.yaml``, the whole hypothesis is skipped rather than
    the unknown candidate being dropped. Dropping one candidate would silently
    renormalise everyone else upward - a poll where an unrecognised name polled
    12% would inflate every other candidate in it by about 14%.
    """
    out: list[Hypothese] = []
    skipped: list[str] = []

    for rec in payload:
        try:
            fin = _parse_date(rec["fin_enquete"])
            debut = _parse_date(rec["debut_enquete"])
            tour = _parse_tour(rec["tour"])
        except (KeyError, ValueError) as exc:
            skipped.append(f"{rec.get('poll_id', '?')}: unparseable ({exc})")
            continue

        if history_start and fin < history_start:
            continue

        cands = rec.get("candidats") or []
        unknown = [c["candidate_id"] for c in cands if c["candidate_id"] not in roster.candidats]
        if unknown:
            skipped.append(
                f"{rec.get('poll_id')} {rec.get('hypothese')}: unknown candidate(s) "
                f"{', '.join(sorted(unknown))} - add them to config/candidats_2027.yaml"
            )
            continue

        raw = {c["candidate_id"]: float(c["intentions"]) for c in cands}
        total = sum(raw.values())
        if total <= 0:
            skipped.append(f"{rec.get('poll_id')} {rec.get('hypothese')}: shares sum to zero")
            continue
        if not 95.0 <= total <= 105.0:
            # The published notices sum to 100 by construction (they are shares
            # of expressed votes). A sum well away from that means the record
            # is malformed, not that turnout is being modelled.
            skipped.append(
                f"{rec.get('poll_id')} {rec.get('hypothese')}: shares sum to {total:.1f}, not ~100"
            )
            continue

        if tour == 2 and len(raw) != 2:
            skipped.append(
                f"{rec.get('poll_id')} {rec.get('hypothese')}: second round with {len(raw)} candidates"
            )
            continue

        shares = {k: v / total for k, v in raw.items()}

        try:
            echantillon = int(rec["echantillon"])
        except (KeyError, TypeError, ValueError):
            skipped.append(f"{rec.get('poll_id')}: missing sample size")
            continue

        out.append(
            Hypothese(
                poll_id=str(rec["poll_id"]),
                institut=str(rec["institut"]).strip(),
                commanditaire=str(rec.get("commanditaire") or "").strip(),
                debut=debut,
                fin=fin,
                echantillon=echantillon,
                population=str(rec.get("population") or "").strip(),
                hypothese=str(rec.get("hypothese") or "").strip(),
                tour=tour,
                notice=str(rec.get("filename") or "").strip(),
                shares=shares,
            )
        )

    out.sort(key=lambda h: (h.fin, h.institut, h.hypothese))
    return out, skipped


def load(
    *,
    roster,
    history_start: dt.date | None = None,
    force: bool = False,
    cache_file: Path | None = None,
) -> tuple[list[Hypothese], list[str]]:
    if cache_file is not None:
        payload = json.loads(Path(cache_file).read_text(encoding="utf-8"))
    else:
        payload = fetch(force=force)
    return parse(payload, roster=roster, history_start=history_start)

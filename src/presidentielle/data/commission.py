"""Is the poll feed missing anything the Commission des sondages has published?

WHY THIS EXISTS
---------------
Every poll in this model comes from one community-maintained feed
(MieuxVoter/presidentielle2027). The authority it is built from is the
Commission des sondages, which by law receives a technical notice for every
published election poll. Nothing checked the one against the other, and on
2026-09-21 a manual comparison found:

* a real voting-intention poll that never reached the feed - OpinionWay for
  Fondapol, fieldwork 1-8 June 2026, 3 057 registered voters, second-round
  head-to-heads;
* an open upstream bug (MieuxVoter/presidentielle2027#182) whose detector
  files at most ten polls per run and silently skips the rest - six were lost
  that way on 2026-09-12.

This module makes that comparison automatic.

WHY IT READS THE NOTICES RATHER THAN THEIR NAMES
------------------------------------------------
The Commission files popularity barometers and opinion questions under the
same "Pres" category as voting intentions. Filenames do not separate them: of
the 46 notices already in the feed - every one a genuine voting-intention poll
- only 14 say so in their name. The rest look like
``9906-pres-ifop-sud-radio-le-figaro-28-fevrier.pdf``. So each notice the feed
lacks is downloaded once and its text read, and the verdict is cached in
``data/cache/commission_scan.json`` so it is never fetched again.

WHAT IT DOES NOT DO
-------------------
It never adds a poll to the model. A notice says what was asked, not reliably
what the answers were, and hand-transcribed numbers are exactly the kind of
unreviewed input this project refuses. A gap is REPORTED - in `audit`, in the
run diagnostics, and as a warning on the GitHub run - so a person can get it
into the feed upstream.

It does not fail the run either. A missing poll is upstream's problem, and a
red build every time an institute publishes before the feed catches up would
train everyone to ignore the colour.

SOURCE
------
MieuxVoter/sondages-commission-index mirrors the Commission's notice list and
the PDFs themselves. It is the same index the feed's own detector uses.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import logging
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import requests
import yaml

from ..paths import CACHE, CONFIG

log = logging.getLogger(__name__)

INDEX_REPO = "MieuxVoter/sondages-commission-index"
CATALOG_URL = f"https://raw.githubusercontent.com/{INDEX_REPO}/main/notices_catalog.csv"
PDF_BASE = f"https://raw.githubusercontent.com/{INDEX_REPO}/main/"

CATALOG_FILE = CACHE / "commission_catalog.csv"
SCAN_FILE = CACHE / "commission_scan.json"
# Human verdicts on individual notices. See that file for why each is there.
REVIEW_FILE = CONFIG / "notices_commission.yaml"

# A notice this recent may simply not have reached the feed yet; upstream
# ingests on its own schedule. Only older gaps are warnings.
GRACE_DAYS = 7

# ---------------------------------------------------------------------------
# PDF text
# ---------------------------------------------------------------------------
# Notices are Word or PowerPoint exports: Flate-compressed content streams
# with text in TJ/Tj operators. That is all this needs to read, so there is
# no PDF dependency. Every pattern is BOUNDED: the first version used
# `\[(.*?)\]\s*TJ` with DOTALL, which backtracks quadratically on a binary
# stream full of '[' and took minutes on some notices.

_STREAM = re.compile(rb"<<((?:[^<>]|<(?!<)|>(?!>)){0,5000})>>\s*stream\r?\n")
# An array or string cannot contain an unescaped opening bracket of its own
# kind, so each scan stops at the next one: linear, not merely bounded. A
# length cap alone still cost 4 000 steps per '[' - seconds on a hostile
# stream, which a test now pins.
_TJ = re.compile(rb"\[([^\[\]]{0,4000})\]\s*TJ")
_TJ_ONE = re.compile(rb"\(((?:\\.|[^\\()]){0,2000})\)\s*Tj")
_STRING = re.compile(rb"\(((?:\\.|[^\\()]){0,2000})\)")
_SKIP = (b"/Image", b"/FontFile", b"/Length1", b"/XObject")


def pdf_text(data: bytes) -> str:
    """Best-effort text of a notice PDF, whitespace collapsed."""
    out: list[str] = []
    for m in _STREAM.finditer(data):
        header = m.group(1)
        if b"FlateDecode" not in header or any(k in header for k in _SKIP):
            continue
        end = data.find(b"endstream", m.end())
        if end < 0:
            continue
        try:
            body = zlib.decompressobj().decompress(data[m.end():end])
        except zlib.error:
            continue
        if b"TJ" not in body and b"Tj" not in body:
            continue
        for raw in _TJ.findall(body):
            out.append(b"".join(_STRING.findall(raw)).decode("latin-1"))
        for raw in _TJ_ONE.findall(body):
            out.append(raw.decode("latin-1"))
    return re.sub(r"\s+", " ", " ".join(out))


# ---------------------------------------------------------------------------
# Is this notice a voting-intention poll?
# ---------------------------------------------------------------------------
# Calibrated against the catalog on 2026-09-21: see `classify`. Kept as data
# so the tests can check the patterns rather than the prose around them.

VOTE_PATTERNS = [
    r"intentions? de vote",
    r"si le (premier|1er|second|2nd) tour",
    r"(premier|1er|second|2nd) tour de l.?.?lection pr.sidentielle (de )?2027",
    r"(pour quel|lequel des) candidats?.{0,80}(voteriez|voterez|pr.f.rence)",
    r"aurait votre pr.f.rence",
    r"vous voteriez (blanc|pour)",
]
# Boilerplate some institutes put on opinion polls precisely to say they are
# NOT voting intentions. Each phrasing here was a false positive in
# calibration: Elabe "ne constituent ni une intention de vote", Toluna Harris
# Interactive "le potentiel electoral ne constitue nullement une intention de
# vote", Odoxa "n'a absolument rien a voir avec une intention de vote".
NEGATION = (
    r"(ni|pas|nullement|aucunement) (une|des|d.) ?intentions? de vote"
    r"|rien . voir avec (une|des) intentions? de vote"
)


def classify(text: str) -> tuple[str, str]:
    """Return (verdict, evidence) for a notice's text.

    verdict is "vote" (it asks how people would vote in 2027), "autre", or
    "illisible" when too little text came out to judge - which is reported as
    such rather than guessed.
    """
    if len(text) < 300:
        return "illisible", f"{len(text)} characters extracted"
    clean = re.sub(NEGATION, " ", text, flags=re.I)
    for pat in VOTE_PATTERNS:
        m = re.search(pat, clean, flags=re.I)
        if m:
            s, e = max(0, m.start() - 60), min(len(clean), m.end() + 60)
            return "vote", clean[s:e].strip()
    return "autre", ""


# ---------------------------------------------------------------------------
# Catalog and comparison
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Notice:
    filename: str
    published: dt.date | None
    pdf_path: str


@dataclass
class CoverageReport:
    latest_notice: dt.date | None
    notices_considered: int
    in_feed: int
    missing_vote: list[dict] = field(default_factory=list)     # overdue: WARN
    pending_vote: list[dict] = field(default_factory=list)     # within grace
    known_gaps: list[dict] = field(default_factory=list)       # reviewed, still absent
    unreadable: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing_vote and not self.unreadable and not self.errors

    def as_dict(self) -> dict:
        return {
            "derniere_notice": self.latest_notice.isoformat()
            if self.latest_notice else None,
            "notices_examinees": self.notices_considered,
            "dans_le_flux": self.in_feed,
            "manquantes": self.missing_vote,
            "en_attente": self.pending_vote,
            "lacunes_connues": self.known_gaps,
            "illisibles": self.unreadable,
            "erreurs": self.errors,
        }

    def lines(self) -> list[str]:
        out = []
        for n in self.missing_vote:
            out.append(
                f"MISSING from the feed: {n['fichier']} (published {n['publiee']}) "
                f"- reads as a voting-intention poll: \"{n['extrait']}\""
            )
        for n in self.pending_vote:
            out.append(
                f"pending (under {GRACE_DAYS} days old): {n['fichier']} - "
                "voting intentions, not in the feed yet"
            )
        for n in self.known_gaps:
            out.append(f"known gap (reviewed): {n['fichier']} - {n['note']}")
        for f in self.unreadable:
            out.append(f"could not read {f} - check it by hand, then record it in "
                       "config/notices_commission.yaml")
        out.extend(f"error: {e}" for e in self.errors)
        return out


def fetch_catalog(timeout: int = 60) -> None:
    """Refresh the cached catalog. Failure keeps the old cache and says so."""
    resp = requests.get(CATALOG_URL, timeout=timeout)
    resp.raise_for_status()
    CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_FILE.write_text(resp.text, encoding="utf-8")


def _date(value: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat((value or "").strip()[:10])
    except ValueError:
        return None


def load_catalog(path: Path | None = None) -> list[Notice]:
    """Presidential notices from the cached catalog."""
    path = path or CATALOG_FILE
    rows = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
    out = []
    for r in rows:
        if r.get("categorie") != "Pres":
            continue
        out.append(
            Notice(
                filename=r["filename"],
                # The PDF's own creation date is when the notice was written;
                # the server timestamp is a fallback, and can be later.
                published=_date(r.get("pdf creation-date", ""))
                or _date(r.get("http last-modified", "")),
                pdf_path=r.get("pdf_path", ""),
            )
        )
    return out


def load_reviews(path: Path | None = None) -> dict[str, dict]:
    path = path or REVIEW_FILE
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw.get("notices") or {}


# What a person can conclude about a notice after reading it.
REVIEW_STATUSES = {
    "pas_une_intention": "not a 2027 voting-intention poll",
    "dans_le_flux": "already in the feed, under another filename",
    "manquante": "a voting-intention poll the feed does not have",
}


def _load_scan() -> dict:
    if SCAN_FILE.exists():
        return json.loads(SCAN_FILE.read_text(encoding="utf-8"))
    return {}


def _save_scan(scan: dict) -> None:
    SCAN_FILE.write_text(
        json.dumps(scan, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )


def check(
    feed_filenames: set[str],
    *,
    as_of: dt.date,
    since: dt.date,
    download: bool = True,
    timeout: int = 60,
) -> CoverageReport:
    """Compare the feed with the Commission catalog.

    ``since`` bounds the comparison to the period the feed claims to cover.
    With ``download`` false, only verdicts already cached are used - that is
    what the test suite and the offline `audit` rely on.
    """
    notices = [n for n in load_catalog() if n.published and n.published >= since]
    report = CoverageReport(
        latest_notice=max((n.published for n in notices), default=None),
        notices_considered=len(notices),
        in_feed=sum(1 for n in notices if n.filename in feed_filenames),
    )
    scan = _load_scan()
    reviews = load_reviews()
    dirty = False
    for n in notices:
        if n.filename in feed_filenames:
            continue
        review = reviews.get(n.filename)
        if review:
            # A person has read it. That beats the classifier either way.
            if review.get("statut") == "manquante":
                report.known_gaps.append({
                    "fichier": n.filename,
                    "publiee": n.published.isoformat(),
                    "note": review.get("note", ""),
                })
            continue
        if re.match(r"^\d+-mun-", n.filename):
            # Municipal polls filed under "Pres" upstream. Not this election.
            continue
        verdict = scan.get(n.filename)
        if verdict is None:
            if not download:
                report.unreadable.append(f"{n.filename} (not yet scanned)")
                continue
            try:
                resp = requests.get(PDF_BASE + n.pdf_path, timeout=timeout)
                resp.raise_for_status()
                v, evidence = classify(pdf_text(resp.content))
            except requests.RequestException as exc:
                # Not cached: a transient failure is retried on the next run.
                report.errors.append(f"{n.filename}: {type(exc).__name__}")
                continue
            verdict = {"verdict": v, "extrait": evidence[:200]}
            scan[n.filename] = verdict
            dirty = True
        if verdict["verdict"] == "illisible":
            report.unreadable.append(n.filename)
        elif verdict["verdict"] == "vote":
            entry = {
                "fichier": n.filename,
                "publiee": n.published.isoformat(),
                "extrait": verdict.get("extrait", ""),
            }
            late = (as_of - n.published).days >= GRACE_DAYS
            (report.missing_vote if late else report.pending_vote).append(entry)
    if dirty:
        _save_scan(scan)
    return report


def feed_filenames(path: Path | None = None) -> set[str]:
    """Notice filenames the poll feed already carries."""
    from .polls import CACHE_FILE as POLLS

    records = json.loads((path or POLLS).read_text(encoding="utf-8"))
    return {r["filename"] for r in records if r.get("filename")}


def github_annotations(report: CoverageReport) -> list[str]:
    """Workflow commands, so a gap shows on the run's summary page.

    Only an unreviewed, overdue voting-intention notice is a WARNING. Known
    gaps and unreadable notices are NOTICES: visible, but not an alarm that
    repeats every morning about something already written down.
    """
    out = []
    for n in report.missing_vote:
        out.append(
            f"::warning title=Poll missing from the feed::{n['fichier']} "
            f"(published {n['publiee']}) reads as a voting-intention poll and is "
            "not in the feed. Read it, then record a verdict in "
            "config/notices_commission.yaml."
        )
    for n in report.known_gaps:
        out.append(f"::notice title=Known gap in the feed::{n['fichier']}")
    for f in report.unreadable:
        out.append(f"::notice title=Notice not readable::{f}")
    for e in report.errors:
        out.append(f"::notice title=Commission check error::{e}")
    return out

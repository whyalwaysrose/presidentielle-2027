"""Measured second-round vote transfers from the 2022 cycle.

WHY THIS MATTERS MORE THAN ANYTHING ELSE IN THE RUNOFF
------------------------------------------------------
The runoff decides the presidency, and what decides the runoff is where the
eliminated candidates' voters go. Until now that was estimated from 54
*hypothetical* 2027 matchups alone - polls asking people about a runoff two
years away between candidates who may not stand.

``nsppolls/reports.csv`` is a different kind of evidence: 609 rows in which
institutes asked 2022 voters, during the actual campaign between the two
actual finalists, where their first-round vote was going. It is the closest
thing available to a measurement of the *front republicain* rather than a
guess at it.

WHAT IS AND IS NOT CARRIED ACROSS
---------------------------------
The structure - how far each bloc sits from each other, how readily its voters
abstain - is treated as a property of French politics and shared across
cycles. The **front republicain term is not**. Whether voters will still cross
the aisle to block the RN in 2027 as they did in 2022 is precisely the
question, so the model fits one value for 2022, a separate one for 2027, and a
prior linking them that says the second is probably like the first but need
not be. That link, not the 2022 number itself, is the point.

WHAT IS EXCLUDED, AND WHY
-------------------------
* Rows whose first-round choice is ``Abstention`` - those are not transfers
  from a candidate.
* Macron and Le Pen themselves. They were the finalists; their own voters'
  behaviour is retention, which the model handles as the finalist's own vote,
  not as a transfer.
* Poutou and Arthaud, who are simply absent from the file.

Each institute contributes only its **final** wave, so a house that published
weekly does not outvote one that published once.
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path

from ..paths import CACHE

log = logging.getLogger(__name__)

REPORTS_CSV = CACHE / "nsppolls_reports_2022.csv"
SOURCE_URL = "https://raw.githubusercontent.com/nsppolls/nsppolls/master/reports.csv"

# The file writes dates in French longhand ("22 avril 2022").
MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

# The 2022 finalists, and therefore the two destinations that are not
# abstention.
FINALIST_A = "Emmanuel Macron"   # centre
FINALIST_B = "Marine Le Pen"     # rn

EXCLUDED_SOURCES = {"Abstention", FINALIST_A, FINALIST_B}


@dataclass(frozen=True)
class TransferObservation:
    """One institute's reading of where one bloc's voters were going."""

    bloc: str
    to_a: float          # share going to the centre finalist
    to_b: float          # share going to the RN finalist
    to_abstention: float
    institut: str
    fin: dt.date
    source_candidate: str


def _parse_date(value: str) -> dt.date | None:
    parts = (value or "").strip().lower().split()
    if len(parts) != 3:
        return None
    day, month, year = parts
    if month not in MOIS or not day.isdigit() or not year.isdigit():
        return None
    return dt.date(int(year), MOIS[month], int(day))


def load(
    *,
    results: dict,
    path: Path | None = None,
) -> tuple[list[TransferObservation], list[str]]:
    """Parse the measured transfers into bloc-level observations.

    ``results`` is ``config/resultats_2022.yaml``, which supplies both the
    poll-name-to-candidate mapping and each 2022 candidate's bloc, so the
    grouping used here is the same one the model uses.

    FAILS CLOSED, like the roster: an unrecognised first-round candidate is
    reported rather than silently dropped, because dropping one would remove a
    whole bloc's evidence without anything looking wrong.
    """
    path = path or REPORTS_CSV
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Fetch it with:\n  curl -sL -o {path} {SOURCE_URL}"
        )

    names = results["noms_sondages"]
    blocs = {k: v["bloc"] for k, v in results["premier_tour"]["candidats"].items()}

    # (institut, source candidate) -> {choice: part}, keeping the latest wave.
    latest: dict[tuple[str, str], dict] = {}
    skipped: list[str] = []

    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            source = (row.get("candidat_T1") or "").strip()
            if source in EXCLUDED_SOURCES:
                continue
            key_name = names.get(source)
            if key_name is None:
                skipped.append(f"unrecognised first-round candidate {source!r}")
                continue
            fin = _parse_date(row.get("fin_enquete", ""))
            if fin is None:
                skipped.append(f"unparseable date {row.get('fin_enquete')!r}")
                continue
            inst = (row.get("nom_institut") or "").strip()
            try:
                part = float(row["part"]) / 100.0
            except (KeyError, TypeError, ValueError):
                skipped.append(f"unparseable part for {source} / {inst}")
                continue

            k = (inst, source)
            cur = latest.get(k)
            if cur is None or fin > cur["fin"]:
                cur = {"fin": fin, "choices": {}, "bloc": blocs[key_name]}
                latest[k] = cur
            elif fin < cur["fin"]:
                continue
            cur["choices"][(row.get("choix_T2") or "").strip()] = part

    out: list[TransferObservation] = []
    for (inst, source), rec in latest.items():
        ch = rec["choices"]
        a, b = ch.get(FINALIST_A), ch.get(FINALIST_B)
        abst = ch.get("Abstention")
        if a is None or b is None:
            skipped.append(f"{inst} / {source}: incomplete destinations")
            continue
        if abst is None:
            abst = max(0.0, 1.0 - a - b)
        total = a + b + abst
        if total <= 0:
            skipped.append(f"{inst} / {source}: destinations sum to zero")
            continue
        out.append(
            TransferObservation(
                bloc=rec["bloc"],
                to_a=a / total,
                to_b=b / total,
                to_abstention=abst / total,
                institut=inst,
                fin=rec["fin"],
                source_candidate=source,
            )
        )

    out.sort(key=lambda o: (o.bloc, o.institut, o.source_candidate))
    log.info(
        "2022 transfers: %d observations across %d blocs, %d institutes",
        len(out),
        len({o.bloc for o in out}),
        len({o.institut for o in out}),
    )
    return out, skipped

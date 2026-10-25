"""What the transfer model implies about runoff polls, and whether that holds.

WHY THIS EXISTS
---------------
Every other large judgement in this project is measured and published. The
first round is scored against 2022, the field is derived from testing
behaviour and reported, the feed is checked against the Commission's own
catalog. The transfer model was the exception: it moves the headline more than
anything else and nobody could read what it was doing.

It is doing something big. Runoff polls currently have Marine Le Pen beating
Edouard Philippe; the model makes him the favourite. That is a deliberate
correction - runoff polls have overstated the RN at every presidential runoff
it has reached - but until now the only way to see its size was to infer it
from a win probability, which is a threshold and not a share.

So this states the correction in points, per duel, beside the polls it departs
from. A reader who thinks the front republicain is dead can see exactly how
much of the forecast rests on it being alive.

WHAT IT IS NOT
--------------
NOT a correction factor, and nothing reads it back into the model. The
transfer model is fitted on the 2022 presidential transfers and 317 RN duels
from the 2024 legislatives; this measures the result of that fit rather than
adjusting it. Turning the diagnostic into an input would make the model agree
with itself.

THE ONE HISTORICAL CHECK WE HAVE, and its limits. 2022 is the only
presidential runoff for which this repository holds both the final polls and
the result, so `historical_error` scores exactly one election. One data point
cannot establish a rate. It also came with an incumbent president on the other
side of the ballot, and the front republicain of 2022 is not obviously the
front republicain of 2027. It is a reference point, not a target, and the
model is not fitted to it.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .paths import CACHE, CONFIG

log = logging.getLogger(__name__)

RESULTS_2022_FILE = CONFIG / "resultats_2022.yaml"
POLLS_2022_FILE = CACHE / "nsppolls_2022.json"

# Runoff polls within this many days of the simulation's `as_of` count as
# "current". Wide enough to hold several institutes, short enough that a duel
# tested before a candidate withdrew does not dominate.
POLL_WINDOW_DAYS = 90
# Below this, a pairing is too rare to be worth reporting beside polls.
MIN_MATCHUP_PROB = 0.02
# The final stretch of the 2022 campaign, where a poll is a fair test of the
# result rather than of a race still moving.
FINAL_FORTNIGHT_2022 = dt.date(2022, 4, 11)


@dataclass(frozen=True)
class DuelComparison:
    a: str
    b: str
    nom_a: str
    nom_b: str
    p_matchup: float
    modele_a: float          # share the model implies for `a`
    sondages_a: float | None  # the same share in recent runoff polls
    n_sondages: int
    ecart: float | None       # model minus polls, in points, for `a`
    rn: str | None            # which of the two is the RN candidate, if either

    @property
    def ecart_rn(self) -> float | None:
        """The correction expressed against the RN, which is the direction the
        historical evidence speaks to. Negative means the model is HARSHER on
        the RN than the polls are."""
        if self.ecart is None or self.rn is None:
            return None
        return self.ecart if self.rn == self.a else -self.ecart


@dataclass(frozen=True)
class Report:
    duels: list[DuelComparison] = field(default_factory=list)
    reference_2022: float | None = None   # points polls overstated the RN by
    n_polls_2022: int = 0

    def lines(self) -> list[str]:
        out = []
        for d in self.duels:
            if d.sondages_a is None:
                out.append(
                    f"{d.nom_a} v {d.nom_b} ({d.p_matchup:.0%} of simulations): "
                    f"model {100 * d.modele_a:.1f}% for {d.nom_a} - no runoff "
                    f"poll of this pairing in the last {POLL_WINDOW_DAYS} days"
                )
                continue
            out.append(
                f"{d.nom_a} v {d.nom_b} ({d.p_matchup:.0%} of simulations): "
                f"model {100 * d.modele_a:.1f}% vs polls {100 * d.sondages_a:.1f}% "
                f"for {d.nom_a} ({d.n_sondages} poll(s)) - "
                f"{d.ecart * 100:+.1f} pts"
                + (f", i.e. {d.ecart_rn * 100:+.1f} pts for the RN"
                   if d.ecart_rn is not None else "")
            )
        if self.reference_2022 is not None:
            out.append(
                f"for reference, in 2022 the final {self.n_polls_2022} runoff "
                f"polls overstated the RN by {self.reference_2022 * 100:+.1f} "
                "pts (one election, with an incumbent opponent)"
            )
        return out


def _rn_of(a: str, b: str, bloc_of: dict[str, str]) -> str | None:
    rn = [c for c in (a, b) if bloc_of.get(c) == "rn"]
    return rn[0] if len(rn) == 1 else None


def poll_shares(
    hypotheses, *, as_of: dt.date, window_days: int = POLL_WINDOW_DAYS
) -> dict[frozenset[str], tuple[float, float, int]]:
    """Recent runoff polling by pairing: {pair -> (share_x, share_y, n)}.

    Keyed by an unordered pair, with the shares returned in a dict so the
    caller cannot mix up which candidate got which number.
    """
    cutoff = as_of - dt.timedelta(days=window_days)
    by_pair: dict[frozenset[str], list[dict[str, float]]] = {}
    for h in hypotheses:
        if h.tour != 2 or h.fin < cutoff or len(h.shares) != 2:
            continue
        by_pair.setdefault(frozenset(h.shares), []).append(h.shares)
    out = {}
    for pair, rows in by_pair.items():
        x, y = sorted(pair)
        out[pair] = (
            statistics.fmean(r[x] for r in rows),
            statistics.fmean(r[y] for r in rows),
            len(rows),
        )
    return out


def historical_error(
    results_2022: Path | None = None, polls_2022: Path | None = None
) -> tuple[float | None, int]:
    """By how much did the final 2022 runoff polls overstate the RN?

    Positive means the polls had Le Pen higher than she finished. Returns
    (error, n_polls), or (None, 0) if either file is missing - a diagnostic
    that cannot find its reference says so rather than guessing one.
    """
    results_path = results_2022 or RESULTS_2022_FILE
    polls_path = polls_2022 or POLLS_2022_FILE
    if not results_path.exists() or not polls_path.exists():
        return None, 0

    second = yaml.safe_load(results_path.read_text(encoding="utf-8"))["second_tour"]
    votes = {k: v["voix"] for k, v in second["candidats"].items()}
    rn_name = next(k for k, v in second["candidats"].items() if v["bloc"] == "rn")
    actual_rn = votes[rn_name] / sum(votes.values())

    payload = json.loads(polls_path.read_text(encoding="utf-8"))
    records = payload if isinstance(payload, list) else payload.get("polls", [])
    polled = []
    for rec in records:
        fin = dt.date.fromisoformat(rec["fin_enquete"])
        if fin < FINAL_FORTNIGHT_2022:
            continue
        for tour in rec.get("tours", []):
            if tour.get("tour") != "Deuxième tour":
                continue
            for hyp in tour.get("hypotheses", []):
                shares = {c["candidat"]: c["intentions"] for c in hyp.get("candidats", [])}
                if shares.keys() != {"Emmanuel Macron", "Marine Le Pen"}:
                    continue
                polled.append(shares["Marine Le Pen"] / 100.0)
    if not polled:
        return None, 0
    return statistics.fmean(polled) - actual_rn, len(polled)


def compare(matchups, roster, hypotheses, *, as_of: dt.date) -> Report:
    """Each likely duel's implied share beside the polls for that pairing."""
    bloc_of = {cid: c.bloc for cid, c in roster.candidats.items()}
    polls = poll_shares(hypotheses, as_of=as_of)

    duels = []
    for row in matchups:
        if row["p_matchup"] < MIN_MATCHUP_PROB:
            continue
        a, b = row["a"], row["b"]
        modele_a = row["part_a"]
        measured = polls.get(frozenset((a, b)))
        sondages_a = n = None
        if measured is not None:
            x, y = sorted((a, b))
            sondages_a = measured[0] if x == a else measured[1]
            n = measured[2]
        duels.append(
            DuelComparison(
                a=a, b=b,
                nom_a=roster.candidats[a].nom,
                nom_b=roster.candidats[b].nom,
                p_matchup=row["p_matchup"],
                modele_a=modele_a,
                sondages_a=sondages_a,
                n_sondages=n or 0,
                ecart=None if sondages_a is None else modele_a - sondages_a,
                rn=_rn_of(a, b, bloc_of),
            )
        )
    error, n2022 = historical_error()
    return Report(duels=duels, reference_2022=error, n_polls_2022=n2022)


def as_dict(report: Report) -> dict:
    return {
        "duels": [
            {
                "a": d.a, "b": d.b, "nom_a": d.nom_a, "nom_b": d.nom_b,
                "p_duel": round(d.p_matchup, 5),
                "part_modele_a": round(d.modele_a, 5),
                "part_sondages_a": None if d.sondages_a is None else round(d.sondages_a, 5),
                "n_sondages": d.n_sondages,
                "ecart_a": None if d.ecart is None else round(d.ecart, 5),
                "ecart_rn": None if d.ecart_rn is None else round(d.ecart_rn, 5),
            }
            for d in report.duels
        ],
        "reference_2022": (
            None if report.reference_2022 is None else round(report.reference_2022, 5)
        ),
        "n_sondages_2022": report.n_polls_2022,
    }

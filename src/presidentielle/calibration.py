"""Fit the election-day error against the 2022 cycle.

WHAT THIS REPLACES
------------------
``election_day_error`` in ``config/model.yaml`` used to carry numbers I chose,
under a comment claiming they were fitted by a command that did not exist.
This is that command.

WHAT IS MEASURED
----------------
How wrong were the final polls, on the day, about the actual result?

    error_c = log(poll share of c) - log(actual share of c)

taken over polls in the last two weeks before the first round of 2022, scored
against the Ministry of the Interior's proclaimed result.

The log scale is not a presentation choice: :mod:`presidentielle.model.simulate`
applies election-day error by perturbing candidate *strengths* and then taking
the nested logit, precisely so a candidate on 4% carries a smaller absolute
miss than one on 34%. Fitting on the same scale the error is applied on is
what makes the fitted number mean what the model does with it.

EACH INSTITUTE'S FINAL POLL, NOT EVERY POLL IN A WINDOW
------------------------------------------------------
Uncertainty in this model is **split, not stacked**. A poll misses for two
different reasons: systematic error in the poll itself, and genuine opinion
change before election day. The random walk already represents the second, so
folding drift into the error term would count that movement twice.

Measured, on 2022: averaging every poll in the fortnight gives a log-error SD
of 0.310; taking only each institute's *final* poll gives 0.247. The gap is
late movement, not polling error - Melenchon gained through the closing days
and the fortnight average is scored partly on where he was, not where he
ended. Only the final polls are used, which is also the standard way poll
error is quoted.

MAJOR CANDIDATES SET THE SCALE
------------------------------
The model applies ONE constant error on the log scale, but real error is not
constant there: proportional misses are larger for small candidates and
smaller for large ones. On 2022 final polls, the log-error SD is 0.201 for
candidates who took 5% or more and 0.247 across everyone above 2%.

The scale is therefore fitted on candidates at or above 5%, because they are
the ones the forecast's outputs actually turn on - who reaches the runoff and
who wins it. The consequence is that proportional uncertainty is understated
for minor candidates, and that is a stated simplification rather than a
discovery waiting to be made.

CORRELATION WITHIN A BLOC
-------------------------
An institute that under-reads the RN under-reads every RN candidate at once, so
election-day errors are correlated inside a bloc. That correlation is measured
here too, from the same residuals, rather than assumed.

ONE CYCLE IS ONE CYCLE
----------------------
The first round gives twelve candidates across many institutes, which supports
a real estimate. The second round of 2022 was a single matchup, so its error is
one number from one event: reported, but not something to treat as a fitted
distribution. That limit is stated in the output and in the config.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from .paths import CACHE, CONFIG

log = logging.getLogger(__name__)

RESULTS_CONFIG = CONFIG / "resultats_2022.yaml"
ARCHIVE = CACHE / "nsppolls_2022.json"

# The share at which `r1_share_error_sd` is quoted, matching REFERENCE_SHARE in
# simulate.py. The fitted quantity is a log-scale SD; the config stores the
# share-scale equivalent at this share, which is where the softmax slope is
# p(1-p).
REFERENCE_SHARE = 0.25

# Only polls this close are considered at all; within that, one poll per
# institute (its last) is scored, so late drift is not counted as error.
WINDOW_DAYS = 14

# The share at or above which a candidate sets the fitted scale. See the
# module docstring: the model applies one constant log-scale error, and these
# are the candidates whose accuracy the forecast turns on.
MAJOR_SHARE = 0.05

# Below this share the log scale is dominated by the 0.5-point rounding in the
# published notices.
MIN_SHARE = 0.02


@dataclass
class CalibrationResult:
    n_polls: int
    n_observations: int
    n_institutes: int
    log_error_sd: float          # candidates >= MAJOR_SHARE; sets the config value
    log_error_sd_all: float      # everyone above MIN_SHARE, for comparison
    r1_share_error_sd: float
    bloc_error_corr: float
    n_same_bloc_pairs: int
    mean_signed_log_error: float
    worst: list[tuple[str, float]] = field(default_factory=list)
    r2_error_points: float | None = None
    r2_n_polls: int = 0

    def as_dict(self) -> dict:
        return {
            "n_polls": self.n_polls,
            "n_observations": self.n_observations,
            "n_institutes": self.n_institutes,
            "log_error_sd": round(self.log_error_sd, 4),
            "log_error_sd_all": round(self.log_error_sd_all, 4),
            "n_same_bloc_pairs": self.n_same_bloc_pairs,
            "r1_share_error_sd": round(self.r1_share_error_sd, 4),
            "bloc_error_corr": round(self.bloc_error_corr, 3),
            "mean_signed_log_error": round(self.mean_signed_log_error, 4),
            "r2_error_points": (
                None if self.r2_error_points is None else round(self.r2_error_points, 3)
            ),
            "r2_n_polls": self.r2_n_polls,
        }


def load_results(path: Path | None = None) -> dict:
    with (path or RESULTS_CONFIG).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _actual_shares(results: dict, tour: str) -> dict[str, float]:
    block = results[tour]
    total = float(block["exprimes"])
    return {k: v["voix"] / total for k, v in block["candidats"].items()}


def _first_round_polls(payload: list[dict], results: dict, election: dt.date):
    """Final-window first-round polls whose field is exactly the real ballot.

    Requiring the exact field matters. A poll testing a hypothetical that never
    appeared on the ballot is not wrong about the election; it is answering a
    different question, and scoring it as error would measure the hypothesis
    rather than the polling.
    """
    names = results["noms_sondages"]
    actual = set(_actual_shares(results, "premier_tour"))
    out = []
    for poll in payload:
        fin = poll.get("fin_enquete")
        if not fin:
            continue
        d = dt.date.fromisoformat(fin)
        if not 0 <= (election - d).days <= WINDOW_DAYS:
            continue
        n = poll.get("echantillon") or 0
        inst = (poll.get("nom_institut") or "").strip()
        for tour in poll.get("tours") or []:
            if not str(tour.get("tour", "")).lower().startswith("premier"):
                continue
            for hyp in tour.get("hypotheses") or []:
                cands = hyp.get("candidats") or []
                mapped, unknown = {}, False
                for c in cands:
                    key = names.get(c["candidat"])
                    if key is None:
                        unknown = True
                        break
                    mapped[key] = float(c.get("intentions") or 0)
                if unknown or set(mapped) != actual:
                    continue
                total = sum(mapped.values())
                if total <= 0:
                    continue
                out.append(
                    {
                        "institut": inst,
                        "fin": d,
                        "n": n,
                        "shares": {k: v / total for k, v in mapped.items()},
                    }
                )
                # One reading per survey; later hypotheses re-ask the same sample.
                break
    return out


def _second_round_polls(payload: list[dict], results: dict, election: dt.date):
    names = results["noms_sondages"]
    actual = set(_actual_shares(results, "second_tour"))
    out = []
    for poll in payload:
        fin = poll.get("fin_enquete")
        if not fin:
            continue
        d = dt.date.fromisoformat(fin)
        if not 0 <= (election - d).days <= WINDOW_DAYS:
            continue
        for tour in poll.get("tours") or []:
            if str(tour.get("tour", "")).lower().startswith("premier"):
                continue
            for hyp in tour.get("hypotheses") or []:
                cands = hyp.get("candidats") or []
                mapped = {}
                ok = True
                for c in cands:
                    key = names.get(c["candidat"])
                    if key is None:
                        ok = False
                        break
                    mapped[key] = float(c.get("intentions") or 0)
                if not ok or set(mapped) != actual:
                    continue
                total = sum(mapped.values())
                if total <= 0:
                    continue
                out.append({"fin": d, "shares": {k: v / total for k, v in mapped.items()}})
                break
    return out


def calibrate(
    *,
    archive: Path | None = None,
    results_path: Path | None = None,
) -> CalibrationResult:
    archive = archive or ARCHIVE
    if not archive.exists():
        raise FileNotFoundError(
            f"{archive} not found. Fetch it with:\n"
            "  curl -sL -o data/cache/nsppolls_2022.json "
            "https://raw.githubusercontent.com/nsppolls/nsppolls/master/presidentielle.json"
        )
    payload = json.loads(archive.read_text(encoding="utf-8"))
    results = load_results(results_path)

    r1_date = results["premier_tour"]["date"]
    r2_date = results["second_tour"]["date"]
    actual1 = _actual_shares(results, "premier_tour")
    actual2 = _actual_shares(results, "second_tour")
    blocs = {k: v["bloc"] for k, v in results["premier_tour"]["candidats"].items()}

    all_polls = _first_round_polls(payload, results, r1_date)
    # One poll per institute: its last. Scoring every poll in the fortnight
    # counts late movement as polling error - measured at 0.310 log SD against
    # 0.247 for final polls alone.
    latest: dict[str, dict] = {}
    for p in all_polls:
        cur = latest.get(p["institut"])
        if cur is None or p["fin"] > cur["fin"]:
            latest[p["institut"]] = p
    polls = list(latest.values())
    if len(polls) < 5:
        raise ValueError(f"only {len(polls)} usable final polls; cannot fit")

    residuals: list[dict[str, float]] = []
    flat_all: list[float] = []
    flat_major: list[float] = []
    per_candidate: dict[str, list[float]] = {}
    for p in polls:
        row = {}
        for cand, share in p["shares"].items():
            if share < MIN_SHARE or actual1[cand] < MIN_SHARE:
                continue
            e = math.log(share) - math.log(actual1[cand])
            row[cand] = e
            flat_all.append(e)
            if actual1[cand] >= MAJOR_SHARE:
                flat_major.append(e)
            per_candidate.setdefault(cand, []).append(e)
        residuals.append(row)

    log_sd_all = statistics.pstdev(flat_all) if len(flat_all) > 1 else 0.0
    log_sd = statistics.pstdev(flat_major) if len(flat_major) > 1 else log_sd_all
    mean_signed = statistics.mean(flat_major) if flat_major else 0.0

    # Within-bloc correlation, net of the common miss. The background level is
    # subtracted because a national error inflates every pair equally and the
    # model already carries that through its shared components.
    same, cross = [], []
    same_pairs = set()
    for row in residuals:
        keys = sorted(row)
        for i, a in enumerate(keys):
            for b in keys[i + 1 :]:
                prod = row[a] * row[b]
                if blocs[a] == blocs[b]:
                    same.append(prod)
                    same_pairs.add((a, b))
                else:
                    cross.append(prod)
    var = log_sd_all**2 if log_sd_all > 0 else 1.0
    corr_same = (statistics.mean(same) / var) if same else 0.0
    corr_cross = (statistics.mean(cross) / var) if cross else 0.0
    bloc_corr = float(np.clip(corr_same - corr_cross, 0.0, 0.95))

    worst = sorted(
        ((c, statistics.mean(v)) for c, v in per_candidate.items()),
        key=lambda kv: -abs(kv[1]),
    )[:4]

    r2_all = _second_round_polls(payload, results, r2_date)
    r2_err = None
    if r2_all:
        macron = [p["shares"]["MACRON"] for p in r2_all]
        r2_err = (statistics.mean(macron) - actual2["MACRON"]) * 100

    return CalibrationResult(
        n_polls=len(polls),
        n_observations=len(flat_all),
        n_institutes=len({p["institut"] for p in polls}),
        log_error_sd=log_sd,
        log_error_sd_all=log_sd_all,
        r1_share_error_sd=log_sd * REFERENCE_SHARE * (1 - REFERENCE_SHARE),
        bloc_error_corr=bloc_corr,
        n_same_bloc_pairs=len(same_pairs),
        mean_signed_log_error=mean_signed,
        worst=worst,
        r2_error_points=r2_err,
        r2_n_polls=len(r2_all),
    )

"""Run the whole pipeline on the 2022 cycle and score it on the real result.

WHAT THIS CAN AND CANNOT TELL YOU
---------------------------------
It is the only end-to-end check that the nested logit, the ballot simulation
and the runoff model work *together* rather than each being individually
reasonable. It answers: given only what was known on a chosen date, does the
model put the right two candidates in the runoff, and the right one in the
Elysee?

It does **not** independently validate the interval widths, and it is important
not to present it as if it did. Both parameters that set those widths - the
random-walk scale from ``fit_walk_scale.py`` and the election-day error from
``calibrate`` - are themselves fitted on the 2022 cycle. Scoring 2022 coverage
against them is partly circular. With one cycle of French polling in hand there
is no way around that; there is only the choice between saying so and not.

NO LOOKAHEAD
------------
Everything the backtest uses must have existed on the as-of date.

* Polls are filtered to those whose fieldwork ended on or before the cutoff.
* The **2022 measured transfers are excluded**. They were published during the
  April 2022 campaign, so anchoring a January 2022 forecast on them would be
  using the future to predict the past. The deployed 2027 model may legitimately
  use them - they are history relative to 2027 - so the runoff here is the
  *unanchored* model, and is a weaker thing than what runs in production.
* The 2022 roster is separate (``config/candidats_2022.yaml``), because a
  candidate's bloc can differ between cycles.

The one leak that cannot be closed is the pair above: the error scales. It is
reported in the output rather than buried here.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
from dataclasses import dataclass, field

import numpy as np
import yaml

from .config import (
    ElectionDates,
    ModelConfig,
    PollsConfig,
    Roster,
    load_model_config,
    load_roster,
)
from .data.polls import Hypothese
from .paths import CACHE, CONFIG

log = logging.getLogger(__name__)

ARCHIVE = CACHE / "nsppolls_2022.json"
ROSTER_2022 = CONFIG / "candidats_2022.yaml"

# Fixed by the 2022 calendar.
R1_2022 = dt.date(2022, 4, 10)
R2_2022 = dt.date(2022, 4, 24)
CLOTURE_2022 = dt.date(2022, 3, 4)  # Conseil constitutionnel published the field


def crps(draws: np.ndarray, actual: float) -> float:
    """Continuous ranked probability score for one candidate, from samples.

    Coverage says whether the truth fell inside an interval; it cannot tell a
    well-centred forecast from a vague one that happens to contain everything.
    CRPS scores the whole predictive distribution against what happened, and is
    proper - it cannot be improved by reporting something other than an honest
    belief. Lower is better, and it is in the units of the thing forecast, so a
    CRPS of 0.02 is two points of share.

        CRPS = E|X - y| - 0.5 * E|X - X'|

    The second term uses the sorted-sample identity rather than all pairs,
    which would be quadratic in the number of draws.
    """
    x = np.sort(np.asarray(draws, dtype=float))
    n = x.size
    if n == 0:
        return float("nan")
    term1 = np.abs(x - actual).mean()
    k = np.arange(1, n + 1)
    term2 = (2.0 / (n * n)) * np.sum((2 * k - n - 1) * x)
    return float(term1 - 0.5 * term2)


def load_roster_2022() -> Roster:
    """2022 candidates, mapped onto the SAME bloc definitions as 2027."""
    base = load_roster()  # for the bloc definitions and their colours
    with ROSTER_2022.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    from .config import Candidat

    candidats: dict[str, Candidat] = {}
    for cid, v in raw["candidats"].items():
        if v["bloc"] not in base.blocs:
            raise ValueError(f"2022 candidate {cid} has unknown bloc {v['bloc']!r}")
        candidats[cid] = Candidat(
            id=cid, nom=v["nom"], parti=v["parti"], bloc=v["bloc"]
        )
    return Roster(blocs=base.blocs, candidats=candidats)


def parse_nsppolls(
    payload: list[dict],
    *,
    roster: Roster,
    as_of: dt.date,
    history_start: dt.date,
) -> tuple[list[Hypothese], list[str]]:
    """Adapt the nsppolls archive to the same Hypothese objects as the live feed.

    nsppolls identifies candidates by NAME, not by a stable id, so the join is
    on the exact name string. It fails closed exactly as the live roster does:
    an unrecognised name skips the whole hypothesis rather than dropping one
    candidate and renormalising the rest upward.
    """
    by_name = {c.nom: cid for cid, c in roster.candidats.items()}
    out: list[Hypothese] = []
    skipped: list[str] = []

    for poll in payload:
        fin_raw = poll.get("fin_enquete")
        debut_raw = poll.get("debut_enquete") or fin_raw
        if not fin_raw:
            continue
        fin = dt.date.fromisoformat(fin_raw)
        # NO LOOKAHEAD: fieldwork must have finished by the as-of date.
        if fin > as_of or fin < history_start:
            continue
        debut = dt.date.fromisoformat(debut_raw)
        institut = (poll.get("nom_institut") or "").strip()
        n = poll.get("echantillon") or 0
        if not institut or not n:
            continue

        for tour in poll.get("tours") or []:
            label = str(tour.get("tour", "")).lower()
            tour_n = 1 if label.startswith("premier") else 2
            for hyp in tour.get("hypotheses") or []:
                cands = hyp.get("candidats") or []
                mapped: dict[str, float] = {}
                bad = None
                for c in cands:
                    name = c.get("candidat")
                    cid = by_name.get(name) if name else None
                    if cid is None:
                        bad = name
                        break
                    mapped[cid] = float(c.get("intentions") or 0)
                if bad is not None:
                    skipped.append(
                        f"{poll.get('id')} {hyp.get('hypothese')}: unknown candidate {bad!r}"
                    )
                    continue
                total = sum(mapped.values())
                if total <= 0 or not 95.0 <= total <= 105.0:
                    continue
                if tour_n == 2 and len(mapped) != 2:
                    continue
                out.append(
                    Hypothese(
                        poll_id=str(poll.get("id")),
                        institut=institut,
                        commanditaire=str(poll.get("commanditaire") or "").strip(),
                        debut=debut,
                        fin=fin,
                        echantillon=int(hyp.get("sous_echantillon") or n),
                        population=str(poll.get("population") or "").strip(),
                        hypothese=str(hyp.get("hypothese") or "").strip(),
                        tour=tour_n,
                        notice=str(poll.get("lien") or "").strip(),
                        shares={k: v / total for k, v in mapped.items()},
                    )
                )

    out.sort(key=lambda h: (h.fin, h.institut, h.hypothese))
    return out, skipped


def config_for_2022(base: ModelConfig, history_start: dt.date) -> ModelConfig:
    return dataclasses.replace(
        base,
        election=ElectionDates(
            premier_tour=R1_2022,
            second_tour=R2_2022,
            cloture_candidatures=CLOTURE_2022,
        ),
        polls=PollsConfig(history_start=history_start, grid_days=base.polls.grid_days),
    )


@dataclass
class BacktestScore:
    as_of: str
    days_out: int
    n_polls: int
    n_hypotheses: int
    rows: list[dict] = field(default_factory=list)
    coverage_90: float = 0.0
    coverage_50: float = 0.0
    p_qualify_actual: dict[str, float] = field(default_factory=dict)
    p_win_actual: float = 0.0
    predicted_top2: list[str] = field(default_factory=list)
    mae_points: float = 0.0
    crps_points: float = 0.0

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "days_out": self.days_out,
            "n_polls": self.n_polls,
            "n_hypotheses": self.n_hypotheses,
            "mae_points": round(self.mae_points, 2),
            "crps_points": round(self.crps_points, 3),
            "coverage_90": round(self.coverage_90, 3),
            "coverage_50": round(self.coverage_50, 3),
            "p_qualify_actual": {k: round(v, 3) for k, v in self.p_qualify_actual.items()},
            "p_win_actual": round(self.p_win_actual, 3),
            "predicted_top2": self.predicted_top2,
            "rows": self.rows,
        }


def score(result, roster: Roster, results_2022: dict, as_of: dt.date) -> BacktestScore:
    """Score a SimulationResult against what actually happened."""
    actual_total = float(results_2022["premier_tour"]["exprimes"])
    actual = {
        k: v["voix"] / actual_total
        for k, v in results_2022["premier_tour"]["candidats"].items()
    }
    # The results file keys on the Ministry's surnames; join through the poll
    # name mapping so the backtest and the calibration agree on identities.
    surname_of = results_2022["noms_sondages"]
    by_name = {c.nom: cid for cid, c in roster.candidats.items()}
    actual_by_id: dict[str, float] = {}
    for poll_name, surname in surname_of.items():
        cid = by_name.get(poll_name)
        if cid is not None and surname in actual:
            actual_by_id[cid] = actual[surname]

    quantiles = result.share_quantiles((0.05, 0.25, 0.5, 0.75, 0.95))
    p_qual = result.p_qualify()
    p_win = result.p_win()
    index = {c: i for i, c in enumerate(result.candidate_ids)}

    rows, inside90, inside50, errs, scores = [], 0, 0, [], []
    for cid, a in sorted(actual_by_id.items(), key=lambda kv: -kv[1]):
        i = index.get(cid)
        if i is None:
            continue
        q = quantiles[cid]
        if np.isnan(q[2]):
            continue
        # Scored on the same draws the intervals come from: conditional on
        # the candidate standing, which is what the site reports.
        col = result.shares[result.standing[:, i], i]
        scores.append(crps(col, a))
        in90 = bool(q[0] <= a <= q[4])
        in50 = bool(q[1] <= a <= q[3])
        inside90 += in90
        inside50 += in50
        errs.append(abs(q[2] - a) * 100)
        rows.append(
            {
                "id": cid,
                "nom": roster.candidats[cid].nom,
                "actual": round(a, 5),
                "q05": round(float(q[0]), 5),
                "q50": round(float(q[2]), 5),
                "q95": round(float(q[4]), 5),
                "inside_90": in90,
                "inside_50": in50,
                "p_qualify": round(float(p_qual[i]), 4),
                "p_win": round(float(p_win[i]), 4),
            }
        )

    n = max(len(rows), 1)
    finalists = ["EM", "MLP"]
    order = np.argsort(-np.array([r["q50"] for r in rows]))
    top2 = [rows[k]["id"] for k in order[:2]] if len(rows) >= 2 else []

    return BacktestScore(
        as_of=as_of.isoformat(),
        days_out=(R1_2022 - as_of).days,
        n_polls=0,
        n_hypotheses=0,
        rows=rows,
        coverage_90=inside90 / n,
        coverage_50=inside50 / n,
        p_qualify_actual={
            f: float(p_qual[index[f]]) for f in finalists if f in index
        },
        p_win_actual=float(p_win[index["EM"]]) if "EM" in index else 0.0,
        predicted_top2=top2,
        mae_points=float(np.mean(errs)) if errs else 0.0,
        crps_points=float(np.mean(scores)) * 100 if scores else 0.0,
    )


def load_archive() -> list[dict]:
    if not ARCHIVE.exists():
        raise FileNotFoundError(
            f"{ARCHIVE} not found. Fetch it with:\n"
            "  curl -sL -o data/cache/nsppolls_2022.json "
            "https://raw.githubusercontent.com/nsppolls/nsppolls/master/presidentielle.json"
        )
    return json.loads(ARCHIVE.read_text(encoding="utf-8"))


def default_config() -> ModelConfig:
    return load_model_config()

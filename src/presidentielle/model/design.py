"""Turn weighted hypotheses into the flat arrays the PyMC model consumes.

The awkward shape here is that hypotheses are **ragged**: one prices a field of
twelve candidates, the next prices nine, and no two need share a field. Rather
than padding to a rectangle and carrying a mask through every operation, the
observations are held in long format - one row per (hypothesis, candidate)
pair - and the model gathers into it. Raggedness then costs nothing.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

import numpy as np

from ..config import ModelConfig, Roster
from ..data.surveys import WeightedHypothese

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelData:
    # --- coordinates -------------------------------------------------
    candidate_ids: list[str]
    bloc_keys: list[str]
    institut_names: list[str]
    grid_dates: list[dt.date]

    # --- structure ---------------------------------------------------
    candidate_bloc: np.ndarray  # (C,) int, index into bloc_keys
    bloc_members: list[np.ndarray]  # per bloc, int indices into candidate_ids
    identified_blocs: np.ndarray  # (K,) bool - has >1 polled member

    # --- first-round observations, long format -----------------------
    obs_hyp: np.ndarray  # (N,) int, index into hypothesis arrays
    obs_cand: np.ndarray  # (N,) int, index into candidate_ids
    obs_y: np.ndarray  # (N,) float, observed share in [0, 1]
    obs_n: np.ndarray  # (N,) float, effective sample size

    # --- per-hypothesis arrays ---------------------------------------
    hyp_time: np.ndarray  # (H,) int, index into grid_dates
    hyp_institut: np.ndarray  # (H,) int, index into institut_names
    hyp_field: np.ndarray  # (H, C) bool, candidate present in this field

    # --- second round, kept aside for the runoff model ---------------
    runoffs: list[dict]

    # --- provenance ---------------------------------------------------
    meta: dict

    @property
    def n_candidates(self) -> int:
        return len(self.candidate_ids)

    @property
    def n_blocs(self) -> int:
        return len(self.bloc_keys)

    @property
    def n_hypotheses(self) -> int:
        return len(self.hyp_time)

    @property
    def n_steps(self) -> int:
        return len(self.grid_dates) - 1

    @property
    def election_index(self) -> int:
        """The grid ends on election day, so that is simply the last step."""
        return len(self.grid_dates) - 1


def _build_grid(start: dt.date, end: dt.date, step_days: int) -> list[dt.date]:
    """Weekly grid ending EXACTLY on election day.

    The grid is built backwards from the election so the final node is the day
    being forecast. This matters: because the fitted walk already reaches
    election day, no separate drift-to-election-day term is needed, and adding
    one would double-count the movement between now and April.
    """
    dates = [end]
    cur = end
    while cur > start:
        cur = cur - dt.timedelta(days=step_days)
        dates.append(cur)
    return sorted(dates)


def build_model_data(
    weighted: list[WeightedHypothese],
    *,
    cfg: ModelConfig,
    roster: Roster,
) -> ModelData:
    first = [w for w in weighted if w.hypothese.tour == 1]
    second = [w for w in weighted if w.hypothese.tour == 2]
    if not first:
        raise ValueError("no first-round hypotheses to fit")

    # Only candidates that actually appear in a poll get a latent state. A
    # politician nobody has tested has no data and would sample from the prior.
    candidate_ids = sorted({c for w in first for c in w.hypothese.shares})
    cand_index = {c: i for i, c in enumerate(candidate_ids)}

    bloc_keys = list(roster.blocs)
    bloc_index = {b: i for i, b in enumerate(bloc_keys)}
    candidate_bloc = np.array(
        [bloc_index[roster.candidats[c].bloc] for c in candidate_ids], dtype="int64"
    )

    bloc_members = [np.where(candidate_bloc == k)[0] for k in range(len(bloc_keys))]
    # A bloc with one polled member offers no within-bloc contrast, so its
    # nesting parameter is not identified by anything and is pinned instead of
    # being left to wander on its prior.
    identified = np.array([len(m) > 1 for m in bloc_members], dtype=bool)

    institut_names = sorted({w.hypothese.institut for w in first})
    institut_index = {n: i for i, n in enumerate(institut_names)}

    grid = _build_grid(
        cfg.polls.history_start, cfg.election.premier_tour, cfg.polls.grid_days
    )
    grid_arr = np.array([d.toordinal() for d in grid])

    hyp_time: list[int] = []
    hyp_institut: list[int] = []
    hyp_field = np.zeros((len(first), len(candidate_ids)), dtype=bool)
    obs_hyp: list[int] = []
    obs_cand: list[int] = []
    obs_y: list[float] = []
    obs_n: list[float] = []

    for h, w in enumerate(first):
        hp = w.hypothese
        # Snap to the nearest grid node. With a weekly grid the worst error is
        # three days, which is far inside the noise of a single poll.
        t = int(np.argmin(np.abs(grid_arr - hp.midpoint.toordinal())))
        hyp_time.append(t)
        hyp_institut.append(institut_index[hp.institut])
        for cid, share in hp.shares.items():
            j = cand_index[cid]
            hyp_field[h, j] = True
            obs_hyp.append(h)
            obs_cand.append(j)
            obs_y.append(share)
            obs_n.append(w.n_effective)

    runoffs = [
        {
            "poll_id": w.hypothese.poll_id,
            "institut": w.hypothese.institut,
            "fin": w.hypothese.fin,
            "n_effective": w.n_effective,
            "shares": dict(w.hypothese.shares),
            "notice": w.hypothese.notice,
        }
        for w in second
    ]

    meta = {
        "n_first_round_hypotheses": len(first),
        "n_second_round_hypotheses": len(second),
        "n_surveys": len({w.hypothese.survey_key for w in weighted}),
        "candidates": candidate_ids,
        "instituts": institut_names,
        "grid_start": grid[0].isoformat(),
        "grid_end": grid[-1].isoformat(),
        "n_grid": len(grid),
        "unidentified_blocs": [
            bloc_keys[k] for k in range(len(bloc_keys)) if not identified[k]
        ],
    }
    log.info(
        "design: %d candidates, %d blocs (%d identified), %d instituts, %d grid nodes, %d obs",
        len(candidate_ids),
        len(bloc_keys),
        int(identified.sum()),
        len(institut_names),
        len(grid),
        len(obs_y),
    )

    return ModelData(
        candidate_ids=candidate_ids,
        bloc_keys=bloc_keys,
        institut_names=institut_names,
        grid_dates=grid,
        candidate_bloc=candidate_bloc,
        bloc_members=bloc_members,
        identified_blocs=identified,
        obs_hyp=np.array(obs_hyp, dtype="int64"),
        obs_cand=np.array(obs_cand, dtype="int64"),
        obs_y=np.array(obs_y, dtype="float64"),
        obs_n=np.array(obs_n, dtype="float64"),
        hyp_time=np.array(hyp_time, dtype="int64"),
        hyp_institut=np.array(hyp_institut, dtype="int64"),
        hyp_field=hyp_field,
        runoffs=runoffs,
        meta=meta,
    )

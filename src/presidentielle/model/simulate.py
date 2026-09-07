"""From posterior draws to a forecast.

Each simulation is one coherent world:

1. a posterior draw of candidate strengths on election day and of the nesting
   parameters;
2. a **ballot** - who is actually standing, drawn from the arbitrations;
3. **election-day error**, correlated within blocs, because an institute that
   under-reads the RN under-reads every RN candidate at once;
4. first-round shares, by nested logit over that ballot;
5. the top two, and the runoff between them.

The order matters. Applying the error before the softmax rather than to the
shares keeps every share positive and every field summing to one, and makes a
candidate polling 4% carry a smaller absolute error than one polling 34% -
which is what historical misses look like.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from ..config import ModelConfig

log = logging.getLogger(__name__)

# A share error of `r1_share_error_sd` is quoted for a candidate in the middle
# of the field. Converting it to the strength scale divides by the slope of the
# softmax there, p(1-p) at this reference share.
REFERENCE_SHARE = 0.25


def nested_logit_shares(
    strength: np.ndarray,  # (S, C)
    lam: np.ndarray,  # (S, K)
    field: np.ndarray,  # (S, C) bool
    candidate_bloc: np.ndarray,  # (C,)
    n_blocs: int,
) -> np.ndarray:
    """Vectorised numpy twin of the PyTensor likelihood. (S, C) shares."""
    NEG = -1.0e9
    lam_c = lam[:, candidate_bloc]  # (S, C)
    scaled = np.where(field, strength / lam_c, NEG)

    S = strength.shape[0]
    lse_k = np.full((S, n_blocs), NEG)
    iv_k = np.full((S, n_blocs), NEG)
    for k in range(n_blocs):
        members = np.where(candidate_bloc == k)[0]
        if len(members) == 0:
            continue
        sub = scaled[:, members]
        present = field[:, members].any(axis=1)
        mx = sub.max(axis=1)
        lse = mx + np.log(np.exp(sub - mx[:, None]).sum(axis=1))
        lse = np.where(present, lse, NEG)
        lse_k[:, k] = lse
        iv_k[:, k] = np.where(present, lam[:, k] * lse, NEG)

    mx = iv_k.max(axis=1)
    lse_blocs = mx + np.log(np.exp(iv_k - mx[:, None]).sum(axis=1))

    log_p = (
        scaled
        - lse_k[np.arange(S)[:, None], candidate_bloc[None, :]]
        + iv_k[np.arange(S)[:, None], candidate_bloc[None, :]]
        - lse_blocs[:, None]
    )
    p = np.exp(log_p)
    return np.where(field, p, 0.0)


@dataclass
class SimulationResult:
    candidate_ids: list[str]
    shares: np.ndarray  # (S, C) first-round shares, 0 where not standing
    standing: np.ndarray  # (S, C) bool
    finalists: np.ndarray  # (S, 2) candidate indices
    winner: np.ndarray  # (S,) candidate index
    runoff_share: np.ndarray  # (S,) winner's share of expressed votes
    n_sims: int

    def p_standing(self) -> np.ndarray:
        return self.standing.mean(axis=0)

    def p_qualify(self) -> np.ndarray:
        out = np.zeros(len(self.candidate_ids))
        for j in range(2):
            np.add.at(out, self.finalists[:, j], 1.0)
        return out / self.n_sims

    def p_win(self) -> np.ndarray:
        out = np.zeros(len(self.candidate_ids))
        np.add.at(out, self.winner, 1.0)
        return out / self.n_sims

    def share_quantiles(self, qs=(0.05, 0.25, 0.5, 0.75, 0.95)) -> dict[str, np.ndarray]:
        """Quantiles conditional on standing - an unconditional quantile would
        mix in the zeros of every world where the candidate is not on the
        ballot, and report a 5th percentile of 0% for everybody."""
        out = {}
        for i, _ in enumerate(self.candidate_ids):
            mask = self.standing[:, i]
            col = self.shares[mask, i]
            out[self.candidate_ids[i]] = (
                np.quantile(col, qs) if col.size else np.full(len(qs), np.nan)
            )
        return out


def simulate(
    *,
    strength_draws: np.ndarray,  # (D, C)
    lambda_draws: np.ndarray,  # (D, K)
    runoff_draws: dict,  # arrays of (D2, ...) posterior draws
    fields: np.ndarray,  # (S, C) bool, one ballot per simulation
    candidate_bloc: np.ndarray,
    n_blocs: int,
    rn_index: int,
    cfg: ModelConfig,
    rng: np.random.Generator,
    candidate_ids: list[str],
) -> SimulationResult:
    S = fields.shape[0]
    D = strength_draws.shape[0]
    pick = rng.integers(0, D, size=S)
    strength = strength_draws[pick]
    lam = lambda_draws[pick]

    # ---- election-day error, correlated within bloc --------------------
    scale = cfg.election_day_error.r1_share_error_sd / (REFERENCE_SHARE * (1 - REFERENCE_SHARE))
    rho = cfg.election_day_error.bloc_error_corr
    common = rng.standard_normal((S, n_blocs))[:, candidate_bloc]
    idio = rng.standard_normal((S, len(candidate_ids)))
    err = scale * (np.sqrt(rho) * common + np.sqrt(1.0 - rho) * idio)

    shares = nested_logit_shares(strength + err, lam, fields, candidate_bloc, n_blocs)

    # ---- top two -------------------------------------------------------
    # Candidates not standing hold share 0 and cannot be picked, unless a
    # simulation somehow produced fewer than two candidates - which the ballot
    # model prevents, but assert rather than silently rank zeros.
    if (fields.sum(axis=1) < 2).any():
        raise ValueError("a simulated ballot has fewer than two candidates")
    order = np.argsort(-shares, axis=1)
    finalists = order[:, :2]

    # ---- runoff --------------------------------------------------------
    D2 = len(runoff_draws["gamma"])
    pick2 = rng.integers(0, D2, size=S)
    positions = runoff_draws["positions"][pick2]  # (S, K)
    gamma = runoff_draws["gamma"][pick2]
    delta = runoff_draws["delta"][pick2]
    abstain = runoff_draws["abstain"][pick2]  # (S, K)

    pair_bloc = candidate_bloc[finalists]  # (S, 2)
    rows = np.arange(S)
    own = np.stack([shares[rows, finalists[:, 0]], shares[rows, finalists[:, 1]]], axis=1)

    elim = shares.copy()
    elim[rows, finalists[:, 0]] = 0.0
    elim[rows, finalists[:, 1]] = 0.0
    source = np.zeros((S, n_blocs))
    for k in range(n_blocs):
        members = np.where(candidate_bloc == k)[0]
        if len(members):
            source[:, k] = elim[:, members].sum(axis=1)

    # predict_numpy is written for shared parameters across rows; here every
    # row has its own draw, so it is applied rowwise via the same arithmetic.
    share_a = _predict_rowwise(
        positions, gamma, delta, abstain, pair_bloc, source, own, rn_index
    )
    share_a = share_a + rng.standard_normal(S) * cfg.election_day_error.r2_margin_error_sd
    share_a = np.clip(share_a, 0.0, 1.0)

    a_wins = share_a > 0.5
    winner = np.where(a_wins, finalists[:, 0], finalists[:, 1])
    runoff_share = np.where(a_wins, share_a, 1.0 - share_a)

    return SimulationResult(
        candidate_ids=candidate_ids,
        shares=shares,
        standing=fields,
        finalists=finalists,
        winner=winner,
        runoff_share=runoff_share,
        n_sims=S,
    )


def _predict_rowwise(positions, gamma, delta, abstain, pair_bloc, source, own, rn_index):
    rows = np.arange(positions.shape[0])
    xa = positions[rows, pair_bloc[:, 0]][:, None]
    xb = positions[rows, pair_bloc[:, 1]][:, None]
    xj = positions  # (S, K)

    ua = -gamma[:, None] * (xj - xa) ** 2 - delta[:, None] * (pair_bloc[:, 0] == rn_index)[:, None]
    ub = -gamma[:, None] * (xj - xb) ** 2 - delta[:, None] * (pair_bloc[:, 1] == rn_index)[:, None]

    stack = np.stack([ua, ub, abstain], axis=2)
    stack = stack - stack.max(axis=2, keepdims=True)
    e = np.exp(stack)
    p = e / e.sum(axis=2, keepdims=True)

    to_a = (source * p[:, :, 0]).sum(axis=1) + own[:, 0]
    to_b = (source * p[:, :, 1]).sum(axis=1) + own[:, 1]
    total = to_a + to_b
    return np.where(total > 0, to_a / np.maximum(total, 1e-12), 0.5)


def matchup_table(result: SimulationResult, min_prob: float = 0.005) -> list[dict]:
    """Every runoff pairing the simulation actually produced, with its odds."""
    pairs: dict[tuple[int, int], list[int]] = {}
    for s in range(result.n_sims):
        a, b = result.finalists[s]
        key = (a, b) if a < b else (b, a)
        pairs.setdefault(key, []).append(s)

    rows = []
    for (a, b), idx in pairs.items():
        p = len(idx) / result.n_sims
        if p < min_prob:
            continue
        wins_a = sum(1 for s in idx if result.winner[s] == a)
        rows.append(
            {
                "a": result.candidate_ids[a],
                "b": result.candidate_ids[b],
                "p_matchup": p,
                "p_a_wins": wins_a / len(idx),
                "n": len(idx),
            }
        )
    rows.sort(key=lambda r: -r["p_matchup"])
    return rows

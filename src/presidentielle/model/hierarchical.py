"""The hierarchical dynamic nested-logit model.

WHY NOT A SOFTMAX
-----------------
The obvious model for multi-candidate vote shares gives each candidate a
latent strength and takes a softmax over whoever is on the ballot. That model
assumes **independence of irrelevant alternatives**: if Le Pen leaves the
ballot, her 34% is redistributed across the remaining candidates in proportion
to their existing support, so Melenchon gains about as much per point of his
own support as Bardella does.

That is not what happens, and the data say so directly. Pollsters have priced
86 fields containing Le Pen and 79 containing Bardella; the RN total barely
moves between them while every other candidate's share is nearly unchanged.
Under IIA the model cannot represent that at all.

WHAT IS FITTED INSTEAD
----------------------
Candidates sit in **blocs**, and each bloc has a nesting parameter
``lambda_k`` in (0, 1]. Writing ``u_c`` for a candidate's strength and ``F``
for the field on the ballot::

    within bloc      log P(c | k) = u_c/lambda_k - LSE_k
    inclusive value  IV_k         = lambda_k * LSE_k
    between blocs    log P(k)     = IV_k - LSE_blocs

    where  LSE_k     = logsumexp over the bloc's members present in F of u/lambda_k
           LSE_blocs = logsumexp over the blocs present in F of IV_k

    log p_c = u_c/lambda_k - LSE_k + IV_k - LSE_blocs

At ``lambda = 1`` this collapses exactly to the plain softmax, so IIA is
nested inside the model rather than assumed away. As ``lambda -> 0``
substitution inside the bloc becomes total: removing Le Pen sends her support
to Bardella and leaves the other blocs untouched, while the RN's own total
still moves to reflect that Bardella is a different candidate. That is the
behaviour the data show, and lambda is estimated, not asserted.

The parameter is only identified for a bloc that has been polled both with and
without a given member. For the RN and the centre that is most of the file;
blocs with a single polled candidate are pinned to 1.

IDENTIFIABILITY
---------------
1. The softmax is shift-invariant, so adding a constant to every candidate's
   strength changes nothing. The latent state is therefore **centred across
   candidates at every time step**, which removes exactly that one degree of
   freedom.
2. House effects are **sum-to-zero across institutes** within each bloc. Left
   free, a constant moves between the house effects and the latent state for
   an identical likelihood and the sampler wanders along that ridge forever.
3. Every random walk is **non-centred** - a cumulative sum of standard normals
   scaled by a separately sampled SD. Centred walks produce funnel geometry
   and sample badly.
4. A candidate's strength is a bloc-level walk plus its own deviation. The
   common component has to live somewhere: without the bloc term it reappears
   as correlated candidate deviations, which is the same ridge again.
"""

from __future__ import annotations

import logging

import numpy as np
import pymc as pm
import pytensor.tensor as pt

from ..config import ModelConfig
from .design import ModelData

log = logging.getLogger(__name__)

# Masking constant for candidates and blocs absent from a field. A finite
# stand-in for -inf: exp() of it is exactly zero in float64, so absent options
# contribute nothing, while gradients stay finite instead of turning into NaN
# the first time the sampler touches them.
NEG = -1.0e9


def _nested_logit_logp(
    u: pt.TensorVariable,
    lam: pt.TensorVariable,
    data: ModelData,
) -> pt.TensorVariable:
    """log p for every (hypothesis, candidate) cell. Absent cells are junk.

    ``u`` is (H, C) utilities, ``lam`` is (K,) nesting parameters.
    """
    field = pt.as_tensor_variable(data.hyp_field)  # (H, C) bool constant
    lam_c = lam[data.candidate_bloc]  # (C,)

    scaled = pt.where(field, u / lam_c, NEG)  # (H, C)

    lse_k, iv_k = [], []
    for k, members in enumerate(data.bloc_members):
        if len(members) == 0:
            # A bloc with no polled candidate can never be present.
            zeros = pt.zeros((u.shape[0],))
            lse_k.append(zeros + NEG)
            iv_k.append(zeros + NEG)
            continue
        present = pt.as_tensor_variable(data.hyp_field[:, members].any(axis=1))
        lse = pt.logsumexp(scaled[:, members], axis=1)
        lse = pt.where(present, lse, NEG)
        lse_k.append(lse)
        iv_k.append(pt.where(present, lam[k] * lse, NEG))

    lse_stack = pt.stack(lse_k, axis=1)  # (H, K)
    iv_stack = pt.stack(iv_k, axis=1)  # (H, K)
    lse_blocs = pt.logsumexp(iv_stack, axis=1)  # (H,)

    lse_of_c = lse_stack[:, data.candidate_bloc]  # (H, C)
    iv_of_c = iv_stack[:, data.candidate_bloc]  # (H, C)

    return scaled - lse_of_c + iv_of_c - lse_blocs[:, None]


def build_model(data: ModelData, cfg: ModelConfig) -> pm.Model:
    grid_days = cfg.grid_days
    # Random-walk variance is additive in time, so a step spanning `grid_days`
    # days has SD sqrt(grid_days) times the per-day figure.
    cand_step = cfg.latent.rw_sd_per_day_prior * np.sqrt(grid_days)
    bloc_step = cfg.latent.bloc_rw_sd_per_day_prior * np.sqrt(grid_days)

    coords = {
        "candidat": data.candidate_ids,
        "bloc": data.bloc_keys,
        "institut": data.institut_names,
        "grid": [d.isoformat() for d in data.grid_dates],
        "grid_step": list(range(data.n_steps)),
        "obs": list(range(len(data.obs_y))),
    }

    C = data.n_candidates
    K = data.n_blocs
    identified = data.identified_blocs
    n_identified = int(identified.sum())

    with pm.Model(coords=coords) as model:
        # ------------------------------------------------------------------
        # Latent strength: a bloc-level walk plus a candidate deviation, both
        # non-centred, then centred across candidates for identifiability.
        # ------------------------------------------------------------------
        # The walk scales are PINNED to the measured values by default.
        #
        # Left free they do not identify against a 146-node weekly grid backed
        # by 39 surveys: the walk is far more flexible than the observation
        # noise term, so the model explains poll-to-poll scatter by moving the
        # latent state rather than by measurement error. Measured, with them
        # free: the posterior walk came out at 0.0337/day against the 0.0142
        # measured from real polls - 2.4x - while sigma_excess collapsed to
        # 0.0011, i.e. the model claimed French polls have essentially no
        # non-sampling error. That inflated volatility then compounds over ~32
        # unconstrained steps to election day and sets every interval on the
        # site.
        #
        # A weak prior cannot fix this; the likelihood simply overrides it.
        # Pinning is the honest option because these are not free parameters
        # we lack information about - scripts/fit_walk_scale.py measures
        # exactly this quantity, from real French polls, net of sampling noise.
        if cfg.latent.pin_walk_scales:
            sigma_bloc = pt.constant(bloc_step, dtype="float64")
            sigma_cand = pt.constant(cand_step, dtype="float64")
        else:
            sigma_bloc = pm.HalfNormal("sigma_bloc", sigma=bloc_step)
            sigma_cand = pm.HalfNormal("sigma_cand", sigma=cand_step)

        # NO bloc_start. A starting level per bloc would be exactly absorbed by
        # the starting levels of its own members, which is nine redundant
        # dimensions and a ridge the sampler cannot get off. The bloc walk
        # carries *movement* only; levels live on the candidates.
        cand_start = pm.Normal("cand_start", 0.0, cfg.latent.initial_sd, dims="candidat")

        # Bloc walks exist only for blocs with more than one polled candidate.
        # With a single member the bloc innovation and that candidate's own
        # innovation are exchangeable at every one of the ~145 steps - the same
        # ridge again, and far larger.
        walking = np.where(identified)[0]
        bloc_innov = pm.Normal(
            "bloc_innov", 0.0, 1.0, shape=(data.n_steps, len(walking))
        )
        cand_innov = pm.Normal("cand_innov", 0.0, 1.0, dims=("grid_step", "candidat"))

        bloc_walk = pt.zeros((data.n_steps + 1, K))
        bloc_walk = pt.set_subtensor(
            bloc_walk[1:, walking], pt.cumsum(bloc_innov, axis=0) * sigma_bloc
        )
        bloc_level = bloc_walk  # (T, K)
        cand_dev = cand_start + pt.concatenate(
            [pt.zeros((1, C)), pt.cumsum(cand_innov, axis=0) * sigma_cand], axis=0
        )  # (T, C)

        strength_raw = bloc_level[:, data.candidate_bloc] + cand_dev  # (T, C)
        strength = pm.Deterministic(
            "strength",
            strength_raw - strength_raw.mean(axis=1, keepdims=True),
            dims=("grid", "candidat"),
        )

        # ------------------------------------------------------------------
        # Nesting parameters. Pinned to 1 (plain softmax, IIA) for any bloc
        # with fewer than two polled candidates, because nothing in the data
        # could distinguish its lambda from its prior.
        # ------------------------------------------------------------------
        if n_identified:
            lam_free = pm.Beta(
                "lambda_free",
                alpha=cfg.nesting.prior_a,
                beta=cfg.nesting.prior_b,
                shape=n_identified,
            )
            lam = pt.ones(K)
            lam = pt.set_subtensor(lam[np.where(identified)[0]], lam_free)
        else:  # pragma: no cover - would mean no bloc has two polled members
            lam = pt.ones(K)
        lam = pm.Deterministic("lambda_bloc", lam, dims="bloc")

        # ------------------------------------------------------------------
        # House effects, per institute x bloc, sum-to-zero across institutes.
        # ------------------------------------------------------------------
        house = pm.ZeroSumNormal(
            "house_effect",
            sigma=cfg.house_effects.sd_prior,
            dims=("institut", "bloc"),
            n_zerosum_axes=1,
        )

        # ------------------------------------------------------------------
        # Utilities per (hypothesis, candidate), then the nested-logit shares.
        # ------------------------------------------------------------------
        u = strength[data.hyp_time] + house[data.hyp_institut][:, data.candidate_bloc]
        log_p = _nested_logit_logp(u, lam, data)
        p = pt.exp(log_p)  # (H, C)

        p_obs = p[data.obs_hyp, data.obs_cand]
        p_obs = pt.clip(p_obs, 1e-6, 1.0 - 1e-6)

        # Sampling variance from the effective sample size, plus non-sampling
        # noise the sample size does not explain. Only the excess term is a
        # free parameter; the binomial part is arithmetic.
        sigma_excess = pm.HalfNormal("sigma_excess", sigma=cfg.observation.excess_sd_prior)
        sd = pt.sqrt(p_obs * (1.0 - p_obs) / data.obs_n + sigma_excess**2)

        pm.Normal("obs_tour1", mu=p_obs, sigma=sd, observed=data.obs_y, dims="obs")

        # Shares on election day, for the simulation stage to consume.
        pm.Deterministic("strength_election", strength[data.election_index], dims="candidat")

    return model


def sample(model: pm.Model, cfg: ModelConfig, *, progressbar: bool = True):
    """Sample with nutpie, falling back to PyMC's own NUTS if unavailable."""
    kwargs = dict(
        draws=cfg.sampling.draws,
        tune=cfg.sampling.tune,
        chains=cfg.sampling.chains,
        target_accept=cfg.sampling.target_accept,
        random_seed=cfg.sampling.seed,
        progressbar=progressbar,
    )
    with model:
        try:
            return pm.sample(nuts_sampler="nutpie", **kwargs)
        except (ImportError, ValueError) as exc:  # pragma: no cover
            log.warning("nutpie unavailable (%s); falling back to PyMC NUTS", exc)
            return pm.sample(**kwargs)

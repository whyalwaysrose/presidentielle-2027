"""Command line entry point.

    presidentielle fetch      refresh the cached poll file
    presidentielle audit      what the data contains, and what was skipped
    presidentielle run        fit, simulate, write site/data/forecast.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys

# PyTensor looks for a C++ compiler it does not need here; sampling goes
# through nutpie (Numba). Set before the scientific stack is imported.
os.environ.setdefault("PYTENSOR_FLAGS", "cxx=")

import numpy as np  # noqa: E402

from . import paths  # noqa: E402
from .config import load_model_config, load_roster  # noqa: E402
from .data import polls, surveys  # noqa: E402

log = logging.getLogger("presidentielle")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _load(cfg, roster, *, force: bool = False):
    hyps, skipped = polls.load(
        roster=roster, history_start=cfg.polls.history_start, force=force
    )
    weighted = surveys.weight(hyps, exponent=cfg.observation.survey_weight_exponent)
    return hyps, weighted, skipped


def cmd_fetch(args) -> int:
    cfg = load_model_config()
    roster = load_roster()
    hyps, weighted, skipped = _load(cfg, roster, force=True)
    s = surveys.summarise(weighted)
    print(f"{s['surveys']} surveys, {s['hypotheses']} hypotheses "
          f"({s['hypotheses_tour1']} first round, {s['hypotheses_tour2']} second)")
    print(f"latest: {s['date_max']}")
    if skipped:
        print(f"{len(skipped)} record(s) skipped:")
        for line in skipped:
            print("  ", line)
    return 0


def cmd_audit(args) -> int:
    cfg = load_model_config()
    roster = load_roster()
    hyps, weighted, skipped = _load(cfg, roster)
    from .model.field import build_ballot_model

    s = surveys.summarise(weighted)
    as_of = max(h.fin for h in hyps)
    print(f"as of {as_of} - {(cfg.election.premier_tour - as_of).days} days to the first round")
    print(f"{s['surveys']} surveys -> {s['hypotheses_tour1']} first-round hypotheses")
    print(f"raw sample {s['raw_sample_tour1']:,} -> effective {s['effective_sample_tour1']:,}")
    print(f"instituts: {', '.join(s['instituts'])}")
    print()

    ballot = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=as_of)
    print("Ballot arbitrations (mutually exclusive candidacies):")
    for a in ballot.arbitrations:
        opts = ", ".join(
            f"{roster.candidats[c].nom} {p:.0%}"
            for c, p in zip(a.options, a.probabilities, strict=True)
        )
        print(f"  {a.bloc:16s} {opts}, none {a.p_none:.0%}")
    print()
    print("Independent candidacies (P on the ballot):")
    for cid, p in sorted(ballot.independent.items(), key=lambda kv: -kv[1]):
        if p >= 0.01:
            print(f"  {roster.candidats[cid].nom:28s} {p:5.0%}")

    if skipped:
        print()
        print(f"{len(skipped)} record(s) skipped:")
        for line in skipped:
            print("  ", line)
    return 0


def cmd_calibrate(args) -> int:
    """Fit the election-day error against the 2022 cycle."""
    from .calibration import calibrate

    cfg = load_model_config()
    res = calibrate()

    print("2022 first round, each institute's final poll within 14 days of the vote")
    print(f"  {res.n_polls} polls, {res.n_institutes} institutes, "
          f"{res.n_observations} candidate observations")
    print()
    print(f"  log-share error SD        {res.log_error_sd:.4f}")
    print(f"  mean signed log error     {res.mean_signed_log_error:+.4f}  "
          f"(a whole-field bias would show here)")
    print(f"  within-bloc correlation   {res.bloc_error_corr:.3f}")
    print()
    print("  largest average misses (log scale, + means the polls over-read):")
    for name, err in res.worst:
        print(f"    {name:16s} {err:+.3f}")
    print()
    print("FITTED VALUES for config/model.yaml -> election_day_error:")
    print(f"  r1_share_error_sd: {res.r1_share_error_sd:.4f}")
    print(f"  bloc_error_corr:   {res.bloc_error_corr:.3f}")
    if res.r2_error_points is not None:
        print()
        print(f"  second round: {res.r2_n_polls} final polls, mean miss on the "
              f"winner's share {res.r2_error_points:+.2f} points.")
        print("  ONE cycle and ONE matchup - reported, not fitted. r2_margin_error_sd")
        print("  stays a prior until a second cycle is available.")
    print()
    cur = cfg.election_day_error
    drift = abs(cur.r1_share_error_sd - res.r1_share_error_sd)
    print(f"config currently has r1_share_error_sd: {cur.r1_share_error_sd:.4f} "
          f"({'matches' if drift < 5e-4 else 'DIFFERS from'} the fit)")
    return 0


def cmd_run(args) -> int:
    import arviz as az

    from .calibration import load_results
    from .commentary import write_commentary
    from .data.transfers import load as load_transfers
    from .model.design import build_model_data
    from .model.field import build_ballot_model, draw_fields, fixed_field
    from .model.hierarchical import build_model, sample
    from .model.runoff import build_runoff_data, build_runoff_model
    from .model.simulate import simulate
    from .outputs import build_forecast, model_fingerprint, write_json

    paths.ensure_dirs()
    cfg = load_model_config()
    if args.draws:
        # Smoke-test override. Never used for a published run: the workflow
        # calls `run` with no overrides so the config alone decides.
        from dataclasses import replace
        cfg = replace(cfg, sampling=replace(cfg.sampling, draws=args.draws,
                                            tune=args.draws, chains=2,
                                            sims_per_draw=4))
        log.warning("SMOKE TEST: draws=%d, results are not publishable", args.draws)
    roster = load_roster()
    hyps, weighted, skipped = _load(cfg, roster, force=args.refresh)
    data = build_model_data(weighted, cfg=cfg, roster=roster)
    as_of = max(h.fin for h in hyps)

    log.info("fitting first-round model")
    model = build_model(data, cfg)
    idata = sample(model, cfg, progressbar=not args.quiet)

    post = idata.posterior
    strength_draws = post["strength_election"].stack(d=("chain", "draw")).values.T
    lambda_draws = post["lambda_bloc"].stack(d=("chain", "draw")).values.T
    log.info("posterior: %d draws", strength_draws.shape[0])

    # Runoff stage, on posterior-mean first-round shares under the reference
    # ballot (see runoff.py on why two stages is acceptable here).
    ballot = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=as_of)
    reference = _reference_field(ballot, data.candidate_ids)
    ref_shares = _reference_shares(
        reference, ballot, data, strength_draws, lambda_draws
    )

    log.info("fitting runoff transfer model on %d hypotheses", len(data.runoffs))
    rdata = build_runoff_data(
        data.runoffs,
        candidate_ids=data.candidate_ids,
        bloc_keys=data.bloc_keys,
        candidate_bloc=data.candidate_bloc,
        r1_shares=ref_shares,
        roster=roster,
    )
    # Anchor the transfer model on the 2022 measurements. Without them the
    # front republicain is estimated only from hypothetical 2027 matchups.
    try:
        transfers, t_skipped = load_transfers(results=load_results())
        for line in t_skipped:
            log.warning("2022 transfers: %s", line)
        log.info("anchoring runoff on %d measured 2022 transfers", len(transfers))
    except FileNotFoundError as exc:
        log.warning("no 2022 transfers (%s); runoff rests on 2027 polls alone", exc)
        transfers = None

    rmodel = build_runoff_model(rdata, cfg, data.bloc_keys, transfers=transfers)
    with rmodel:
        ridata = __import__("pymc").sample(
            draws=cfg.sampling.draws,
            tune=cfg.sampling.tune,
            chains=cfg.sampling.chains,
            target_accept=cfg.sampling.target_accept,
            random_seed=cfg.sampling.seed + 1,
            progressbar=not args.quiet,
            nuts_sampler="nutpie",
        )
    rp = ridata.posterior
    # Does the transfer model reproduce the runoffs it was fitted to? This is
    # the check that matters most for P(win): the runoff decides the
    # presidency, and a transfer model that misses the tested matchups is
    # asserting something the polls contradict.
    _mu = rp["mu"].mean(("chain", "draw")).values
    _resid = _mu - rdata.y
    _worst = int(np.argmax(np.abs(_resid)))
    runoff_fit = {
        "mae_points": round(float(np.abs(_resid).mean()) * 100, 2),
        "bias_points": round(float(_resid.mean()) * 100, 2),
        "worst_matchup": rdata.labels[_worst],
        "worst_error_points": round(float(_resid[_worst]) * 100, 2),
    }
    log.info(
        "runoff fit: MAE %.2f pts, bias %+.2f pts, worst %s %+.1f pts",
        runoff_fit["mae_points"], runoff_fit["bias_points"],
        runoff_fit["worst_matchup"], runoff_fit["worst_error_points"],
    )
    runoff_draws = {
        "positions": rp["positions"].stack(d=("chain", "draw")).values.T,
        "gamma": rp["gamma"].stack(d=("chain", "draw")).values,
        "delta": rp["delta_front_republicain"].stack(d=("chain", "draw")).values,
        "abstain": rp["abstain"].stack(d=("chain", "draw")).values.T,
    }

    rng = np.random.default_rng(cfg.sampling.seed)
    n_sims = strength_draws.shape[0] * cfg.sampling.sims_per_draw

    if args.scenario:
        fields = fixed_field(data.candidate_ids, args.scenario.split(","), n_sims)
        scenario_name = args.scenario
    else:
        fields = draw_fields(ballot, data.candidate_ids, n_sims, rng)
        scenario_name = "modele"

    log.info("simulating %d worlds", n_sims)
    result = simulate(
        strength_draws=strength_draws,
        lambda_draws=lambda_draws,
        runoff_draws=runoff_draws,
        fields=fields,
        candidate_bloc=data.candidate_bloc,
        n_blocs=data.n_blocs,
        rn_index=data.bloc_keys.index("rn"),
        cfg=cfg,
        rng=rng,
        candidate_ids=data.candidate_ids,
    )

    trend = _build_trend(post, reference, data, cfg)
    summary = surveys.summarise(weighted)
    recent = _recent_polls(hyps, roster, limit=12)

    diag = {
        "min_ess_bulk": float(az.ess(idata, var_names=["strength_election"])
                              ["strength_election"].min()),
        "max_rhat": float(az.rhat(idata, var_names=["strength_election"])
                          ["strength_election"].max()),
        "lambda_bloc": {
            b: round(float(post["lambda_bloc"].mean(("chain", "draw")).values[i]), 3)
            for i, b in enumerate(data.bloc_keys)
        },
        "delta_front_republicain": round(float(rp["delta_front_republicain"].mean()), 3),
        "n_transferts_2022": 0 if transfers is None else len(transfers),
        "runoff_fit": runoff_fit,
        "sigma_excess": round(float(post["sigma_excess"].mean()), 4),
        # Posterior walk scales, back on a per-day basis so they can be
        # compared directly with the fitted 0.0142 from fit_walk_scale.py.
        # Pinned scales are not in the posterior; report the config value so
        # the diagnostic line means the same thing either way.
        "sigma_cand_per_day": (
            cfg.latent.rw_sd_per_day_prior
            if cfg.latent.pin_walk_scales
            else round(float(post["sigma_cand"].mean()) / np.sqrt(cfg.grid_days), 4)
        ),
        "sigma_bloc_per_day": (
            cfg.latent.bloc_rw_sd_per_day_prior
            if cfg.latent.pin_walk_scales
            else round(float(post["sigma_bloc"].mean()) / np.sqrt(cfg.grid_days), 4)
        ),
        "walk_scales_pinned": cfg.latent.pin_walk_scales,
        "skipped_records": len(skipped),
        "n_first_round_hypotheses": data.meta["n_first_round_hypotheses"],
        "n_second_round_hypotheses": data.meta["n_second_round_hypotheses"],
        "pinned_blocs": data.meta["unidentified_blocs"],
    }

    fingerprint = model_fingerprint(
        paths.MODEL_CONFIG,
        [
            paths.ROOT / "src/presidentielle/model/hierarchical.py",
            paths.ROOT / "src/presidentielle/model/simulate.py",
            paths.ROOT / "src/presidentielle/model/runoff.py",
            paths.ROOT / "src/presidentielle/model/field.py",
        ],
    )

    payload = build_forecast(
        result=result,
        roster=roster,
        cfg=cfg,
        ballot=ballot,
        trend=trend,
        poll_summary={k: str(v) if isinstance(v, dt.date) else v for k, v in summary.items()},
        recent_polls=recent,
        diagnostics=diag,
        fingerprint=fingerprint,
        as_of=as_of,
        scenario=scenario_name,
    )
    payload["commentaire"] = write_commentary(payload, roster)

    write_json(payload, paths.SITE_DATA / "forecast.json")
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    write_json(payload, paths.RUNS / f"{stamp}.json")

    print()
    print(f"as of {as_of} - {payload['election']['jours_restants']} days out")
    print(f"{'candidate':26s} {'P(ballot)':>10s} {'P(round 2)':>11s} {'P(win)':>8s}  first round")
    for c in payload["candidats"][:9]:
        q = c["share"]
        print(
            f"  {c['nom']:24s} {c['p_standing']:9.0%} {c['p_qualify']:10.0%} "
            f"{c['p_win']:7.0%}   {q['q50']:.1%} [{q['q05']:.1%}-{q['q95']:.1%}]"
        )
    print()
    print("most likely runoffs:")
    for d in payload["duels"][:5]:
        print(f"  {d['nom_a']} vs {d['nom_b']}: {d['p_matchup']:.0%} likely, "
              f"{d['nom_a']} wins {d['p_a_wins']:.0%}")
    print()
    print(f"max R-hat {diag['max_rhat']:.3f}, min ESS {diag['min_ess_bulk']:.0f}")
    return 0


def _reference_field(ballot, candidate_ids: list[str]) -> np.ndarray:
    """The single most likely ballot: each arbitration's favourite, plus every
    independent candidacy more likely than not."""
    present = {c for c, p in ballot.independent.items() if p >= 0.5}
    for arb in ballot.arbitrations:
        best = max(
            zip(arb.options, arb.probabilities, strict=True), key=lambda kv: kv[1]
        )
        if best[1] >= arb.p_none:
            present.add(best[0])
    row = np.array([c in present for c in candidate_ids], dtype=bool)
    if row.sum() < 2:  # pragma: no cover
        raise ValueError("reference ballot has fewer than two candidates")
    return row


def _reference_shares(
    reference: np.ndarray, ballot, data, strength_draws, lambda_draws
) -> np.ndarray:
    """A first-round share for EVERY polled candidate, not just the ones on the
    reference ballot.

    The runoff stage needs a base for each finalist of each tested matchup, and
    institutes test matchups involving candidates the reference ballot excludes
    - Bardella above all, since the RN arbitration resolves to Le Pen.

    Reading his share straight off the reference ballot gives ZERO, which is
    what it did: every Bardella runoff was fitted with him holding no
    first-round votes. It cost 14.5 points on Bardella-versus-Melenchon and
    inflated the whole runoff MAE from 1.97 to 3.54, while looking like tension
    between the 2022 and 2027 evidence.

    So a candidate missing from the reference ballot is priced on the ballot he
    would actually be on: his own arbitration resolved in his favour, or, for an
    independent candidacy, simply added.
    """
    from .model.simulate import nested_logit_shares

    strength = strength_draws.mean(axis=0)[None, :]
    lam = lambda_draws.mean(axis=0)[None, :]

    shares = nested_logit_shares(
        strength, lam, reference[None, :], data.candidate_bloc, data.n_blocs
    )[0]

    index = {c: i for i, c in enumerate(data.candidate_ids)}
    for j, cid in enumerate(data.candidate_ids):
        if reference[j]:
            continue
        field = reference.copy()
        # Drop whoever currently holds this candidate's arbitration slot, so
        # the bloc still fields exactly one.
        for arb in ballot.arbitrations:
            if cid in arb.options:
                for other in arb.options:
                    k = index.get(other)
                    if k is not None:
                        field[k] = False
                break
        field[j] = True
        alt = nested_logit_shares(
            strength, lam, field[None, :], data.candidate_bloc, data.n_blocs
        )[0]
        shares[j] = alt[j]
    return shares


def _build_trend(post, reference: np.ndarray, data, cfg) -> dict:
    """Median share over time under the reference ballot."""
    from .model.simulate import nested_logit_shares

    strength = post["strength"].mean(("chain", "draw")).values  # (T, C)
    lam = post["lambda_bloc"].mean(("chain", "draw")).values  # (K,)
    T = strength.shape[0]
    shares = nested_logit_shares(
        strength,
        np.repeat(lam[None, :], T, axis=0),
        np.repeat(reference[None, :], T, axis=0),
        data.candidate_bloc,
        data.n_blocs,
    )
    return {
        "dates": [d.isoformat() for d in data.grid_dates],
        "reference_field": [
            c for c, on in zip(data.candidate_ids, reference, strict=True) if on
        ],
        "series": {
            cid: [round(float(x), 5) for x in shares[:, i]]
            for i, cid in enumerate(data.candidate_ids)
            if reference[i]
        },
    }


def _recent_polls(hyps, roster, limit: int) -> list[dict]:
    from .data.polls import NOTICE_BASE

    first = sorted([h for h in hyps if h.tour == 1], key=lambda h: h.fin, reverse=True)
    seen: set = set()
    out = []
    for h in first:
        if h.survey_key in seen:
            continue
        seen.add(h.survey_key)
        top = sorted(h.shares.items(), key=lambda kv: -kv[1])[:4]
        out.append(
            {
                "institut": h.institut,
                "commanditaire": h.commanditaire,
                "debut": h.debut.isoformat(),
                "fin": h.fin.isoformat(),
                "echantillon": h.echantillon,
                "notice": h.notice,
                "notice_url": NOTICE_BASE if h.notice else "",
                "tete": [
                    {"id": c, "nom": roster.candidats[c].nom, "part": round(v, 4)}
                    for c, v in top
                ],
            }
        )
        if len(out) >= limit:
            break
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="presidentielle")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fetch", help="refresh the cached poll file").set_defaults(fn=cmd_fetch)
    sub.add_parser("audit", help="describe the data and the ballot model").set_defaults(
        fn=cmd_audit
    )
    sub.add_parser(
        "calibrate", help="fit the election-day error against the 2022 cycle"
    ).set_defaults(fn=cmd_calibrate)

    run = sub.add_parser("run", help="fit, simulate and write the site JSON")
    run.add_argument("--refresh", action="store_true", help="re-download polls first")
    run.add_argument("--quiet", action="store_true", help="no sampling progress bar")
    run.add_argument("--draws", type=int, help="override draws/tune for a smoke test")
    run.add_argument(
        "--scenario",
        help="comma-separated candidate ids to fix the ballot, e.g. MLP,EP,JLM,BR,RG",
    )
    run.set_defaults(fn=cmd_run)

    args = p.parse_args(argv)
    _setup_logging(args.verbose)
    return args.fn(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

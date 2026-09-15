"""The 2024 legislative second-round duels, as observations of transfer.

WHY A LEGISLATIVE ELECTION IS IN A PRESIDENTIAL MODEL
-----------------------------------------------------
The runoff decides the presidency, and what decides the runoff is where the
eliminated candidates' voters go. Until now that rested on two sources: 43
measured 2022 transfers, and 54 polls asking 2026 respondents about a
hypothetical 2027 matchup. One is four years old; the other is speculation
about candidates who may not stand.

The 2024 legislative elections are the largest real test of anti-RN transfer
behaviour since 2022. 330 second-round duels pitted an RN or RN-allied
candidate against exactly one opponent, each with a full first-round
distribution behind it - a real electorate, choosing between two real names,
with everyone else eliminated. Structurally that is the same object the runoff
model already predicts.

WHAT IS TAKEN FROM THEM, AND WHAT IS DELIBERATELY NOT
-----------------------------------------------------
The **shape** is taken: how much worse the RN does against a left opponent
than against a centre one, from near-identical first-round positions. That is
a statement about the geometry of French politics, and 330 duels say it far
more precisely than 54 hypothetical polls can.

The **level** is not. A legislative duel follows *desistements* - third-placed
candidates standing down to consolidate the anti-RN vote - which a two-
candidate presidential runoff has no mechanism for, and it is local, with
incumbency and personal votes. So the model carries an explicit legislative
adjustment to the front republicain term (`runoff.py`), given a prior wide
enough that 2024's overall level is absorbed rather than exported to 2027.

THE UNION DE LA GAUCHE PROBLEM
------------------------------
136 of the 330 opponents carry the nuance ``UG``: the Nouveau Front populaire
joint nomination. The Ministry file does not record which party each one
actually came from, and they span LFI to the Socialists. There is no way to
resolve that from this data.

They are therefore placed at a FIXED MIXTURE of the model's left blocs, using
the NFP's own published seat-sharing split (LFI 229, PS and Place publique
175, Les Ecologistes 92, PCF 50). That is a real approximation and it is the
single largest assumption in this file: the position of the average NFP
candidate, applied to every one of them.

It cannot be fitted instead. Letting the data choose where the 2024 left sat
would absorb exactly the contrast this module exists to import, and report
nothing about 2027. ``scripts/check_legislatives_2024.py`` re-runs the whole
fit with the mixture moved to pure LFI and pure PS, which is how the size of
that assumption is checked rather than asserted.

SOURCE
------
Ministere de l'Interieur via data.gouv.fr, Licence Ouverte 2.0. Committed to
``data/cache/`` so this runs offline; see ``docs/DATA_SOURCES.md``.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..paths import CACHE

log = logging.getLogger(__name__)

T1 = CACHE / "legislatives_2024_t1.csv"
T2 = CACHE / "legislatives_2024_t2.csv"

SOURCE_URL = (
    "https://www.data.gouv.fr/datasets/"
    "elections-legislatives-des-30-juin-et-7-juillet-2024-resultats-definitifs"
)

# The NFP nomination split, June 2024: LFI 229, PS and Place publique 175,
# Les Ecologistes 92, PCF 50. The PCF sits in gauche_radicale in this model's
# roster (see config/candidats_2027.yaml on Roussel), so it joins LFI here.
_NFP = {"gauche_radicale": 229 + 50, "socialiste": 175, "ecologiste": 92}
NFP_SPLIT = {k: v / sum(_NFP.values()) for k, v in _NFP.items()}

# Ministry "nuance" codes mapped onto the model's nine blocs. A code may map to
# a mixture; weights must sum to one.
NUANCE_BLOC: dict[str, dict[str, float]] = {
    "EXG": {"extreme_gauche": 1.0},
    "FI": {"gauche_radicale": 1.0},
    "COM": {"gauche_radicale": 1.0},
    "UG": dict(NFP_SPLIT),
    "SOC": {"socialiste": 1.0},
    "RDG": {"socialiste": 1.0},
    "DVG": {"socialiste": 1.0},
    "ECO": {"ecologiste": 1.0},
    "ENS": {"centre": 1.0},
    "MDM": {"centre": 1.0},
    "HOR": {"centre": 1.0},
    "DVC": {"centre": 1.0},
    "LR": {"droite": 1.0},
    "UDI": {"droite": 1.0},
    "DVD": {"droite": 1.0},
    "DSV": {"souverainiste": 1.0},
    "REC": {"reconquete": 1.0},
    "EXD": {"reconquete": 1.0},
    "RN": {"rn": 1.0},
    "UXD": {"rn": 1.0},
}

# Codes with no position on a left-right axis. Not an oversight: "divers" is
# the Ministry's own label for unclassifiable, and the regionalists span the
# spectrum. Their first-round votes are dropped from the transfer pool rather
# than guessed, and `unmapped_share` reports how much that costs.
UNPLACEABLE = {"DIV", "REG"}

# The RN and the allied union of the far right (Ciotti's UDR in 2024).
FAR_RIGHT = {"RN", "UXD"}

# A duel whose eliminated field is mostly unplaceable says nothing reliable
# about transfer, so it is dropped rather than fitted on a guess.
MAX_UNMAPPED_SHARE = 0.05


@dataclass(frozen=True)
class Duels:
    """Runoff observations in the same shape the transfer model predicts.

    Finalist 0 is ALWAYS the RN side, so ``y`` is the RN's share of the
    two-way second-round vote and no per-duel sign bookkeeping is needed.
    """

    opp_weight: np.ndarray      # (M, K) the opponent's position as bloc weights
    source_shares: np.ndarray   # (M, K) eliminated first-round vote, by bloc
    finalist_own: np.ndarray    # (M, 2) each finalist's own first-round share
    y: np.ndarray               # (M,) RN share of the two-way round-2 vote
    opp_nuance: list[str]
    labels: list[str]
    dropped: list[str]
    unmapped_share: float       # share of round-1 vote with no bloc, overall

    def __len__(self) -> int:
        return len(self.y)


def _int(value: str | None) -> int | None:
    t = (value or "").strip().replace(" ", "").replace("\xa0", "")
    return int(t) if t.isdigit() else None


def parse(path: Path) -> dict:
    """Ministry circonscription file -> {(dept, circ): {exp, c: [candidates]}}."""
    out: dict[tuple[str, str], dict] = {}
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        cols = [c.strip().strip('"') for c in fh.readline().split(";")]
        for row in csv.reader(fh, delimiter=";"):
            if len(row) < 10:
                continue
            d = dict(zip(cols, row, strict=False))
            key = (
                d["Code département"].strip(),
                d["Code circonscription législative"].strip(),
            )
            cands = []
            i = 1
            while f"Nuance candidat {i}" in d:
                nu = (d.get(f"Nuance candidat {i}") or "").strip()
                nom = (d.get(f"Nom candidat {i}") or "").strip().upper()
                pre = (d.get(f"Prénom candidat {i}") or "").strip().upper()
                voix = _int(d.get(f"Voix {i}"))
                if nu and voix is not None:
                    cands.append({"nu": nu, "nom": nom, "pre": pre, "v": voix})
                i += 1
            exp = _int(d.get("Exprimés"))
            if exp:
                out[key] = {"exp": exp, "c": cands}
    return out


def _match(first: dict, cand: dict) -> dict | None:
    """Find a round-two finalist in the round-one field, BY NAME.

    Not by party label: a candidate's nuance can differ between rounds, and a
    mismatch there would silently drop the duel rather than erroring.
    """
    return next(
        (x for x in first["c"] if x["nom"] == cand["nom"] and x["pre"] == cand["pre"]),
        None,
    )


def raw_duels(t1: dict, t2: dict) -> list[dict]:
    """Round-two duels of the RN against exactly one opponent, matched by name.

    Kept in vote counts rather than shares because the reporting script
    aggregates across duels, where summing votes and averaging shares differ.
    """
    rows = []
    for key, second in t2.items():
        if len(second["c"]) != 2:
            continue
        rn = [c for c in second["c"] if c["nu"] in FAR_RIGHT]
        if len(rn) != 1:
            continue
        rn = rn[0]
        opp = next(c for c in second["c"] if c is not rn)
        first = t1.get(key)
        if not first:
            continue
        rn1, opp1 = _match(first, rn), _match(first, opp)
        if not rn1 or not opp1:
            continue
        rows.append(
            {
                "key": key,
                "nuance": opp["nu"],
                "rn_r1": rn1["v"],
                "rn_r2": rn["v"],
                "opp_r1": opp1["v"],
                "opp_r2": opp["v"],
                "exp_r1": first["exp"],
                "exp_r2": second["exp"],
                "first": first["c"],
                "rn_name": (rn["nom"], rn["pre"]),
                "opp_name": (opp["nom"], opp["pre"]),
            }
        )
    return rows


def build(
    bloc_keys: list[str],
    *,
    t1_path: Path | None = None,
    t2_path: Path | None = None,
    nfp_split: dict[str, float] | None = None,
) -> Duels:
    """Assemble the duels as transfer observations over the model's blocs.

    ``nfp_split`` overrides where the union-de-la-gauche candidates sit. It is
    the sensitivity knob for the largest assumption here, not a free parameter:
    see the module docstring.
    """
    t1_path = t1_path or T1
    t2_path = t2_path or T2
    for p in (t1_path, t2_path):
        if not p.exists():
            raise FileNotFoundError(f"{p} not found. See {SOURCE_URL}")

    mapping = dict(NUANCE_BLOC)
    if nfp_split is not None:
        total = sum(nfp_split.values())
        mapping["UG"] = {k: v / total for k, v in nfp_split.items()}

    index = {b: i for i, b in enumerate(bloc_keys)}
    K = len(bloc_keys)
    rn_index = index["rn"]

    def weights(nuance: str) -> np.ndarray | None:
        w = mapping.get(nuance)
        if w is None:
            return None
        out = np.zeros(K)
        for bloc, part in w.items():
            out[index[bloc]] += part
        return out

    rows = raw_duels(parse(t1_path), parse(t2_path))
    opp_w, source, own, y, nuances, labels, dropped = [], [], [], [], [], [], []
    unmapped_votes = total_votes = 0

    for r in rows:
        w_opp = weights(r["nuance"])
        if w_opp is None:
            dropped.append(
                f"{r['key'][0]}-{r['key'][1]}: opponent nuance {r['nuance']} "
                "has no position on the left-right axis"
            )
            continue

        # Everyone not in the duel has votes to transfer, spread across the
        # blocs their nuance maps to.
        by_bloc = np.zeros(K)
        unmapped = 0
        for c in r["first"]:
            if (c["nom"], c["pre"]) in (r["rn_name"], r["opp_name"]):
                continue
            w = weights(c["nu"])
            if w is None:
                unmapped += c["v"]
                continue
            by_bloc += w * c["v"]

        exp1 = r["exp_r1"]
        total_votes += exp1
        unmapped_votes += unmapped
        if unmapped / exp1 > MAX_UNMAPPED_SHARE:
            dropped.append(
                f"{r['key'][0]}-{r['key'][1]}: {unmapped / exp1:.0%} of the "
                "first-round vote has no bloc"
            )
            continue

        opp_w.append(w_opp)
        source.append(by_bloc / exp1)
        own.append([r["rn_r1"] / exp1, r["opp_r1"] / exp1])
        y.append(r["rn_r2"] / (r["rn_r2"] + r["opp_r2"]))
        nuances.append(r["nuance"])
        labels.append(f"{r['key'][0]}-{r['key'][1]} RN vs {r['nuance']}")

    if len(y) < 200:
        raise ValueError(
            f"only {len(y)} duels usable of {len(rows)} found; expected ~330. "
            "The Ministry file or the nuance mapping has changed."
        )

    duels = Duels(
        opp_weight=np.array(opp_w),
        source_shares=np.array(source),
        finalist_own=np.array(own),
        y=np.array(y),
        opp_nuance=nuances,
        labels=labels,
        dropped=dropped,
        unmapped_share=unmapped_votes / total_votes if total_votes else 0.0,
    )
    log.info(
        "2024 duels: %d usable, %d dropped, %.1f%% of first-round vote unplaceable",
        len(duels), len(dropped), 100 * duels.unmapped_share,
    )
    if duels.opp_weight[:, rn_index].any():
        raise ValueError("an RN-versus-RN pairing is not a duel; check FAR_RIGHT")
    return duels

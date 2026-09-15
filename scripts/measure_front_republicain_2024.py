"""How strong was the front republicain in 2024, and against whom?

WHY GO LOOKING FOR THIS
-----------------------
The single assumption that can most change this forecast is how readily
non-RN voters transfer to block an RN finalist. In the model that is fitted on
**2022** presidential transfers and on 2026 polls asking about a hypothetical
2027 runoff. Both are old or speculative.

The 2024 legislative elections are the largest real test of anti-RN transfer
behaviour since, and they postdate 2022. 330 second-round duels pitted an RN or
RN-allied candidate against exactly one opponent - a far bigger sample than the
one presidential runoff the model is otherwise anchored on.

WHAT IS MEASURED
----------------
For each duel, both finalists are matched between rounds BY NAME (not by
party label, which can change), and the RN's share of the two-way vote in round
two is compared with its first-round position. Aggregated by the bloc the
opponent came from, that answers the question the model actually needs: does it
matter *who* the anti-RN candidate is?

This is the DESCRIPTIVE read. The duels are also fitted properly, inside the
runoff transfer model - see ``presidentielle/data/legislatives_2024.py``, which
this script shares its parsing and its nuance mapping with, and
``scripts/check_legislatives_2024.py`` for what they do to the forecast.

WHAT THIS IS NOT
----------------
* **Not a presidential runoff.** Legislative duels are local, carry incumbency
  and personal votes, and - decisively - follow *desistements*, where third
  candidates withdrew to consolidate the anti-RN vote. A presidential runoff
  has two candidates by construction, so that mechanism is absent. This is a
  reason 2024 may overstate what a presidential second round would show.
* **Not individual behaviour.** These are aggregate flows: ecological
  inference, not a survey of who switched.
* **Not Melenchon.** The 2024 "left" is the NFP coalition, spanning LFI to the
  Socialists and Greens. A single polarising candidate is not the same thing,
  which is the main reason the number below cannot be dropped straight into the
  2027 model.

Run:  python scripts/measure_front_republicain_2024.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("PYTENSOR_FLAGS", "cxx=")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from presidentielle.data.legislatives_2024 import (  # noqa: E402
    NUANCE_BLOC,
    SOURCE_URL,
    T1,
    T2,
    parse,
    raw_duels,
)

# Coarse groups for reporting. Derived from the model's own nuance mapping so
# the two cannot drift apart: a nuance belongs to the group its heaviest bloc
# belongs to.
GROUP_OF_BLOC = {
    "extreme_gauche": "left", "gauche_radicale": "left",
    "socialiste": "left", "ecologiste": "left",
    "centre": "centre",
    "droite": "right",
    "souverainiste": "far right", "reconquete": "far right", "rn": "far right",
}


def group_of(nuance: str) -> str:
    weights = NUANCE_BLOC.get(nuance)
    if not weights:
        return "other"
    return GROUP_OF_BLOC[max(weights, key=weights.get)]


# 2022 presidential, for comparison: Le Pen 23.15% in round one, 41.45% of the
# two-way vote in round two (config/resultats_2022.yaml).
LEPEN_2022_R1 = 0.2315
LEPEN_2022_R2 = 0.4145


def main() -> int:
    if not T1.exists() or not T2.exists():
        sys.exit(f"missing {T1.name} / {T2.name} in data/cache.\n{SOURCE_URL}")
    rows = raw_duels(parse(T1), parse(T2))
    if len(rows) < 50:
        sys.exit(f"only {len(rows)} duels matched; expected several hundred")
    for r in rows:
        r["bloc"] = group_of(r["nuance"])

    def agg(sub):
        r1 = sum(r["rn_r1"] for r in sub) / sum(r["exp_r1"] for r in sub)
        r2 = sum(r["rn_r2"] for r in sub) / sum(r["rn_r2"] + r["opp_r2"] for r in sub)
        gain_rn = sum(r["rn_r2"] - r["rn_r1"] for r in sub)
        gain_opp = sum(r["opp_r2"] - r["opp_r1"] for r in sub)
        won = sum(1 for r in sub if r["rn_r2"] > r["opp_r2"])
        return r1, r2, gain_opp / gain_rn if gain_rn else float("nan"), won

    print(f"{len(rows)} second-round duels, RN or allied against one opponent")
    print()
    r1, r2, ratio, won = agg(rows)
    print("OVERALL")
    print(f"  RN round 1 {r1:.1%}  ->  round 2 {r2:.1%}   ({100 * (r2 - r1):+.1f} pts)")
    print(f"  for every vote the RN gained between rounds, its opponent gained {ratio:.2f}")
    print(f"  RN won {won} of {len(rows)} ({won / len(rows):.0%})")
    print()
    print("  2022 presidential for comparison:")
    print(f"    Le Pen {LEPEN_2022_R1:.1%} -> {LEPEN_2022_R2:.1%} "
          f"({100 * (LEPEN_2022_R2 - LEPEN_2022_R1):+.1f} pts), opponent gained 1.74 per RN vote")
    print()
    print("BY OPPONENT BLOC  - does it matter who the anti-RN candidate is?")
    print(f"  {'bloc':<8} {'n':>4} {'RN r1':>7} {'RN r2':>7} {'ratio':>7} {'RN won':>8}")
    order = ["left", "centre", "right", "other"]
    shares = {}
    for b in order:
        sub = [r for r in rows if r["bloc"] == b]
        if len(sub) < 5:
            continue
        a1, a2, ra, w = agg(sub)
        shares[b] = a2
        print(f"  {b:<8} {len(sub):>4} {a1:>6.1%} {a2:>7.1%} {ra:>7.2f} {w / len(sub):>7.0%}")

    if "left" in shares and "centre" in shares:
        gap = 100 * (shares["left"] - shares["centre"])
        print()
        print("  THE FINDING: from near-identical first-round positions, the RN converts")
        print(f"  {gap:+.1f} points better against a left opponent than a centre one.")
        print()
        print("  The model's structure says the same thing qualitatively. The 2027")
        print("  hypothetical polls say it far more strongly - they put Le Pen around")
        print("  68% against Melenchon and under 50% against Philippe, a gap nearer 20")
        print("  points. Reconciling those two is what the legislative-versus-")
        print("  presidential terms in the runoff model exist for; see")
        print("  scripts/check_legislatives_2024.py.")
        print()
        print("  Do not read the gap above as Melenchon's penalty. The 2024 'left' is")
        print("  the NFP coalition, not one polarising candidate, and these are local")
        print("  duels following desistements, which a presidential runoff has not.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

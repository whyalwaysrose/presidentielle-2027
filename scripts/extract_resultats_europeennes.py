"""Build `config/resultats_europeennes.yaml` from the Ministry's own files.

WHY THE EUROPEANS, BESIDE THE PRESIDENTIALS
-------------------------------------------
A presidential first round measures a CANDIDATE. The Europeans are the cleanest
measure of a PARTY there is in France: proportional representation with party
lists, so the vote attaches to an organisation rather than to a personality.
They also say something the presidential series cannot. The Rassemblement
national has topped three consecutive European elections without ever winning a
presidency.

FOUR CYCLES, FOUR LAYOUTS, so this is a script and not a transcription:

  2009  `Circo euro` sheet of the .xls - the eight European constituencies of
        the time, summed. (The commune-level file published alongside it covers
        only part of the country: 7.5M of 17.2M valid votes. Its SHARES look
        almost right, which is exactly what makes it dangerous.)
  2014  `Résultats` sheet of the .xlsx, which carries a France entière block
        by nuance.
  2019  per-circonscription .txt, summed. NO NUANCE COLUMN this year, so lists
        are keyed by their abbreviated label.
  2024  per-circonscription .csv, summed, keyed by nuance.

Every cycle is checked against its own published Exprimés, and the script
refuses to write one that does not reconcile.

WHAT A KEY MEANS
----------------
For 2009, 2014 and 2024 the key is the Ministry's NUANCE code - a grouping of
lists, not a party. `LEXG` is every far-left list at once, so Lutte ouvrière
and the NPA cannot be told apart in those years; `LDVD` likewise covers several
sovereigntist and right-wing lists. `config/partis.yaml` therefore maps only
what can be identified, and leaves the rest blank rather than guessing. A gap
shown as a dash is honest; a wrong attribution is not.

LICENCE: each dataset is published under the Licence Ouverte (`fr-lo`) or
Licence Ouverte v2 (`lov2`), which permit reuse with attribution. The
attribution travels in the header of the file this writes.

Run:  pip install -e '.[extract]'
      python scripts/extract_resultats_europeennes.py
"""

from __future__ import annotations

import collections
import csv
import datetime as dt
import io
import sys
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config" / "resultats_europeennes.yaml"

SOURCES = {
    2009: {
        "date": dt.date(2009, 6, 7),
        "page": "https://www.data.gouv.fr/datasets/elections-europeennes-2009-resultats-571327",
        "url": "https://static.data.gouv.fr/e0/88c770f067e9bc4cfd3dea656aa69b15add243c1c4c367a85d7314e74fde63.xls",
        "kind": "xls_circo_euro",
    },
    2014: {
        "date": dt.date(2014, 5, 25),
        "page": "https://www.data.gouv.fr/datasets/elections-europeennes-2014-resulta-2",
        "url": "https://www.data.gouv.fr/storage/f/2014-05-30T10-34-25/euro-2014-resultats-c.xlsx",
        "kind": "xlsx_national",
    },
    2019: {
        "date": dt.date(2019, 5, 26),
        "page": "https://www.data.gouv.fr/datasets/resultats-des-elections-europeennes-2019",
        "url": "https://static.data.gouv.fr/resources/resultats-des-elections-europeennes-2019/20190531-144336/resultats-definitifs-par-circonscription.txt",
        "kind": "txt_wide",
    },
    2024: {
        "date": dt.date(2024, 6, 9),
        "page": "https://www.data.gouv.fr/datasets/resultats-des-elections-europeennes-du-9-juin-2024",
        "url": "https://static.data.gouv.fr/resources/resultats-des-elections-europeennes-du-9-juin-2024/20240613-154902/resultats-definitifs-par-circonscription.csv",
        "kind": "csv_wide",
    },
}


def _num(value) -> int | None:
    if isinstance(value, (int, float)) and value != "":
        return int(round(value))
    text = str(value or "").replace("\xa0", "").replace(" ", "").replace(" ", "").strip()
    return int(text) if text.isdigit() else None


def _sum_wide(header: list[str], rows, key_col: str, label_col: str) -> dict:
    """Sum repeating list blocks across rows, keyed by `key_col`."""
    header = [h.strip().strip('"') for h in header]
    starts = [i for i, h in enumerate(header) if h in ("N°Liste", "Numéro de panneau 1")]
    if not starts:  # the 2024 file numbers every block's header
        starts = [i for i, h in enumerate(header) if h.startswith("Numéro de panneau")]
    width = (starts[1] - starts[0]) if len(starts) > 1 else 7
    offsets = {header[starts[0] + k]: k for k in range(width)
               if starts[0] + k < len(header)}
    exprimes_col = next(i for i, h in enumerate(header) if h == "Exprimés")

    votes: collections.Counter = collections.Counter()
    labels: dict[str, str] = {}
    exprimes = 0
    for row in rows:
        if len(row) <= exprimes_col:
            continue
        exprimes += _num(row[exprimes_col]) or 0
        for s in starts:
            def cell(name, _row=row, _s=s):
                k = offsets.get(name)
                return _row[_s + k] if k is not None and _s + k < len(_row) else None
            key = str(cell(key_col) or "").strip()
            votes_cast = _num(cell("Voix"))
            if key and votes_cast is not None:
                votes[key] += votes_cast
                labels.setdefault(key, str(cell(label_col) or "").strip())
    return {"votes": dict(votes), "labels": labels, "exprimes": exprimes}


def read_xls_circo_euro(content: bytes) -> dict:
    """2009: the eight European constituencies of the time, summed."""
    import xlrd

    sheet = xlrd.open_workbook(file_contents=content).sheet_by_name("Circo euro")
    header = [str(sheet.cell_value(0, c)) for c in range(sheet.ncols)]
    rows = [[sheet.cell_value(r, c) for c in range(sheet.ncols)]
            for r in range(1, sheet.nrows)]
    return _sum_wide(header, rows, "Nuance Liste", "Libellé Abrégé Liste")


def read_xlsx_national(content: bytes) -> dict:
    """2014: the France entière block of the `Résultats` sheet.

    Laid out as the electorate lines on the left and one row per nuance on the
    right, and it repeats for Métropole and Outre-Mer below - so this stops at
    the first block, exactly as the presidential 2017 reader has to.
    """
    import openpyxl

    ws = openpyxl.load_workbook(io.BytesIO(content), read_only=True)["Résultats"]
    grid = [list(r) for r in ws.iter_rows(min_row=1, max_row=20, values_only=True)]

    exprimes = None
    for row in grid:
        for i, cell in enumerate(row):
            if str(cell).strip().lower() == "exprimés":
                exprimes = next((_num(v) for v in row[i + 1:] if _num(v)), None)
                break
        if exprimes:
            break

    # The nuance column is the one whose header cell reads "Nuan..."; votes are
    # the first value after the seats/% pair, so take the LAST large integer in
    # the row, which is the vote count.
    votes: dict[str, int] = {}
    start = next(i for i, row in enumerate(grid)
                 if any(str(c).strip().startswith("Nuan") for c in row))
    col = next(i for i, c in enumerate(grid[start]) if str(c).strip().startswith("Nuan"))
    for row in grid[start + 1:]:
        if col >= len(row):
            continue
        key = str(row[col] or "").strip()
        if not key.startswith("L"):
            continue
        big = [v for v in (_num(x) for x in row[col + 1:]) if v and v > 1000]
        if big:
            votes[key] = max(big)
    return {"votes": votes, "labels": {}, "exprimes": exprimes}


def read_txt_wide(content: bytes) -> dict:
    """2019: per-circonscription, no nuance column, so keyed by list label."""
    text = content.decode("latin-1")
    lines = text.splitlines()
    header = lines[0].split(";")
    rows = [line.split(";") for line in lines[1:] if line.strip()]
    # The header describes ONE list block; the rows repeat it.
    base, block = header[:18], header[18:25]
    full = base + block * ((max(len(r) for r in rows) - len(base)) // len(block) + 1)
    return _sum_wide(full, rows, "Libellé Abrégé Liste", "Nom Tête de Liste")


def read_csv_wide(content: bytes) -> dict:
    """2024: per-circonscription, keyed by nuance."""
    text = content.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = next(reader)
    rows = list(reader)
    header = [h.strip().strip('"') for h in header]
    starts = [i for i, h in enumerate(header) if h.startswith("Numéro de panneau")]
    width = starts[1] - starts[0]
    offsets = {header[starts[0] + k].rstrip(" 1"): k for k in range(width)}
    exprimes_col = header.index("Exprimés")

    votes: collections.Counter = collections.Counter()
    labels: dict[str, str] = {}
    exprimes = 0
    for row in rows:
        if len(row) <= exprimes_col:
            continue
        exprimes += _num(row[exprimes_col]) or 0
        for s in starts:
            nuance = str(row[s + offsets["Nuance liste"]] or "").strip()
            cast = _num(row[s + offsets["Voix"]])
            if nuance and cast is not None:
                votes[nuance] += cast
                labels.setdefault(
                    nuance, str(row[s + offsets["Libellé abrégé de liste"]] or "").strip()
                )
    return {"votes": dict(votes), "labels": labels, "exprimes": exprimes}


READERS = {
    "xls_circo_euro": read_xls_circo_euro,
    "xlsx_national": read_xlsx_national,
    "txt_wide": read_txt_wide,
    "csv_wide": read_csv_wide,
}


def main() -> int:
    out: dict = {}
    for year, src in sorted(SOURCES.items()):
        print(f"fetching {year} ...", file=sys.stderr)
        resp = requests.get(src["url"], timeout=300)
        resp.raise_for_status()
        national = READERS[src["kind"]](resp.content)

        exprimes = national["exprimes"]
        total = sum(national["votes"].values())
        if not exprimes:
            raise SystemExit(f"{year}: no Exprimés found")
        # Every list's votes must reconcile with the Ministry's own total. The
        # 2009 commune file fails this by a factor of two while its shares look
        # plausible, which is the trap this check exists for.
        if abs(total - exprimes) > max(2000, 0.001 * exprimes):
            raise SystemExit(
                f"{year}: list votes sum to {total:,} but Exprimés is {exprimes:,} "
                f"({100 * (total - exprimes) / exprimes:+.2f}%)"
            )
        out[year] = {
            "date": src["date"],
            "source_page": src["page"],
            "source_fichier": src["url"],
            "exprimes": exprimes,
            "listes": {
                k: {"voix": v, "libelle": national["labels"].get(k, "")}
                for k, v in sorted(national["votes"].items(), key=lambda kv: -kv[1])
            },
        }
        top = sorted(national["votes"].items(), key=lambda kv: -kv[1])[:3]
        print(f"  {year}: {len(national['votes'])} lists, {exprimes:,} exprimés, "
              + ", ".join(f"{k} {100 * v / exprimes:.1f}%" for k, v in top),
              file=sys.stderr)

    header = f"""# National results of the European elections, by list grouping.
#
# GENERATED by scripts/extract_resultats_europeennes.py on {dt.date.today()}.
# Do not edit by hand: re-run the script, which refuses to write any cycle
# whose list votes do not reconcile with the Ministry's own Exprimés.
#
# SOURCE: Ministere de l'Interieur via data.gouv.fr, Licence Ouverte. The
# dataset page for each cycle is in `source_page`, and that is what the site
# cites.
#
# WHY THE EUROPEANS: proportional representation with party lists, so the vote
# attaches to an organisation rather than to a personality - the cleanest
# measure of party strength France produces. The RN has topped three of these
# in a row without ever winning a presidency.
#
# A KEY IS A NUANCE, NOT A PARTY, in 2009, 2014 and 2024: `LEXG` is every
# far-left list at once, `LDVD` several right-wing ones. 2019 has no nuance
# column at all and is keyed by the list's abbreviated label. config/partis.yaml
# maps only what can be identified and leaves the rest blank; a dash is honest,
# a wrong attribution is not.

"""
    OUT.write_text(
        header + yaml.safe_dump(out, allow_unicode=True, sort_keys=True, width=100),
        encoding="utf-8",
    )
    print(f"wrote {OUT.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

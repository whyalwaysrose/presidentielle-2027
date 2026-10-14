"""Tests for the feed-versus-Commission des sondages check.

The check exists because a real voting-intention poll (OpinionWay for Fondapol,
June 2026) never reached the feed and nothing noticed. Its failure mode is the
same as the thing it guards against: silence. So these assert that each kind
of gap is REPORTED, and that the reading of notices is neither fooled by the
disclaimers institutes print nor slow enough to be dropped from the daily run.
"""

from __future__ import annotations

import datetime as dt
import time
import zlib

import pytest
import yaml

from presidentielle.data import commission as C

TODAY = dt.date(2026, 9, 21)

# ------------------------------------------------------------------ PDF text


def _pdf(*streams: tuple[bytes, bytes]) -> bytes:
    """A minimal PDF: (dictionary, uncompressed body) pairs, Flate-encoded."""
    parts = [b"%PDF-1.7\n"]
    for i, (header, body) in enumerate(streams, start=1):
        data = zlib.compress(body)
        parts.append(
            b"%d 0 obj\n<< /Filter /FlateDecode /Length %d %s >>\nstream\n"
            % (i, len(data), header)
            + data
            + b"\nendstream\nendobj\n"
        )
    return b"".join(parts)


def _hex_string_pdf(content: bytes) -> bytes:
    """A complete, valid one-page PDF carrying `content` as its page stream.

    Unlike `_pdf`, this one is structurally real - it has a catalog, a page
    tree and an xref - because pypdf will not open anything less.
    """
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 6 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, start))
    return bytes(out)


def test_text_comes_out_of_tj_operators():
    pdf = _pdf((b"", b"BT [(Intentions ) -20 (de vote)] TJ ET BT (au 1er tour) Tj ET"))
    assert C.pdf_text(pdf) == "Intentions de vote au 1er tour"


def test_images_and_fonts_are_skipped():
    """Decompressing and scanning embedded images was most of the cost, and
    their bytes can accidentally look like text operators."""
    junk = b"[(intentions de vote)] TJ"
    pdf = _pdf((b"/Subtype /Image", junk), (b"/Length1 99", junk), (b"", b"(ok) Tj"))
    assert C.pdf_text(pdf) == "ok"


def test_a_hostile_stream_is_fast():
    """REGRESSION. The first extractor used `\\[(.*?)\\]\\s*TJ` with DOTALL,
    which backtracks quadratically on a stream full of '[' with no ']' - some
    real notices took minutes each, which would have made the daily check
    unaffordable. The patterns are bounded now."""
    pdf = _pdf((b"", b"[" * 200_000 + b"(" * 200_000 + b"Tj TJ"))
    t0 = time.perf_counter()
    C.pdf_text(pdf)
    assert time.perf_counter() - t0 < 2.0


# ---------------------------------------------------------------- classifier

PADDING = " Notice technique, echantillon de 1 000 personnes. " * 10


@pytest.mark.parametrize(
    "phrase",
    [
        "Intentions de vote au premier tour",
        "Si le premier tour de l'election presidentielle avait lieu dimanche prochain",
        "pour chacune des configurations suivantes, lequel des candidats aurait votre "
        "preference ?",
    ],
)
def test_voting_intention_notices_are_recognised(phrase):
    verdict, evidence = C.classify(PADDING + phrase + PADDING)
    assert verdict == "vote"
    assert evidence


@pytest.mark.parametrize(
    "disclaimer",
    [
        # Each of these produced a false positive during calibration.
        "Ils ne constituent ni une intention de vote ni un element predictif.",
        "Le potentiel electoral ne constitue nullement une intention de vote.",
        "Cette question n'a absolument rien a voir avec une intention de vote.",
    ],
)
def test_disclaimers_are_not_mistaken_for_voting_intentions(disclaimer):
    assert C.classify(PADDING + disclaimer + PADDING)[0] == "autre"


def test_an_unreadable_notice_is_reported_not_guessed():
    """Some notices are scanned images. Calling them 'not a poll' would be a
    guess that silently hides exactly the kind of gap this exists to find."""
    assert C.classify("12 34")[0] == "illisible"


# ------------------------------------------------------------------- check


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A catalog, a scan cache and a review file, all on disk under tmp_path."""
    monkeypatch.setattr(C, "CATALOG_FILE", tmp_path / "catalog.csv")
    monkeypatch.setattr(C, "SCAN_FILE", tmp_path / "scan.json")
    monkeypatch.setattr(C, "REVIEW_FILE", tmp_path / "reviews.yaml")

    def write(catalog, scan=None, reviews=None):
        rows = ["filename,categorie,year,pdf_path,http last-modified,pdf creation-date"]
        for name, published, cat in catalog:
            # `published` of "" is a notice the catalog gives no date for.
            rows.append(f"{name},{cat},2026.0,archives/{name},,{published}")
        C.CATALOG_FILE.write_text("\n".join(rows) + "\n", encoding="utf-8")
        C._save_scan(scan or {})
        C.REVIEW_FILE.write_text(
            yaml.safe_dump({"notices": reviews or {}}), encoding="utf-8"
        )

    return write


def _run(feed=frozenset()):
    return C.check(set(feed), as_of=TODAY, since=dt.date(2024, 7, 8), download=False)


def test_an_old_unreviewed_voting_intention_is_a_warning(sandbox):
    sandbox(
        [("100-pres-x.pdf", "2026-08-01", "Pres")],
        scan={"100-pres-x.pdf": {"verdict": "vote", "extrait": "intentions de vote"}},
    )
    r = _run()
    assert [n["fichier"] for n in r.missing_vote] == ["100-pres-x.pdf"]
    assert not r.ok
    assert any(a.startswith("::warning") for a in C.github_annotations(r))


def test_a_fresh_one_is_only_pending(sandbox):
    """Upstream ingests on its own schedule; a notice from yesterday not being
    in the feed yet is normal, and warning about it daily would teach everyone
    to ignore the warning."""
    sandbox(
        [("101-pres-x.pdf", (TODAY - dt.timedelta(days=2)).isoformat(), "Pres")],
        scan={"101-pres-x.pdf": {"verdict": "vote", "extrait": ""}},
    )
    r = _run()
    assert r.pending_vote and not r.missing_vote


def test_a_reviewed_gap_is_reported_but_not_warned(sandbox):
    sandbox(
        [("102-pres-x.pdf", "2026-06-01", "Pres")],
        scan={"102-pres-x.pdf": {"verdict": "vote", "extrait": ""}},
        reviews={"102-pres-x.pdf": {"statut": "manquante", "note": "Fondapol"}},
    )
    r = _run()
    assert not r.missing_vote
    assert r.known_gaps[0]["note"] == "Fondapol"
    assert not any(a.startswith("::warning") for a in C.github_annotations(r))


def test_a_poll_upstream_declined_is_shown_but_never_warned(sandbox):
    """Different from a gap. The upstream maintainers read the Toluna/Regards
    poll and decided against carrying it because its hypotheses name a "gauche
    unie" candidate rather than a person. Reporting it again would relitigate
    their decision - but it is still a real voting-intention poll this forecast
    does not see, so it stays on the report rather than vanishing."""
    sandbox(
        [("104-pres-y.pdf", "2026-06-01", "Pres")],
        scan={"104-pres-y.pdf": {"verdict": "vote", "extrait": ""}},
        reviews={"104-pres-y.pdf": {
            "statut": "ecartee_upstream", "note": "upstream declined it"}},
    )
    r = _run()
    # Not an open gap, and nothing to act on...
    assert not r.missing_vote and not r.known_gaps
    assert r.ok
    assert not any(a.startswith("::warning") for a in C.github_annotations(r))
    # ...but still visible, with the reason, on the report and in the payload.
    assert r.declined[0]["note"] == "upstream declined it"
    assert any("declined upstream" in line for line in r.lines())
    assert r.as_dict()["ecartees_upstream"][0]["fichier"] == "104-pres-y.pdf"


def test_a_human_verdict_beats_the_classifier(sandbox):
    sandbox(
        [("103-pres-seconds-tours.pdf", "2026-06-01", "Pres")],
        scan={"103-pres-seconds-tours.pdf": {"verdict": "vote", "extrait": ""}},
        reviews={"103-pres-seconds-tours.pdf": {"statut": "pas_une_intention"}},
    )
    r = _run()
    assert r.ok and not r.known_gaps


def test_notices_in_the_feed_and_out_of_scope_are_ignored(sandbox):
    sandbox([
        ("104-pres-iv-x.pdf", "2026-06-01", "Pres"),      # in the feed
        ("105-mun-rodez.pdf", "2026-06-01", "Pres"),      # municipal, misfiled
        ("106-pres-old.pdf", "2023-01-01", "Pres"),       # before the feed starts
        ("107-leg-x.pdf", "2026-06-01", "Leg"),           # another election
    ])
    r = _run(feed={"104-pres-iv-x.pdf"})
    assert r.ok
    # In scope means presidential and dated since the feed starts: 104 and 105.
    assert r.notices_considered == 2 and r.in_feed == 1


def test_offline_an_unscanned_notice_is_flagged_not_skipped(sandbox):
    """`audit` and `run` never download. A notice nobody has read yet must show
    up as unread rather than passing as fine."""
    sandbox([("108-pres-new.pdf", "2026-06-01", "Pres")])
    r = _run()
    assert r.unreadable and not r.ok


def _serve(monkeypatch, body: bytes):
    """Make every notice download return `body`."""
    class Response:
        content = body

        def raise_for_status(self):
            pass

    monkeypatch.setattr(C.requests, "get", lambda *a, **k: Response())


def test_an_unreadable_verdict_is_never_cached(sandbox, monkeypatch):
    """"Unreadable" says something about the reader, not about the notice. The
    four Elabe notices sat cached as unreadable while pypdf could read them
    perfectly well; cache that verdict and a reader that later learns to read
    them never gets the chance."""
    sandbox([("200-pres-scan.pdf", "2026-08-01", "Pres")])
    _serve(monkeypatch, b"%PDF-1.7\nno text at all")
    r = C.check(set(), as_of=TODAY, since=dt.date(2024, 7, 8))
    assert r.unreadable == ["200-pres-scan.pdf"]
    assert C._load_scan() == {}, "an unreadable verdict was cached"


def test_a_verdict_the_reader_could_reach_is_cached(sandbox, monkeypatch):
    """The counterpart: a notice that was actually read is cached, so the daily
    run does not download the whole catalog every morning."""
    sandbox([("201-pres-x.pdf", "2026-08-01", "Pres")])
    body = b"BT [(Intentions de vote au premier tour. %s)] TJ ET" % (
        PADDING.encode())
    _serve(monkeypatch, _pdf((b"", body)))
    r = C.check(set(), as_of=TODAY, since=dt.date(2024, 7, 8))
    assert [n["fichier"] for n in r.missing_vote] == ["201-pres-x.pdf"]
    assert C._load_scan()["201-pres-x.pdf"]["verdict"] == "vote"


def test_a_notice_with_no_date_is_reported_not_dropped(sandbox):
    """The catalog gives 10251a no date in either column, and a notice that
    cannot be placed in time was being filtered out of the comparison
    altogether - the exact failure this check exists to prevent. It is now
    reported for a person instead."""
    sandbox([("300-pres-undated.pdf", "", "Pres")])
    r = _run()
    assert r.undated == ["300-pres-undated.pdf"]
    assert not r.ok
    assert any("no publication date" in line for line in r.lines())
    assert r.as_dict()["sans_date"] == ["300-pres-undated.pdf"]
    assert any("::notice title=Notice has no date" in a
               for a in C.github_annotations(r))


def test_an_undated_notice_already_handled_is_not_nagged_about(sandbox):
    """Once it is in the feed, or once someone has ruled on it, it stops being
    an open question."""
    sandbox([("300-pres-undated.pdf", "", "Pres")])
    assert _run(feed={"300-pres-undated.pdf"}).undated == []

    sandbox(
        [("300-pres-undated.pdf", "", "Pres")],
        reviews={"300-pres-undated.pdf": {
            "statut": "pas_une_intention", "note": "read by hand"}},
    )
    assert _run().undated == []


# ------------------------------------------------------------ second reader


def test_the_bounded_reader_is_used_whenever_it_finds_anything(monkeypatch):
    """pypdf is the fallback, never the default. The hand-rolled reader runs
    unattended against arbitrary PDFs from the internet; handing a full parser
    work it does not need would give that up for nothing."""
    called = []
    monkeypatch.setattr(C, "pdf_text_pypdf", lambda d: called.append(d) or "")
    data = _pdf((b"", b"BT [(Intentions de vote)] TJ ET"))
    assert "Intentions de vote" in C.notice_text(data)
    assert not called, "the fallback ran even though the primary found text"


def test_a_notice_the_bounded_reader_cannot_read_falls_back(monkeypatch):
    """The Elabe case: subset CID fonts, so the TJ operands are hex glyph ids
    and the primary returns nothing at all."""
    monkeypatch.setattr(C, "pdf_text_pypdf", lambda d: "Intentions de vote 2027")
    cid = _pdf((b"", b"BT /F1 12 Tf [<0003><0004>] TJ ET"))
    assert C.pdf_text(cid).strip() == ""
    assert C.notice_text(cid) == "Intentions de vote 2027"


def test_without_pypdf_a_notice_is_unreadable_exactly_as_before(monkeypatch):
    """The dependency is optional. A scheduled run on a machine without it
    must report the notice for a person, not die with an ImportError."""
    import builtins

    real_import = builtins.__import__

    def no_pypdf(name, *args, **kwargs):
        if name == "pypdf":
            raise ImportError("no pypdf")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pypdf)
    # Has a text layer, so the fallback would otherwise be attempted.
    assert C.pdf_text_pypdf(b"%PDF-1.7\n/ToUnicode") == ""


def test_the_fallback_is_not_handed_scans_or_anything_enormous():
    """Two cheap guards before a parser is started: a PDF with no ToUnicode
    map has no text layer to decode, and a notice is never megabytes long."""
    assert C.pdf_text_pypdf(b"%PDF-1.7\nno text layer here") == ""
    assert C.pdf_text_pypdf(b"/ToUnicode" + b"\0" * C.MAX_FALLBACK_BYTES) == ""
    assert C.pdf_text_pypdf(b"") == ""


def test_a_malformed_pdf_does_not_stop_the_run():
    """Whatever pypdf raises on a truncated or hostile file, the run continues
    and the notice is simply reported as unreadable."""
    pytest.importorskip("pypdf")
    assert C.pdf_text_pypdf(b"%PDF-1.7\n/ToUnicode garbage not a pdf") == ""


def test_the_fallback_reads_a_hex_string_notice():
    """End to end, with no monkeypatching: a PDF whose text is written as hex
    strings rather than literal ones. The primary reader gets nothing from it;
    pypdf gets the words."""
    pytest.importorskip("pypdf")
    body = b"BT /F1 24 Tf 72 700 Td <496E74656E74696F6E7320646520766F7465> Tj ET"
    pdf = _hex_string_pdf(body)
    assert C.pdf_text(pdf).strip() == ""
    assert "Intentions de vote" in C.notice_text(pdf)


# ------------------------------------------------------ the committed reviews


def test_every_review_is_well_formed_and_names_a_real_notice():
    reviews = C.load_reviews()
    assert reviews, "the review file is empty or missing"
    known = {n.filename for n in C.load_catalog()} if C.CATALOG_FILE.exists() else None
    for name, review in reviews.items():
        assert review.get("statut") in C.REVIEW_STATUSES, name
        assert review.get("note"), f"{name}: a verdict must say what was read"
        if known is not None:
            assert name in known, f"{name} is not in the Commission catalog"

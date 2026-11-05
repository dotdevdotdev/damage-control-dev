"""Respelling a known-blocked or known-asked corpus row must not change its verdict.

The default run is deterministic (fixed seed, bounded count) and replays every respelling through the real
hook entrypoint. A miss is never fixed by loosening the generator: each distinct miss class has its own
issue, and ``KNOWN_MISSES`` below names the classes whose issue is still open. A class leaves the list when
its fix lands, and the staleness test fails if a listed class no longer misses.
"""

import re

from damage_control import cli, corpus, fuzz

DATA = corpus.load()
QUOTE_OR_BACKSLASH = {"quote-split", "backslash"}
DOT_OR_DOUBLE_SLASH = re.compile(r"//|/\.{1,2}/")

# issue number -> (what the class is, which respellings it covers)
KNOWN_MISSES = {
    30: ("quote or backslash inside a protected path that also has a dot segment or repeated slash",
         lambda r: r.family in QUOTE_OR_BACKSLASH and r.row_id.startswith("path-spelling")
         and bool(DOT_OR_DOUBLE_SLASH.search(r.plain))),
    33: ("braced variable reference followed by a repeated slash or inside a brace group",
         lambda r: r.family == "home-variable" and "${hh}" in r.command
         and r.row_id in ("path-spelling-06", "path-spelling-15", "path-spelling-17")),
}


def _known(respelling):
    return any(matches(respelling) for _, matches in KNOWN_MISSES.values())


def test_every_respelling_keeps_its_rows_verdict_except_the_classes_with_an_open_issue():
    result = fuzz.run(DATA, exclude=_known)
    assert result["count"] > 100
    assert not result["mismatches"], fuzz.report(result)


def test_each_excluded_class_still_misses():
    everything = fuzz.generate(DATA["rows"], n=10 ** 6)
    stale = []
    for number, (what, matches) in KNOWN_MISSES.items():
        covered = [r for r in everything if matches(r)]
        missed = fuzz.replay(DATA, covered)["mismatches"]
        if not missed:
            stale.append((number, what, len(covered)))
    assert not stale, f"fixed, so remove from KNOWN_MISSES: {stale}"


def test_generation_is_deterministic_bounded_and_seeded():
    rows = DATA["rows"]
    first = fuzz.generate(rows, n=60, seed=3)
    assert first == fuzz.generate(rows, n=60, seed=3)
    assert len(first) == 60
    assert first != fuzz.generate(rows, n=60, seed=4)
    assert all(r.verdict in ("block", "ask") and r.command != r.plain for r in first)


def test_every_family_respells_some_row_and_no_allow_row_is_respelled():
    everything = fuzz.generate(DATA["rows"], n=10 ** 6)
    families = {r.family for r in everything}
    folds = "letter-case" not in families
    assert families | ({"letter-case"} if folds else set()) == set(fuzz.FAMILIES)
    allow_ids = {row["id"] for row in DATA["rows"] if row["verdict"] == "allow"}
    assert not {r.row_id for r in everything} & allow_ids


def test_a_changed_verdict_is_listed_with_its_respelling_and_fails_the_cli(monkeypatch, capsys):
    row = next(r for r in DATA["rows"] if r["id"] == "path-spelling-03")
    wrong = {**DATA, "rows": [{**row, "verdict": "ask"}]}
    result = fuzz.run(wrong, n=6)
    assert result["count"] == 6
    assert [m["got"] for m in result["mismatches"]] == ["block"] * 6
    assert all(m["command"] in fuzz.report(result) for m in result["mismatches"])
    monkeypatch.setattr(corpus, "load", lambda path=None: wrong)
    assert cli.main(["corpus", "fuzz", "--n", "6"]) == 1
    assert "DIFF path-spelling-03" in capsys.readouterr().out

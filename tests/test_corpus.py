"""The conformance corpus is replayed through the real hook, and the replay reports honestly."""

import json
from pathlib import Path

import pytest

from damage_control import cli, corpus


def test_every_corpus_row_gets_its_recorded_verdict_from_the_real_hook():
    data = corpus.load()
    bad = [(r["id"], r["command"], r["verdict"], r["got"]) for r in corpus.replay(data) if not r["ok"]]
    assert not bad, bad


def test_each_class_pairs_its_respellings_with_a_control_that_stays_allowed():
    data = corpus.load()
    lacking = [name for name in data["classes"]
               if not any(r["class"] == name and r["verdict"] == "allow" for r in data["rows"])]
    assert not lacking, lacking


def test_the_replay_flags_a_row_whose_recorded_verdict_is_wrong(capsys, tmp_path):
    data = corpus.load()
    row = next(r for r in data["rows"] if r["verdict"] == "block")
    wrong = {**data, "rows": [{**row, "verdict": "allow"}]}
    results = corpus.replay(wrong)
    assert [r["ok"] for r in results] == [False]
    assert row["id"] in corpus.table(results, data["classes"])


def test_the_cli_exits_nonzero_and_lists_the_failure_when_a_row_is_wrong(monkeypatch, capsys):
    data = corpus.load()
    row = next(r for r in data["rows"] if r["verdict"] == "block")
    monkeypatch.setattr(corpus, "load", lambda path=None: {**data, "rows": [{**row, "verdict": "allow"}]})
    assert cli.main(["corpus", "run", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False and [f["id"] for f in report["failures"]] == [row["id"]]


@pytest.mark.parametrize("mutate", [
    lambda row: row.pop("source"),
    lambda row: row.update(verdict="deny"),
    lambda row: row.update({"class": "no-such-class"}),
])
def test_a_malformed_row_is_refused(mutate):
    data = corpus.load()
    row = dict(data["rows"][0])
    mutate(row)
    with pytest.raises(corpus.CorpusError):
        corpus.validate({**data, "rows": [row]})


def test_row_ids_are_unique():
    data = corpus.load()
    with pytest.raises(corpus.CorpusError):
        corpus.validate({**data, "rows": [data["rows"][0], data["rows"][0]]})


def test_the_docs_page_is_current():
    import subprocess
    import sys
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run([sys.executable, str(root / "tools" / "conformance_doc.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

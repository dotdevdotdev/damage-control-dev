"""``doctor`` reports Claude Code's sandbox state from settings files: informational, read-only."""

import json
import os
import subprocess
import sys

import pytest

from damage_control import sandbox

ASK = "Bash(dangerouslyDisableSandbox:true)"

FIXTURES = {
    "on-strict": ({"sandbox": {"enabled": True, "allowUnsandboxedCommands": False}}, ["sandbox-enabled", "sandbox-retry"], "closed"),
    "on-retry-open-no-ask": ({"sandbox": {"enabled": True}}, ["sandbox-enabled", "sandbox-retry", "sandbox-retry-ask"], "OPEN"),
    "on-retry-open-with-ask": ({"sandbox": {"enabled": True}, "permissions": {"ask": [ASK]}},
                               ["sandbox-enabled", "sandbox-retry", "sandbox-retry-ask"], "OPEN"),
    "off": ({"sandbox": {"enabled": False}}, ["sandbox-off"], "explicitly disabled"),
    "unset": ({"model": "x"}, ["sandbox-off"], "not enabled"),
    "garbled-section": ({"sandbox": "yes"}, ["sandbox-off"], "not enabled"),
}


def _run(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return sandbox.findings(str(path), tmp_path)


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_fixture_states(tmp_path, name):
    content, codes, word = FIXTURES[name]
    got = _run(tmp_path, content)
    assert [f.code for f in got] == codes
    assert word in " ".join(f.message for f in got)
    assert {f.level for f in got} == {"info"}


def test_ask_rule_reported_only_when_present(tmp_path):
    with_rule = _run(tmp_path, FIXTURES["on-retry-open-with-ask"][0])
    without = _run(tmp_path, FIXTURES["on-retry-open-no-ask"][0])
    assert "is set" in with_rule[-1].message
    assert "no ask rule" in without[-1].message


def test_missing_and_invalid_are_reported_not_guessed(tmp_path):
    missing = sandbox.findings(str(tmp_path / "nope.json"), tmp_path)
    assert [f.code for f in missing] == ["sandbox-no-settings"]
    invalid = _run(tmp_path, "{not json")
    assert [f.code for f in invalid] == ["sandbox-unreadable", "sandbox-no-settings"]
    assert {f.level for f in missing + invalid} == {"info"}


def test_project_files_override_user_and_lists_merge(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(json.dumps({"sandbox": {"enabled": True}, "permissions": {"ask": [ASK]}}))
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "settings.local.json").write_text(json.dumps({"sandbox": {"allowUnsandboxedCommands": False}}))
    monkeypatch.setenv("HOME", str(home))
    got = sandbox.findings(None, project)
    assert [f.code for f in got] == ["sandbox-enabled", "sandbox-retry"]
    assert "closed" in got[1].message


def test_read_only(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"sandbox": {"enabled": True}}))
    before = (path.read_bytes(), path.stat().st_mtime_ns, sorted(p.name for p in tmp_path.iterdir()))
    sandbox.findings(str(path), tmp_path)
    assert (path.read_bytes(), path.stat().st_mtime_ns, sorted(p.name for p in tmp_path.iterdir())) == before


def test_doctor_cli_carries_the_findings_and_never_fails_on_them(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    settings = home / "settings.json"
    codes = {}
    for state, content in (("open", {"sandbox": {"enabled": True}}), ("garbled", "{not json")):
        settings.write_text(content if isinstance(content, str) else json.dumps(content))
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home)}
        proc = subprocess.run([sys.executable, "-I", "-m", "damage_control.cli", "doctor", "--json", "--settings", str(settings)],
                              capture_output=True, text=True, env=env, cwd=str(home), timeout=120)
        findings = json.loads(proc.stdout)["findings"]
        mine = [f for f in findings if f["code"].startswith("sandbox-")]
        assert mine and {f["level"] for f in mine} == {"info"}
        codes[state] = [f["code"] for f in mine]
    assert codes == {"open": ["sandbox-enabled", "sandbox-retry", "sandbox-retry-ask"],
                     "garbled": ["sandbox-unreadable", "sandbox-no-settings"]}

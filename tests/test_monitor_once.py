"""A ``Monitor`` call that Claude Code also routes through ``Bash`` is judged and audited once.

From Claude Code 2.1.314 a ``Bash`` hook runs on the command a ``Monitor`` call starts, so a host
that registers both matchers gets the same call (one ``tool_use_id``) in two hook processes. Every
run below is the real hook entry as a subprocess, fed the payload Claude Code sends; the audit rows
under the temporary home are the count of judgments.
"""

import json
import subprocess
import sys
import threading

import pytest

from hookrun import run_hook

ID = "toolu_01MONITORONCE"


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def rows(home):
    return [json.loads(line) for f in sorted(home.rglob("*.jsonl")) for line in f.read_text().splitlines()]


def call(home, tool, command, tool_use_id=ID):
    return run_hook("bash", tool, {"command": command}, str(home), home, tool_use_id=tool_use_id)


@pytest.mark.parametrize("command,want,decision", [
    ("tail -f /var/log/system.log", "allow", "allowed"),
    ("rm -rf /", "block", "blocked"),
    ("$(echo rm) -rf /", "ask", "asked"),
])
@pytest.mark.parametrize("order", [("Bash", "Monitor"), ("Monitor", "Bash")])
def test_one_call_seen_by_both_matchers_is_one_judgment_and_one_row(home, command, want, decision, order):
    first = call(home, order[0], command)
    second = call(home, order[1], command)
    assert first == want
    assert second == "allow"  # the duplicate says nothing; the process that judged carries the verdict
    assert [(r["tool_use_id"], r["decision"]) for r in rows(home)] == [(ID, decision)]


def test_concurrent_duplicates_are_judged_once(home):
    results = []

    def go(tool):
        results.append(call(home, tool, "rm -rf /"))

    threads = [threading.Thread(target=go, args=(t,)) for t in ("Bash", "Monitor", "Monitor", "Bash")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["allow", "allow", "allow", "block"]
    assert len(rows(home)) == 1


def test_a_different_command_under_the_same_id_is_judged(home):
    assert call(home, "Bash", "echo hi") == "allow"
    assert call(home, "Monitor", "rm -rf /") == "block"
    assert len(rows(home)) == 2


def test_different_calls_are_each_judged(home):
    for i in range(3):
        assert call(home, "Bash", "echo hi", tool_use_id=f"toolu_{i}") == "allow"
    assert len(rows(home)) == 3


def test_a_call_without_an_id_is_always_judged(home):
    assert call(home, "Monitor", "echo hi", tool_use_id=None) == "allow"
    assert call(home, "Bash", "echo hi", tool_use_id=None) == "allow"
    assert len(rows(home)) == 2


def test_the_same_id_in_another_session_is_judged(home):
    other = {"session_id": "11111111-1111-1111-1111-111111111111"}
    payload = {"cwd": str(home), "hook_event_name": "PreToolUse", "permission_mode": "default",
               "tool_name": "Bash", "tool_input": {"command": "echo hi"}, "tool_use_id": ID, **other}
    assert call(home, "Bash", "echo hi") == "allow"
    proc = subprocess.run([sys.executable, "-I", "-m", "damage_control.hook", "bash"], input=json.dumps(payload),
                          capture_output=True, text=True, env={"HOME": str(home), "PWD": str(home)}, cwd=str(home))
    assert proc.returncode == 0
    assert len(rows(home)) == 2

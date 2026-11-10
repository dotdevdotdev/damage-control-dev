"""Audit rows name the agent that made the call: the payload's agent_id/agent_type, else the env, else main."""

import json

import pytest

from damage_control import corpus
from hookrun import run_hook

ENV = {"AGENTWIRE_AGENT_ID": "env-agent"}


@pytest.fixture
def home(tmp_path):
    (tmp_path / "home").mkdir()
    return tmp_path / "home"


@pytest.fixture
def pack_home(tmp_path):
    return corpus.home_for(tmp_path / "packhome", ["agentwire"])


def row(home):
    (line,) = [l for f in home.rglob("*.jsonl") for l in f.read_text().splitlines()]
    return json.loads(line)


def audit(home, payload_extra=None, env=None):
    run_hook("bash", "Bash", {"command": "rm -rf /"}, str(home), home, env=env, payload_extra=payload_extra)
    return row(home)


def test_subagent_payload_names_the_subagent(home):
    r = audit(home, {"agent_id": "a1b2c3", "agent_type": "Explore"})
    assert (r["agent_id"], r["agent_type"]) == ("a1b2c3", "Explore")


def test_payload_agent_id_wins_over_env(pack_home):
    assert audit(pack_home, {"agent_id": "a1b2c3", "agent_type": "Explore"}, ENV)["agent_id"] == "a1b2c3"


def test_env_is_the_fallback_when_payload_has_no_agent_id(pack_home):
    r = audit(pack_home, env=ENV)
    assert (r["agent_id"], r["agent_type"]) == ("env-agent", None)


def test_main_when_neither_names_an_agent(home):
    r = audit(home)
    assert (r["agent_id"], r["agent_type"]) == ("main", None)


UNVERIFIABLE = "$(echo rm) -rf /"


def raw(home, extra, mode="default"):
    import subprocess
    import sys
    payload = {"session_id": "0" * 8, "cwd": str(home), "hook_event_name": "PreToolUse", "permission_mode": mode,
               "tool_name": "Bash", "tool_input": {"command": UNVERIFIABLE}, **extra}
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "PWD": str(home)}
    return subprocess.run([sys.executable, "-I", "-m", "damage_control.hook", "bash"], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, cwd=str(home), timeout=120)


def test_an_ask_names_the_subagent_asking(home):
    proc = raw(home, {"agent_id": "a1b2c3", "agent_type": "Explore"})
    reason = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert proc.returncode == 0 and reason.startswith("[Explore a1b2c3] ")


def test_an_ask_from_the_main_agent_has_no_label(home):
    reason = json.loads(raw(home, {}).stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert not reason.startswith("[")


READ_LOOP = (
    "bash -c 'while read n; do c=$(curl -s -o /dev/null -w \"%{http_code}\" https://x.test/$n.com); "
    "if [ \"$c\" = 429 ]; then sleep 10; fi; echo \"$n $c\" >> r.txt; done < n.txt'"
)


def test_a_read_loop_with_a_substitution_result_is_not_unverifiable(home):
    """`c=$(…)` was resolved to its first word and spliced into the `bash -c` payload, which then asked."""
    assert run_hook("bash", "Bash", {"command": READ_LOOP}, str(home), home, mode="bypassPermissions") == "allow"

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

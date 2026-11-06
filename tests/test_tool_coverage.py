"""Which Claude Code tools are judged: Monitor and LSP through the real hook, and the decision table.

Every hook answer below comes from ``python -I -m damage_control.hook`` as a subprocess, fed the payload
Claude Code sends. Registration is checked on a settings dict in memory: nothing here touches a real
settings file or the real home.
"""

import copy
import json

import pytest

from damage_control import adapter, claude_code as cc, install, toolcoverage
from hookrun import run_hook


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def monitor(home, command, **extra):
    return run_hook("bash", "Monitor", {"description": "watch", "command": command, **extra}, str(home), home)


# -- Monitor runs a command: the same rules as Bash ----------------------------------------------------------

@pytest.mark.parametrize("command,want", [
    ("rm -rf /", "block"),
    ("while true; do rm -rf /; done", "block"),
    ("$(echo rm) -rf /", "ask"),
    ("tail -f /var/log/system.log", "allow"),
    ("while true; do echo tick; sleep 5; done", "allow"),
])
def test_monitor_command_gets_the_verdict_bash_gives(home, command, want):
    assert monitor(home, command) == want
    assert run_hook("bash", "Bash", {"command": command}, str(home), home) == want


def test_a_monitor_with_a_url_and_no_command_has_nothing_to_judge(home):
    assert run_hook("bash", "Monitor", {"description": "watch", "url": "wss://example.com/events"}, str(home), home) == "allow"


def test_monitor_ask_follows_the_modes_of_an_ask(home):
    ask = "$(echo rm) -rf /"
    assert monitor(home, ask) == "ask"
    assert run_hook("bash", "Monitor", {"command": ask}, str(home), home, env={"DAMAGE_CONTROL_UNATTENDED": "1"}) == "block"
    assert run_hook("bash", "Monitor", {"command": ask}, str(home), home, mode="bypassPermissions") == "ask"  # unverifiable: bypass never demotes


# -- LSP reads a file by path: the same ladder as Read -------------------------------------------------------

@pytest.mark.parametrize("path,want", [
    ("{home}/.ssh/id_rsa", "block"),
    ("{home}/project/.env", "block"),
    ("{home}/project/main.py", "allow"),
])
def test_lsp_file_path_gets_the_verdict_read_gives(home, path, want):
    path = path.format(home=home)
    lsp = {"operation": "hover", "filePath": path, "line": 1, "character": 1}
    assert run_hook("read", "LSP", lsp, str(home), home) == want
    assert run_hook("read", "Read", {"file_path": path}, str(home), home) == want


def test_an_lsp_call_with_no_file_path_has_nothing_to_judge(home):
    assert run_hook("read", "LSP", {"operation": "workspaceSymbol", "query": "main"}, str(home), home) == "allow"


# -- registration: owned, idempotent, removable --------------------------------------------------------------

def desired():
    return {m: cc.wanted_hook("/usr/bin/python3", k, 10, True) for m, k in cc.MATCHERS.items()}


def reg(settings, matchers):
    return install.register(settings, {cc.PRE_TOOL_USE: matchers}, [])


def test_the_new_matchers_are_registered_under_their_kinds():
    assert cc.MATCHERS["Monitor"] == "bash" and cc.MATCHERS["LSP"] == "read"
    settings = {}
    reg(settings, desired())
    registered = {o.matcher: cc.kind_of(o.hook) for o in cc.owned_entries(settings)}
    assert registered == cc.MATCHERS


def test_registering_twice_changes_nothing_and_upgrading_adds_only_the_new_matchers():
    old = {m: h for m, h in desired().items() if m not in ("Monitor", "LSP")}
    foreign = {"matcher": "Bash", "hooks": [{"type": "command", "command": "/opt/mine"}]}
    settings = {"hooks": {"PreToolUse": [foreign]}}
    reg(settings, old)
    before = copy.deepcopy(settings)
    assert reg(settings, desired()) is True
    added = [e["matcher"] for e in settings["hooks"]["PreToolUse"] if e not in before["hooks"]["PreToolUse"]]
    assert sorted(added) == ["LSP", "Monitor"]
    assert foreign in settings["hooks"]["PreToolUse"]
    once = copy.deepcopy(settings)
    assert reg(settings, desired()) is False and settings == once


def test_uninstall_removes_every_entry_of_ours_including_the_new_ones_and_only_those():
    foreign = {"matcher": "Monitor", "hooks": [{"type": "command", "command": "/opt/mine"}]}
    settings = {"hooks": {"PreToolUse": [foreign]}}
    reg(settings, desired())
    assert install.unregister(settings, []) is True
    assert settings == {"hooks": {"PreToolUse": [foreign]}}


def test_doctor_reports_a_missing_new_matcher():
    settings = {}
    reg(settings, {m: h for m, h in desired().items() if m != "Monitor"})
    findings = install._drift(cc.owned_entries(settings), "/usr/bin/python3", None, True)
    assert any(f.level == "bad" and "Monitor" in f.message for f in findings)


# -- the decision table ---------------------------------------------------------------------------------------

def test_the_judged_decisions_are_exactly_the_registered_matchers():
    assert set(toolcoverage.JUDGED_NAMES) == set(cc.MATCHERS)


def test_every_tool_the_hooks_handle_is_registered():
    handled = {t for tools, _ in adapter.HOOK_KINDS.values() if tools for t in tools}
    assert handled == {m for m in cc.MATCHERS if m != "mcp__.*"}


def test_a_tool_name_has_one_decision():
    names = [n for d in toolcoverage.DECISIONS for n in d.names]
    assert len(names) == len(set(names))


def test_an_out_of_scope_tool_has_no_hook_and_a_reason():
    for d in toolcoverage.DECISIONS:
        assert d.decision in (toolcoverage.JUDGED, toolcoverage.OUT_OF_SCOPE)
        assert d.harm and d.reason
        if d.decision == toolcoverage.OUT_OF_SCOPE:
            assert not any(n.split(" ")[0] in cc.MATCHERS for n in d.names), d.names


def test_the_reviewed_tools_are_all_in_the_table():
    named = {n.split(" ")[0] for d in toolcoverage.DECISIONS for n in d.names}
    reviewed = {"WebFetch", "WebSearch", "Agent", "Workflow", "Skill", "Monitor", "AskUserQuestion", "ExitPlanMode",
                "SubagentHandback", "LSP", "TodoWrite", "RemoteTrigger", "CronCreate", "REPL"}
    assert reviewed <= named

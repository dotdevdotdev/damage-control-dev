"""The optional ``agentwire`` pack: off by default, no trace of it in the engine, and the same judgments when on.

The command-line rows live in the conformance corpus (``pack-*`` classes). This file covers what a row
cannot carry: the file-tool and MCP hooks, the profile fragment, and the rule that keeps the core clean.
"""

import json
import re
from pathlib import Path

import pytest

from damage_control import corpus, engine, groups, packs
from damage_control.profile import GENERIC, ProfileError, merge_fragments
from hookrun import run_hook

NAME = "agent" + "wire"
SRC = Path(__file__).resolve().parent.parent / "src" / "damage_control"
PACK_FILES = {"agentwire.yaml", "agentwire.json"}
SCHED = f"~/.{NAME}/scheduler.yaml"


@pytest.fixture
def off_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return home


@pytest.fixture
def on_home(tmp_path):
    return corpus.home_for(tmp_path / "home", ["agentwire"])


def test_the_core_has_no_trace_of_the_orchestrator():
    hits = []
    for path in sorted(SRC.rglob("*")):
        if not path.is_file() or path.suffix == ".pyc" or path.name in PACK_FILES | {"corpus_rows.json"}:
            continue
        if NAME in path.name.lower() or NAME in path.read_text(errors="replace").lower():
            hits.append(str(path.relative_to(SRC)))
    assert not hits, hits


def test_only_the_pack_files_and_its_corpus_rows_carry_the_name():
    named = {p.name for p in SRC.rglob("*") if p.is_file() and p.suffix != ".pyc" and NAME in p.read_text(errors="replace").lower()}
    assert named == PACK_FILES | {"corpus_rows.json"}
    data = corpus.load()
    stray = [r["id"] for r in data["rows"] if NAME in json.dumps(r).lower() and not r["id"].startswith("pack-")]
    assert not stray, stray
    assert not [name for name, text in data["classes"].items() if NAME in text.lower() and not name.startswith("pack-")]


def test_the_pack_is_registered_from_its_own_header_and_is_off_without_a_decision(tmp_path):
    entry = groups.registry()["agentwire"]
    assert (entry.kind, entry.rules, entry.kernel) == ("pack", ("agentwire.yaml",), False)
    rows = {r["name"]: r for r in packs.overview(tmp_path / "damagecontrol.yml", None, None)}
    assert rows["agentwire"]["enabled"] is False
    assert groups.unclassified() == {}


def test_enabling_the_pack_goes_through_the_human_only_mechanism(tmp_path):
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, "-I", "-m", "damage_control", "packs", "enable", "agentwire"], stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}, timeout=120)
    assert proc.returncode != 0 and "human" in proc.stdout + proc.stderr or "terminal" in proc.stdout + proc.stderr
    assert not (tmp_path / ".damage-control" / "damagecontrol.yml").exists()


def test_the_pack_off_loads_none_of_its_rules():
    config = engine.load_effective_config()
    ids = {r.get("id") for r in config["bashToolPatterns"]} | {p.get("id") for p in config["mcpToolPolicies"]}
    assert not {i for i in ids if i and ("agentwire" in i)}
    assert "profileFragments" not in config


def test_the_pack_on_loads_every_rule_id_it_declares(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(corpus.home_for(tmp_path / "home", ["agentwire"])))
    config = engine.load_effective_config()
    ids = {r.get("id") for r in config["bashToolPatterns"]} | {p.get("id") for p in config["mcpToolPolicies"]}
    assert {
        "agentwire.tmux-kill-session-targeting-agentwire-sessions", "agentwire.agentwire-destroy-if-implemented-destroys-agentwire-state",
        "agentwire.agentwire-force-remove-operations", "agentwire.recursive-forced-rm-of-the-agentwire-directory-itself-destro",
        "outbound.agentwire-email", "outbound.agentwire-quo", "mcp.agentwire.worktree-remove", "mcp.agentwire.worktree-prune",
        "mcp.agentwire.session-kill", "mcp.agentwire.pane-kill", "mcp.agentwire.session-recreate", "mcp.agentwire.machine-remove",
    } <= ids
    assert not config.get("_duplicate_rule_ids") and not config.get("_parse_failures")


@pytest.mark.parametrize("tool", ["worktree_remove", "worktree_prune", "session_kill", "pane_kill", "session_recreate", "machine_remove"])
def test_each_teardown_tool_asks_with_the_pack_on_and_is_unclassified_without_it(tool, on_home, off_home):
    name = f"mcp__{NAME}__{tool}"
    assert run_hook("mcp", name, {}, "/tmp", on_home) == "ask"
    assert run_hook("mcp", name, {}, "/tmp", off_home) == "allow"


@pytest.mark.parametrize("tool", ["worktree_remove", "session_kill"])
def test_a_teardown_tool_fails_closed_unattended_unless_granted(tool, on_home):
    name = f"mcp__{NAME}__{tool}"
    unattended = {"AGENTWIRE_UNATTENDED": "1"}
    assert run_hook("mcp", name, {}, "/tmp", on_home, mode="bypassPermissions", env=unattended) == "block"
    granted = {**unattended, "AGENTWIRE_UNATTENDED_ALLOW": f"mcp.{NAME}.{tool.replace('_', '-')}"}
    assert run_hook("mcp", name, {}, "/tmp", on_home, mode="bypassPermissions", env=granted) == "allow"


@pytest.mark.parametrize("tool, args, expected", [
    ("email_send", {"to": ["a@example.com"], "subject": "hi", "body": "x"}, "ask"),
    ("quo_send", {"to": "+15550100", "body": "x"}, "ask"),
])
def test_the_outbound_tools_get_the_verdict_of_their_shell_command(tool, args, expected, on_home, off_home):
    name = f"mcp__{NAME}__{tool}"
    assert run_hook("mcp", name, args, "/tmp", on_home) == expected
    assert run_hook("mcp", name, args, "/tmp", off_home) == "allow"


def test_the_outbound_tools_follow_the_unattended_grants_of_the_pack(on_home):
    unattended = {"AGENTWIRE_UNATTENDED": "1"}
    mail = {"to": ["a@example.com"], "subject": "hi"}
    assert run_hook("mcp", f"mcp__{NAME}__email_send", mail, "/tmp", on_home, mode="bypassPermissions", env=unattended) == "allow"
    assert run_hook("mcp", f"mcp__{NAME}__quo_send", {"to": "+15550100"}, "/tmp", on_home, mode="bypassPermissions", env=unattended) == "block"


@pytest.mark.parametrize("tool, path, verdict", [
    ("Edit", f"~/.{NAME}/scheduler.yaml", "block"),
    ("Write", f"~/.{NAME}/config.yaml", "block"),
    ("Edit", f"~/.{NAME}/damagecontrol.yml", "block"),
    ("Edit", f"~/.{NAME}/damage-control/core.yaml", "block"),
    ("Edit", f"~/.{NAME}/hooks/damage-control/bash.py", "block"),
    ("Edit", f"/srv/proj/.{NAME}.tasks.yml", "block"),
    ("Edit", f"/srv/proj/.{NAME}.tasks.proposed.yml", "allow"),
    ("Edit", f"/srv/proj/.{NAME}.yml", "allow"),
    ("Edit", f"~/.{NAME}/wiki/page.md", "allow"),
])
def test_file_tools_judge_the_pack_paths(tool, path, verdict, on_home, off_home):
    expanded = path.replace("~", str(on_home))
    kind = tool.lower()
    assert run_hook(kind, tool, {"file_path": expanded, "content": "x", "old_string": "a", "new_string": "b"}, "/tmp", on_home) == verdict
    assert run_hook(kind, tool, {"file_path": path.replace("~", str(off_home)), "content": "x", "old_string": "a", "new_string": "b"},
                    "/tmp", off_home) == "allow"


def test_the_task_file_block_names_the_propose_and_promote_remedy(on_home):
    import subprocess
    import sys

    payload = {"session_id": "s", "cwd": "/tmp", "hook_event_name": "PreToolUse", "permission_mode": "default",
               "tool_name": "Edit", "tool_input": {"file_path": f"/srv/proj/.{NAME}.tasks.yml", "old_string": "a", "new_string": "b"}}
    proc = subprocess.run([sys.executable, "-I", "-m", "damage_control.hook", "edit"], input=json.dumps(payload), capture_output=True,
                          text=True, env={"PATH": "/usr/bin:/bin", "HOME": str(on_home)}, cwd=str(on_home), timeout=120)
    assert proc.returncode == 2 and f"{NAME} tasks promote" in proc.stderr


def test_a_secret_of_the_pack_is_unreadable_through_the_read_tool_only_when_the_pack_is_on(on_home, off_home):
    secret = f"{{home}}/.{NAME}/credentials/token"
    assert run_hook("read", "Read", {"file_path": secret.format(home=on_home)}, "/tmp", on_home) == "block"
    assert run_hook("read", "Read", {"file_path": secret.format(home=off_home)}, "/tmp", off_home) == "allow"


# --- the profile fragment ------------------------------------------------------------------------


def test_a_fragment_only_adds_to_the_host_profile():
    base = GENERIC._replace(protected_paths=("~/x",), default_unattended_allow=("git.add",))
    merged = merge_fragments(base, [{"protected_paths": ["~/y"], "default_unattended_allow": ["git.commit"], "data_consumers": ["tool"]}])
    assert merged.protected_paths == ("~/x", "~/y")
    assert merged.default_unattended_allow == ("git.add", "git.commit")
    assert merged.data_consumers == ("tool",)
    assert merge_fragments(base, []) == base


def test_a_fragment_names_the_unattended_marker_only_while_the_host_left_the_default():
    fragment = [{"unattended_env": "MARKER", "unattended_allow_env": "MARKER_ALLOW"}]
    assert merge_fragments(GENERIC, fragment).unattended_env == "MARKER"
    hosted = GENERIC._replace(unattended_env="HOST_MARKER")
    assert merge_fragments(hosted, fragment).unattended_env == "HOST_MARKER"


@pytest.mark.parametrize("fragment", [
    ["not a mapping"],
    [{"config_dir": "~/elsewhere"}],
    [{"unattended_env": 1}],
    [{"audit": "x"}],
    [{"mcp_command_templates": [["only-a-tool"]]}],
])
def test_a_malformed_fragment_is_refused_not_ignored(fragment):
    with pytest.raises(ProfileError):
        merge_fragments(GENERIC, fragment)


def test_a_fragment_cannot_move_the_config_home_or_the_policy_file():
    from damage_control.profile import FRAGMENT_FIELDS

    assert not {"config_dir", "config_dir_env", "home_alias", "extra_rules_dirs", "groups", "default_packs",
                "unattended_block_notifier"} & set(FRAGMENT_FIELDS)


def test_a_fragment_in_an_overlay_file_is_not_honoured(tmp_path, monkeypatch):
    home = tmp_path / "home"
    overlay = home / ".damage-control" / "damage-control"
    overlay.mkdir(parents=True)
    (overlay / "mine.yaml").write_text("profile:\n  protected_paths: ['~/overlay-claimed']\n")
    monkeypatch.setenv("HOME", str(home))
    config = engine.load_effective_config()
    assert "profileFragments" not in config
    assert "~/overlay-claimed" not in engine.PROTECTED_CONTROL_PLANE_PATHS


def test_the_pack_declares_the_unattended_names_the_docs_state(on_home, monkeypatch):
    monkeypatch.setenv("HOME", str(on_home))
    engine.load_effective_config()
    try:
        assert (engine.PROFILE.unattended_env, engine.PROFILE.unattended_allow_env) == ("AGENTWIRE_UNATTENDED", "AGENTWIRE_UNATTENDED_ALLOW")
        assert sorted(engine.DEFAULT_UNATTENDED_ALLOW) == sorted([
            "git.add", "git.add-u", "git.commit", "git.push", "gh.pr-create", "outbound.agentwire-email",
            "tooldef.uv-run-a-script-in-project-environment", "tooldef.uv-run-a-command-in-project-environment"])
        text = (Path(__file__).resolve().parent.parent / "docs" / "agentwire-pack.md").read_text()
        assert "AGENTWIRE_UNATTENDED" in text and "AGENTWIRE_UNATTENDED_ALLOW" in text
    finally:
        engine.install_profile(GENERIC)


def test_every_default_grant_of_the_pack_names_a_rule_that_exists(on_home, monkeypatch):
    monkeypatch.setenv("HOME", str(on_home))
    config = engine.load_effective_config()
    try:
        ids = {r.get("id") for r in config["bashToolPatterns"]}
        missing = [g for g in engine.PROFILE.default_unattended_allow if g not in ids]
        assert not missing, missing
    finally:
        engine.install_profile(GENERIC)


def test_the_pack_fragment_in_the_shipped_json_matches_its_yaml_source():
    yaml = pytest.importorskip("yaml")
    rules = SRC / "rules"
    assert json.loads((rules / "agentwire.json").read_text()) == yaml.safe_load((rules / "agentwire.yaml").read_text())
    assert re.search(r"^pack:", (rules / "agentwire.yaml").read_text(), re.MULTILINE)

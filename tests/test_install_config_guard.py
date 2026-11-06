"""Registration of the ConfigChange guard: idempotent, additive, removed by uninstall, reported by status."""

import copy
import json
import os
import subprocess
import sys

import pytest

from damage_control import claude_code as cc
from damage_control import install

FOREIGN_PRE = {"matcher": "Bash", "hooks": [{"type": "command", "command": "true"}]}
FOREIGN_CONFIG = {"matcher": "project_settings", "hooks": [{"type": "command", "command": "true"}]}


def desired(interpreter="/usr/bin/python3"):
    return {event: {m: cc.wanted_hook(interpreter, k, 30, True) for m, k in matchers.items()}
            for event, matchers in cc.EVENTS.items()}


def cli(home, *args):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)}
    return subprocess.run([sys.executable, "-I", "-m", "damage_control", *args], env=env, capture_output=True,
                          text=True, timeout=120)


def test_config_guard_is_one_entry_for_the_four_settings_sources():
    assert cc.CONFIG_MATCHERS == {"user_settings|project_settings|local_settings|policy_settings": "config"}
    assert "skills" not in cc.CONFIG_SOURCES


def test_register_is_idempotent_and_writes_both_events():
    settings, created = {}, []
    assert install.register(settings, desired(), created) is True
    assert set(settings["hooks"]) == {cc.PRE_TOOL_USE, cc.CONFIG_EVENT}
    assert created == ["hooks", "hooks.PreToolUse", "hooks.ConfigChange"]
    snapshot = copy.deepcopy(settings)
    assert install.register(settings, desired(), []) is False
    assert settings == snapshot
    assert len(settings["hooks"][cc.CONFIG_EVENT]) == 1


def test_register_keeps_foreign_hooks_and_repairs_a_drifted_guard():
    settings = {"hooks": {cc.PRE_TOOL_USE: [FOREIGN_PRE], cc.CONFIG_EVENT: [copy.deepcopy(FOREIGN_CONFIG)]}}
    install.register(settings, desired(), [])
    assert FOREIGN_PRE in settings["hooks"][cc.PRE_TOOL_USE]
    assert FOREIGN_CONFIG in settings["hooks"][cc.CONFIG_EVENT]
    guard = [h for e in settings["hooks"][cc.CONFIG_EVENT] for h in e["hooks"] if cc.is_ours(h)]
    guard[0]["timeout"] = 1
    assert install.register(settings, desired(), []) is True
    assert install.register(settings, desired(), []) is False


def test_register_moves_a_guard_entry_that_sits_under_the_wrong_event():
    settings = {"hooks": {cc.PRE_TOOL_USE: [{"matcher": "Bash", "hooks": [desired()[cc.CONFIG_EVENT][next(iter(cc.CONFIG_MATCHERS))]]}]}}
    install.register(settings, desired(), [])
    kinds = [(o.event, cc.kind_of(o.hook)) for o in cc.owned_entries(settings)]
    assert (cc.PRE_TOOL_USE, cc.CONFIG_KIND) not in kinds
    assert (cc.CONFIG_EVENT, cc.CONFIG_KIND) in kinds


def test_register_refuses_a_malformed_config_change_list():
    with pytest.raises(install.hc.ConfigError):
        install.register({"hooks": {cc.CONFIG_EVENT: "nope"}}, desired(), [])


def test_unregister_removes_only_ours_and_prunes_what_register_created():
    settings = {"hooks": {cc.CONFIG_EVENT: [copy.deepcopy(FOREIGN_CONFIG)]}}
    created: list = []
    install.register(settings, desired(), created)
    assert install.unregister(settings, created) is True
    assert settings == {"hooks": {cc.CONFIG_EVENT: [FOREIGN_CONFIG]}}

    empty, created = {}, []
    install.register(empty, desired(), created)
    install.unregister(empty, created)
    assert empty == {}


def test_init_status_uninstall_round_trip(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"model": "x"}))
    args = ("--settings", str(path))
    first = cli(home, "init", *args, "--allow-dev-source", "--fail-open")
    assert first.returncode == 0, first.stderr
    assert f"{install.registration_count()} matchers" in first.stdout
    after_first = path.read_text()
    assert set(json.loads(after_first)["hooks"]) == {cc.PRE_TOOL_USE, cc.CONFIG_EVENT}
    assert "already registered" in cli(home, "init", *args, "--allow-dev-source", "--fail-open").stdout
    assert path.read_text() == after_first
    status = cli(home, "status", *args)
    assert status.returncode == 0 and "ConfigChange guard is registered" in status.stdout
    assert cli(home, "uninstall", *args).returncode == 0
    assert json.loads(path.read_text()) == {"model": "x"}


def test_status_flags_an_install_that_predates_the_guard(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    path = tmp_path / "settings.json"
    path.write_text("{}")
    args = ("--settings", str(path))
    assert cli(home, "init", *args, "--allow-dev-source", "--fail-open").returncode == 0
    data = json.loads(path.read_text())
    del data["hooks"][cc.CONFIG_EVENT]
    path.write_text(json.dumps(data))
    status = cli(home, "status", *args)
    assert status.returncode == 1
    assert "ConfigChange guard is not registered" in status.stdout
    assert cli(home, "init", *args, "--allow-dev-source", "--fail-open").returncode == 0
    assert cli(home, "status", *args).returncode == 0


def test_selftest_runs_the_config_hook_and_proves_it_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    real, seen = subprocess.run, []

    def spy(argv, **kwargs):
        done = real(argv, **kwargs)
        if argv[-1] == cc.CONFIG_KIND:
            seen.append((json.loads(kwargs["input"])["source"], done.returncode))
        return done

    monkeypatch.setattr(install.subprocess, "run", spy)
    assert install.selftest(sys.executable) == []
    assert seen == [("skills", 0), ("project_settings", 2)]

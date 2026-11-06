"""The ConfigChange guard, judged by the real hook entrypoint (``python -I -m damage_control.hook config``)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from damage_control import claude_code as cc
from damage_control import install
from hookrun import run_config_hook

ENV = lambda home: {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)}  # noqa: E731


@pytest.fixture
def home(tmp_path):
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def registered(home, tmp_path):
    """A settings file ``init`` registered into, with the install record under the scratch home."""
    path = tmp_path / "proj" / "settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"model": "x", "permissions": {"allow": ["Bash(ls:*)"]}}))
    proc = subprocess.run([sys.executable, "-I", "-m", "damage_control", "init", "--settings", str(path),
                           "--allow-dev-source", "--fail-open"], env=ENV(home), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return path


def edit(path: Path, change) -> Path:
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))
    return path


def unregistered(tmp_path, content) -> Path:
    path = tmp_path / "other.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return path


def audit_rows(home: Path):
    rows = []
    for log in home.rglob("*.jsonl"):
        rows += [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    return [r for r in rows if r.get("tool") == "ConfigChange"]


UNSAFE_CONTENT = {
    "disable-all-hooks": {"disableAllHooks": True},
    "env-home": {"env": {"HOME": "/elsewhere"}},
    "env-config-home": {"env": {"DAMAGE_CONTROL_HOME": "/elsewhere"}},
    "env-unattended-grants": {"env": {"DAMAGE_CONTROL_UNATTENDED_ALLOW": "core.anything"}},
}


@pytest.mark.parametrize("name", sorted(UNSAFE_CONTENT))
@pytest.mark.parametrize("source", ["user_settings", "project_settings", "local_settings"])
def test_unsafe_content_is_blocked_in_any_file(home, tmp_path, name, source):
    path = unregistered(tmp_path, UNSAFE_CONTENT[name])
    assert run_config_hook(source, str(path), home) == "block"


BENIGN_CONTENT = {
    "empty": {},
    "model": {"model": "other"},
    "wider-allow": {"permissions": {"allow": ["Bash(*)", "Read(*)"]}},
    "foreign-hook": {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "true"}]}]}},
    "other-env": {"env": {"EDITOR": "vi"}},
    "hooks-not-disabled": {"disableAllHooks": False},
}


@pytest.mark.parametrize("name", sorted(BENIGN_CONTENT))
def test_benign_change_to_an_unregistered_file_is_allowed(home, tmp_path, name):
    path = unregistered(tmp_path, BENIGN_CONTENT[name])
    assert run_config_hook("project_settings", str(path), home) == "allow"


def test_unregistered_deleted_or_unparseable_file_is_allowed(home, tmp_path):
    assert run_config_hook("local_settings", str(tmp_path / "gone.json"), home) == "allow"
    assert run_config_hook("local_settings", str(unregistered(tmp_path, "{not json")), home) == "allow"


def test_skill_changes_are_allowed_without_judging_the_file(home, tmp_path):
    assert run_config_hook("skills", str(tmp_path / "missing" / "SKILL.md"), home) == "allow"
    assert run_config_hook("skills", str(unregistered(tmp_path, {"disableAllHooks": True})), home) == "allow"


def test_registered_file_untouched_or_edited_elsewhere_is_allowed(home, registered):
    assert run_config_hook("project_settings", str(registered), home) == "allow"
    edit(registered, lambda d: d.update(model="other"))
    edit(registered, lambda d: d["hooks"]["PreToolUse"].append(
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "true"}]}))
    assert run_config_hook("project_settings", str(registered), home) == "allow"


def _drop_config_guard(d):
    del d["hooks"][cc.CONFIG_EVENT]


def _drop_bash_hook(d):
    d["hooks"]["PreToolUse"] = [e for e in d["hooks"]["PreToolUse"] if e["matcher"] != "Bash"]


def _drop_all_hooks(d):
    del d["hooks"]


def _rewrite_args(d):
    d["hooks"]["PreToolUse"][0]["hooks"][0]["args"] = ["-c", "pass"]


def _rematch(d):
    d["hooks"]["PreToolUse"][0]["matcher"] = "NoSuchTool"


def _retime(d):
    d["hooks"][cc.CONFIG_EVENT][0]["hooks"][0]["timeout"] = 1


REGISTRATION_DAMAGE = {
    "config-guard-removed": _drop_config_guard,
    "bash-hook-removed": _drop_bash_hook,
    "all-hooks-removed": _drop_all_hooks,
    "args-rewritten": _rewrite_args,
    "matcher-changed": _rematch,
    "timeout-changed": _retime,
    "hooks-disabled": lambda d: d.update(disableAllHooks=True),
}


@pytest.mark.parametrize("name", sorted(REGISTRATION_DAMAGE))
def test_damage_to_a_registered_file_is_blocked(home, registered, name):
    edit(registered, REGISTRATION_DAMAGE[name])
    assert run_config_hook("project_settings", str(registered), home) == "block"


def test_registered_file_deleted_or_unparseable_is_blocked(home, registered):
    registered.write_text("{not json")
    assert run_config_hook("user_settings", str(registered), home) == "block"
    registered.unlink()
    assert run_config_hook("user_settings", str(registered), home) == "block"


def test_registered_file_reached_through_a_symlink_is_still_judged(home, registered, tmp_path):
    link = tmp_path / "link.json"
    link.symlink_to(registered)
    edit(registered, _drop_all_hooks)
    assert run_config_hook("user_settings", str(link), home) == "block"


def test_policy_change_cannot_be_blocked_but_is_audited_as_observed(home, tmp_path):
    path = unregistered(tmp_path, {"disableAllHooks": True})
    assert run_config_hook("policy_settings", str(path), home) == "allow"
    rows = audit_rows(home)
    assert [r["decision"] for r in rows] == ["observed"]
    assert "disableAllHooks" in rows[0]["blocked_by"]


def test_a_block_is_written_to_the_audit_log(home, tmp_path):
    path = unregistered(tmp_path, {"disableAllHooks": True})
    assert run_config_hook("local_settings", str(path), home) == "block"
    rows = audit_rows(home)
    assert [(r["decision"], r["rule_id"], r["command"]) for r in rows] == [("blocked", "core.config-change", str(path))]
    assert "disableAllHooks" in rows[0]["blocked_by"]


def test_an_allowed_change_is_audited(home, tmp_path):
    path = unregistered(tmp_path, {"model": "x"})
    run_config_hook("local_settings", str(path), home)
    assert [r["decision"] for r in audit_rows(home)] == ["allowed"]


@pytest.mark.parametrize("payload", ["not json", "[]", "{}"])
def test_bad_input_never_exits_zero_for_a_settings_source(home, payload):
    proc = subprocess.run([sys.executable, "-I", "-m", "damage_control.hook", "config"], input=payload,
                          capture_output=True, text=True, env=ENV(home), cwd=str(home), timeout=120)
    assert proc.returncode == 2


def test_status_reports_the_guard_and_doctor_reports_unsafe_settings(home, registered, monkeypatch):
    monkeypatch.setenv("HOME", str(home))
    levels = lambda: {f.code: f.level for f in install.inspect("user", str(registered))}  # noqa: E731
    assert levels()["config-guard"] == "ok"
    edit(registered, _drop_config_guard)
    assert levels()["config-guard"] == "bad"
    edit(registered, lambda d: d.update(disableAllHooks=True))
    assert levels()["unsafe-setting"] == "bad"

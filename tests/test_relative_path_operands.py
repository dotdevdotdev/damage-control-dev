"""Relative path operands resolve against the payload cwd, for every protected class.

A command that names a protected file relative to the directory it runs in is judged as
the file it names, however it is spelled. The first test drives the real hook entrypoint
as a subprocess (exit 2 = block, exit 0 and silence = allow); the rest run in-process so a
symlinked cwd can be built for real.
"""

import json
import os
import subprocess
import sys

import pytest

from damage_control.engine import bundled_rule_sources, bundled_tooldefs_dir, check_command, load_config

FAKE_HOME = "/golden/home"
# Deliberately not under /tmp: the core rules allowlist /tmp, which outranks zero-access.
ELSEWHERE = "/golden/elsewhere"

# (cwd, command, verdict)
CASES = [
    (FAKE_HOME, "echo x > .claude/settings.json", "block"),
    (FAKE_HOME, "echo x | tee .claude/settings.json", "block"),
    (FAKE_HOME, "cp /golden/stage/a .claude/settings.json", "block"),
    (FAKE_HOME, "echo x > .claude/hooks/h.sh", "block"),
    (FAKE_HOME + "/.claude", "echo x > settings.json", "block"),
    (FAKE_HOME + "/.claude/hooks", "echo x > ../settings.json", "block"),
    (FAKE_HOME + "/project", "echo x > ../.claude/settings.json", "block"),
    (FAKE_HOME, "echo hi\necho x > .claude/settings.json", "block"),
    (FAKE_HOME, "echo x > .claude/settings.json  # ask: because", "block"),
    (FAKE_HOME + "/.damage-control", "echo x > damagecontrol.yml", "block"),
    (FAKE_HOME, "echo x > .damage-control/damagecontrol.yml", "block"),
    (ELSEWHERE, "cd ~ && echo x > .claude/settings.json", "block"),
    (FAKE_HOME, "cat .ssh/id_rsa", "block"),
    (FAKE_HOME + "/.ssh", "cat id_rsa", "block"),
    (FAKE_HOME, "rm .claude/notes.txt", "block"),
    (FAKE_HOME + "/.claude", "rm notes.txt", "block"),
    (FAKE_HOME, "echo x >> .bash_history", "block"),
    (ELSEWHERE, "cd ~ && cat .ssh/id_rsa", "block"),
    # what a relative name means depends on where it runs
    (ELSEWHERE, "echo x > .claude/settings.json", "allow"),
    (ELSEWHERE, "cat .ssh/id_rsa", "allow"),
    (ELSEWHERE, "rm .claude/notes.txt", "allow"),
    (FAKE_HOME, "cd " + ELSEWHERE + " && echo x > .claude/settings.json", "allow"),
]


def _hook(cwd, command, tmp_path):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": FAKE_HOME, "PWD": cwd}
    payload = {"session_id": "00000000-0000-0000-0000-000000000000", "cwd": cwd,
               "hook_event_name": "PreToolUse", "permission_mode": "default",
               "tool_name": "Bash", "tool_input": {"command": command}}
    proc = subprocess.run(
        [sys.executable, "-I", "-m", "damage_control.hook", "bash"],
        input=json.dumps(payload), capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=120,
    )
    if proc.returncode == 2:
        return "block"
    if proc.returncode != 0:
        return f"crash-{proc.returncode}: {proc.stderr[-200:]}"
    return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] if proc.stdout.strip() else "allow"


def test_the_real_hook_resolves_relative_operands_against_the_payload_cwd(tmp_path):
    bad = [(cwd, cmd, want, got) for cwd, cmd, want in CASES for got in [_hook(cwd, cmd, tmp_path)] if got != want]
    assert not bad, bad


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "hooks").mkdir(parents=True)
    (home / "project").mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def cfg():
    config = load_config(bundled_rule_sources(), bundled_tooldefs_dir())
    config["safety"] = {"enabled": True, "disabled_rules": []}
    return config


def _decisions(cfg, cwd, commands):
    return {c: check_command(c, cfg, cwd=str(cwd))["decision"] for c in commands}


def test_a_symlinked_cwd_is_judged_by_where_it_lands(home, cfg, tmp_path):
    link = tmp_path / "lnk"
    link.symlink_to(home)
    commands = ["echo x > .claude/settings.json", "echo x > .claude/hooks/h.sh"]
    bad = {c: d for c, d in _decisions(cfg, link, commands).items() if d != "block"}
    assert not bad, bad


def test_dot_and_dotdot_operands_resolve_like_absolute_ones(home, cfg):
    commands = [
        "echo x > ./../.claude/settings.json",
        "echo x > ../.claude/settings.json",
        "echo x > ../project/../.claude/settings.json",
    ]
    bad = {c: d for c, d in _decisions(cfg, home / "project", commands).items() if d != "block"}
    assert not bad, bad


def test_an_operand_that_resolves_outside_the_protected_tree_stays_allowed(home, cfg):
    commands = ["echo x > notes.txt", "echo x > ./sub/settings.json", "cat README"]
    bad = {c: d for c, d in _decisions(cfg, home / "project", commands).items() if d != "allow"}
    assert not bad, bad


def test_a_missing_cwd_adds_no_resolution(cfg):
    assert check_command("echo x > .claude/settings.json", cfg)["decision"] == "allow"

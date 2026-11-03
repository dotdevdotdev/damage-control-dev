"""``# ask: <reason>``: the agent asks the human to decide a command that would be blocked.

Every row drives the real hook entrypoint as a subprocess (exit 2 = block, exit 0 with an
``ask`` envelope = ask). ``# allow:`` has no effect: it is judged as if it were not there.
"""

import json
import os
import subprocess
import sys

import pytest

from hookrun import run_hook

RM = "rm -rf /"
UNATTENDED = {"DAMAGE_CONTROL_UNATTENDED": "1", "DAMAGE_CONTROL_UNATTENDED_ALLOW": "core.rm-with-recursive-or-force-flags"}


@pytest.fixture
def home(tmp_path):
    (tmp_path / "home").mkdir()
    return tmp_path / "home"


def _table(home):
    cp = f"{home}/.claude/settings.json"
    return [
        # (command, mode, env, want)
        (f"{RM} # ask: scratch dir", "default", {}, "ask"),
        (f"{RM} #ask: no space", "default", {}, "ask"),
        (f"cat {home}/.ssh/id_rsa # ask: need the key", "default", {}, "ask"),
        ("echo hi # ask: not needed", "default", {}, "allow"),
        (f"{RM} # ask: x", "bypassPermissions", {}, "ask"),
        (f"{RM} # ask: x", "auto", {}, "ask"),
        (f"{RM} # ask: x", "acceptEdits", {}, "ask"),
        (f"echo x > {cp} # ask: because", "default", {}, "block"),
        (f"echo x > {cp} # ask: because", "bypassPermissions", {}, "block"),
        (f"{RM} # ask:", "default", {}, "block"),
        (f"{RM} # ask:   ", "default", {}, "block"),
        (f"{RM} # allow: x", "default", {}, "block"),
        (f"{RM} # allow: x", "bypassPermissions", {}, "block"),
        (f"echo x > {cp} # allow: x", "default", {}, "block"),
        (f"bash -c '{RM} # ask: x'", "default", {}, "block"),
        (f"bash -c \"{RM} # ask: x\"", "default", {}, "block"),
        (f"{RM} # ask: x\nls", "default", {}, "block"),
        (f"cat <<EOF\n{RM}\n# ask: x\nEOF\n{RM}", "default", {}, "block"),
        (f"{RM} # ask: x", "default", UNATTENDED, "block"),
        (f"{RM} # ask: x", "bypassPermissions", UNATTENDED, "block"),
    ]


def test_the_real_hook_table(home, tmp_path):
    wrong = []
    for command, mode, env, want in _table(home):
        got = run_hook("bash", "Bash", {"command": command}, str(tmp_path), home, mode=mode, env=env)
        if got != want:
            wrong.append((command, mode, sorted(env), want, got))
    assert not wrong


def test_a_script_runs_with_the_comment_on_the_command_but_not_in_the_file(home, tmp_path):
    (tmp_path / "bad.sh").write_text("#!/bin/sh\n# ask: reviewed\nrm -rf /\n")
    assert run_hook("bash", "Bash", {"command": "bash bad.sh"}, str(tmp_path), home) == "block"
    assert run_hook("bash", "Bash", {"command": "bash bad.sh # ask: reviewed"}, str(tmp_path), home) == "ask"
    assert run_hook("bash", "Bash", {"command": "bash bad.sh # ask: reviewed"}, str(tmp_path), home,
                    mode="bypassPermissions") == "ask"
    assert run_hook("bash", "Bash", {"command": "bash bad.sh # allow: reviewed"}, str(tmp_path), home) == "block"


def test_the_ask_shows_the_human_the_block_and_the_agents_reason(home, tmp_path):
    environ = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "PWD": str(tmp_path)}
    payload = {"session_id": "s", "cwd": str(tmp_path), "hook_event_name": "PreToolUse",
               "permission_mode": "bypassPermissions", "tool_name": "Bash",
               "tool_input": {"command": f"{RM} # ask: scratch dir"}}
    proc = subprocess.run([sys.executable, "-I", "-m", "damage_control.hook", "bash"], input=json.dumps(payload),
                          capture_output=True, text=True, env=environ, cwd=str(home), timeout=120)
    assert proc.returncode == 0
    shown = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert shown.startswith("The agent asked for an exception") and "scratch dir" in shown


def test_the_audit_row_keeps_the_reason_and_the_original_rule(home, tmp_path):
    got = run_hook("bash", "Bash", {"command": f"{RM} # ask: scratch dir"}, str(tmp_path), home)
    assert got == "ask"
    rows = [json.loads(line) for p in home.rglob("*.jsonl") for line in p.read_text().splitlines()]
    (row,) = rows
    assert row["decision"] == "asked"
    assert row["escape_reason"] == "scratch dir"
    assert row["escalated_from"] == "block"
    assert row["rule_id"] == "core.rm-with-recursive-or-force-flags"

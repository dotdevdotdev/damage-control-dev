"""The first layer of the settings guard: the tool call that writes a settings file, judged by the real hook."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from damage_control import configguard
from hookrun import run_config_hook, run_hook

ENV = lambda home: {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)}  # noqa: E731

START = {"model": "x", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "true"}]}]}}
OTHER_HOOK = {"PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "false"}]}]}

# (id, the settings object the write leaves behind, verdict with a human present)
CONTENTS = [
    ("disable-all-hooks", {**START, "disableAllHooks": True}, "block"),
    ("disable-all-hooks-no-hooks-key", {"disableAllHooks": True}, "block"),
    ("env-home", {**START, "env": {"HOME": "/elsewhere"}}, "block"),
    ("env-config-home", {**START, "env": {"DAMAGE_CONTROL_HOME": "/elsewhere"}}, "block"),
    ("hooks-removed", {"model": "x"}, "ask"),
    ("hooks-rewritten", {**START, "hooks": OTHER_HOOK}, "ask"),
    ("hooks-emptied", {**START, "hooks": {}}, "ask"),
    ("unrelated-key", {**START, "model": "y"}, "allow"),
    ("hooks-unchanged", dict(START), "allow"),
    ("disable-false", {**START, "disableAllHooks": False}, "allow"),
    ("wider-allow", {**START, "permissions": {"allow": ["Bash(ls:*)"]}}, "allow"),
    ("env-unrelated", {**START, "env": {"DEBUG": "1"}}, "allow"),
]
IDS = [c[0] for c in CONTENTS]


@pytest.fixture
def home(tmp_path):
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def proj(tmp_path):
    path = tmp_path / "proj"
    (path / ".claude").mkdir(parents=True)
    return path


@pytest.fixture
def target(proj):
    path = proj / ".claude" / "settings.local.json"
    path.write_text(json.dumps(START))
    return path


def write(target, home, content, mode="default"):
    return run_hook("write", "Write", {"file_path": str(target), "content": content}, str(target.parent.parent), home, mode)


def shell(proj, home, command, mode="default"):
    return run_hook("bash", "Bash", {"command": command}, str(proj), home, mode)


@pytest.mark.parametrize("name,settings,verdict", CONTENTS, ids=IDS)
def test_write_tool_judges_the_resulting_file(home, target, name, settings, verdict):
    assert write(target, home, json.dumps(settings)) == verdict


@pytest.mark.parametrize("name,settings,verdict", CONTENTS, ids=IDS)
def test_bypass_lifts_only_the_ask(home, target, name, settings, verdict):
    assert write(target, home, json.dumps(settings), "bypassPermissions") == ("allow" if verdict == "ask" else verdict)


@pytest.mark.parametrize("name,settings,verdict", CONTENTS, ids=IDS)
def test_guard_and_tool_call_agree(home, target, name, settings, verdict):
    """One definition of unsafe settings: the ConfigChange guard blocks exactly the files the Write tool blocks."""
    target.write_text(json.dumps(settings))
    guard = run_config_hook("local_settings", str(target), home)
    assert (guard == "block") == (verdict == "block")


@pytest.mark.parametrize("name,settings,verdict", CONTENTS, ids=IDS)
def test_helper_reasons_are_the_guards_reasons(target, name, settings, verdict):
    profile = configguard_profile()
    none = lambda _path: None  # noqa: E731
    found = configguard.settings_write(str(target), json.dumps(settings), profile, none, lambda *_: [])
    assert found.refuse == configguard.unsafe_settings(settings, profile)


def configguard_profile():
    from damage_control import engine
    return engine.PROFILE


def test_registration_removed_from_a_registered_file_blocks(home, proj):
    path = proj / ".claude" / "settings.local.json"
    path.write_text(json.dumps({"model": "x"}))
    proc = subprocess.run([sys.executable, "-I", "-m", "damage_control", "init", "--settings", str(path),
                           "--allow-dev-source", "--fail-open"], env=ENV(home), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert write(path, home, json.dumps({"model": "x"})) == "block"
    assert write(path, home, json.dumps({**json.loads(path.read_text()), "model": "y"})) == "allow"


def test_write_creating_the_file(home, proj):
    path = proj / ".claude" / "settings.local.json"
    assert write(path, home, '{"disableAllHooks": true}') == "block"
    assert write(path, home, '{"model": "x"}') == "allow"


def test_write_of_text_that_is_not_json_is_left_to_the_guard(home, target):
    assert write(target, home, "not json") == "allow"


@pytest.mark.parametrize("relative", [".claude/settings.json", ".claude/settings.local.json"])
def test_user_project_and_local_files_are_all_judged(home, proj, relative):
    path = proj / relative
    assert write(path, home, '{"disableAllHooks": true}') == "block"


@pytest.mark.parametrize("relative", ["settings.json", ".claude/other.json", "docs/.claude/notes.json", "config/settings.local.json"])
def test_other_files_are_not_settings_files(home, proj, relative):
    path = proj / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    assert write(path, home, '{"disableAllHooks": true}') == "allow"


def test_a_symlink_to_a_settings_file_is_judged_by_where_it_lands(home, proj, target):
    link = proj / "link.json"
    link.symlink_to(target)
    assert write(link, home, '{"disableAllHooks": true}') == "block"


EDITS = [
    ("add-disable", '"model": "x"', '"model": "x", "disableAllHooks": true', "block"),
    ("add-env-home", '"model": "x"', '"model": "x", "env": {"HOME": "/e"}', "block"),
    ("unrelated", '"model": "x"', '"model": "z"', "allow"),
    ("drop-hooks-key", START and json.dumps(START)[json.dumps(START).index(', "hooks"'):-1], "", "ask"),
]


@pytest.mark.parametrize("name,old,new,verdict", EDITS, ids=[e[0] for e in EDITS])
def test_edit_tool_judges_the_resulting_file(home, target, name, old, new, verdict):
    target.write_text(json.dumps(START))
    got = run_hook("edit", "Edit", {"file_path": str(target), "old_string": old, "new_string": new}, str(target.parent.parent), home)
    assert got == verdict


def test_edit_whose_result_cannot_be_known_asks_even_under_bypass(home, target):
    call = {"file_path": str(target), "old_string": "no such text", "new_string": '"disableAllHooks": true'}
    assert run_hook("edit", "Edit", call, str(target.parent.parent), home) == "ask"
    assert run_hook("edit", "Edit", call, str(target.parent.parent), home, "bypassPermissions") == "ask"


def test_edit_replace_all_is_applied_everywhere(home, target):
    target.write_text('{"model": "x", "a": "x"}')
    call = {"file_path": str(target), "old_string": '"x"', "new_string": "true", "replace_all": True}
    assert run_hook("edit", "Edit", {**call, "old_string": '"a": "x"', "new_string": '"disableAllHooks": true'},
                    str(target.parent.parent), home) == "block"


def test_notebook_edit_naming_a_settings_file_asks(home, target):
    call = {"notebook_path": str(target), "new_source": '"disableAllHooks": true', "cell_type": "code"}
    assert run_hook("edit", "NotebookEdit", call, str(target.parent.parent), home, "bypassPermissions") == "ask"


SHELL_WRITES = {
    "redirect": "echo '{{}}' > {t}",
    "append": "echo x >> {t}",
    "tee": "echo '{{}}' | tee {t}",
    "tee-append": "echo '{{}}' | tee -a {t}",
    "sed-in-place": "sed -i.bak 's/x/y/' {t}",
    "jq-then-move": "jq '.disableAllHooks=true' {t} > /tmp/dc-new.json && mv /tmp/dc-new.json {t}",
    "jq-redirect": "jq '.disableAllHooks=true' {t} > {t}",
    "copy-over": "cp /tmp/dc-new.json {t}",
    "move-over": "mv /tmp/dc-new.json {t}",
    "heredoc": "cat > {t} <<'EOF'\n{{}}\nEOF",
    "relative-redirect": "echo '{{}}' > .claude/settings.local.json",
    "project-file": "echo '{{}}' > .claude/settings.json",
    "absolute-cd-then-write": "cd {d} && echo '{{}}' > settings.local.json",
    "dd": "echo '{{}}' | dd of={t}",
    "truncate": "truncate -s 0 {t}",
}
SHELL_READS = {
    "cat": "cat {t}",
    "grep": "grep disableAllHooks {t}",
    "jq-read": "jq .hooks {t}",
    "echo-mention": "echo disableAllHooks is a setting > notes.txt",
    "quoted-path": "echo 'write disableAllHooks into .claude/settings.local.json' | wc -c",
    "grep-message": "git log --grep='disableAllHooks in .claude/settings.local.json'",
    "grep-the-key": "grep -rn disableAllHooks .claude/",
    "other-file": "echo '{{}}' > .claude/other.json",
    "plain-settings": "echo '{{}}' > settings.json",
    "diff": "diff {t} /tmp/dc-new.json",
}


@pytest.mark.parametrize("name", list(SHELL_WRITES))
@pytest.mark.parametrize("mode", ["default", "bypassPermissions"])
def test_shell_write_to_a_settings_file_asks_and_bypass_does_not_lift_it(home, proj, target, name, mode):
    assert shell(proj, home, SHELL_WRITES[name].format(t=target, d=target.parent), mode) == "ask"


@pytest.mark.parametrize("name", list(SHELL_READS))
def test_shell_that_only_mentions_or_reads_a_settings_file_is_allowed(home, proj, target, name):
    assert shell(proj, home, SHELL_READS[name].format(t=target)) == "allow"


@pytest.mark.parametrize("body", ["echo '{{}}' > {t}\n", "#!/bin/sh\nset -e\njq '.x=1' {t} > /tmp/o && mv /tmp/o {t}\n"])
def test_a_script_that_writes_a_settings_file_asks(home, proj, target, body):
    script = proj / "fix.sh"
    script.write_text(body.format(t=target))
    assert shell(proj, home, f"bash {script}", "bypassPermissions") == "ask"
    assert shell(proj, home, "bash fix.sh", "bypassPermissions") == "ask"


def test_writing_the_script_that_writes_a_settings_file_asks(home, proj, target):
    call = {"file_path": str(proj / "fix.sh"), "content": f"#!/bin/sh\necho '{{}}' > {target}\n"}
    assert run_hook("write", "Write", call, str(proj), home) == "ask"


def test_unattended_shell_write_is_blocked(home, proj, target):
    env = {"DAMAGE_CONTROL_UNATTENDED": "1"}
    assert run_hook("bash", "Bash", {"command": f"echo x > {target}"}, str(proj), home, env=env) == "block"

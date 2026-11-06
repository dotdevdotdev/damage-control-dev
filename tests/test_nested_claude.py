"""A nested ``claude`` run that loads no hooks is judged by what its options do, however they are spelled.

Each row drives the real hook entrypoint (exit 2 = block). The tiers: an option that removes the guard's hooks
blocks (``--bare``, ``--safe-mode``, ``--settings`` carrying ``disableAllHooks``, a ``--setting-sources`` list
without the user scope); one that redirects or adds config the engine cannot read asks (``--plugin-dir``,
``--settings <file>``, ``CLAUDE_CONFIG_DIR``, a list that keeps the user scope but drops the project or local
one). A plain run and text that only mentions a flag stay allowed.
"""

import pytest

from damage_control import claudeops
from hookrun import run_hook

BLOCK = [
    "claude --bare -p hi", "claude --safe-mode -p hi",
    "claude --settings '{\"disableAllHooks\": true}' -p hi", "claude --settings='{\"disableAllHooks\":true}' -p hi",
    "claude --settings '{\"model\":\"x\",\"DisableAllHooks\":true}' -p hi",
    "claude --setting-sources project,local -p hi", "claude --setting-sources=project -p hi",
    "claude --setting-sources '' -p hi", "claude --setting-sources local,project -p hi",
    # abbreviations
    "claude --bar -p hi", "claude --saf -p hi",
    "claude --setting-s=project -p hi",
    # launchers and wrappers in front
    "sudo claude --bare", "env FOO=1 claude --bare", "timeout 5 claude --safe-mode", "/usr/local/bin/claude --bare",
    "nohup claude --bare &", "uvx --from x claude --bare", "npx -y @anthropic-ai/claude-code@latest --bare -p hi",
    "xargs claude --bare", "( claude --bare )", "claude --bare 2>&1 | cat", "echo hi | claude --bare -p",
    "sh -c 'claude --bare -p hi'", 'bash -c "env X=1 claude --safe-mode"',
    # a name the shell builds
    "c=claude; $c --bare -p hi", "x=--bare; claude $x -p hi",
    # the option is the prompt-looking word: the parser still reads it as an option
    "claude -p --bare",
]
ASK = [
    "claude --setting-sources user -p hi", "claude --setting-sources=user,project -p hi",
    "claude --settings /tmp/settings.json -p hi", "claude --settings=./s.json -p hi",
    "claude --settings '{\"hooks\":' -p hi",
    "claude --plugin-dir ./plugins -p hi", "claude --plugin-dir=./plugins -p hi", "claude --plugin ./p",
    "CLAUDE_CONFIG_DIR=/tmp/cfg claude -p hi", "env CLAUDE_CONFIG_DIR=/tmp/cfg claude -p hi",
    "export CLAUDE_CONFIG_DIR=/tmp/cfg; claude -p hi", "CLAUDE_CONFIG_DIR=/tmp/cfg sh -c 'claude -p hi'",
    "sudo env CLAUDE_CONFIG_DIR=/tmp/cfg claude -p hi",
]
ALLOW = [
    "claude -p 'summarize this'", "claude", "claude --version", "claude mcp list", "claude --model sonnet -p hi",
    "claude --setting-sources user,project,local -p hi", "claude --setting-sources=local,user,project -p hi",
    "claude --settings '{\"model\":\"x\"}' -p hi", "claude --settings '{\"disableAllHooks\":false}' -p hi",
    "claude -p hi -- --bare", "npx @anthropic-ai/claude-code -p hi", "CLAUDE_CODE_DEBUG=1 claude -p hi",
    "sh -c 'claude -p hi'", "echo hi | claude -p 'what is this'",
    # a value option takes the next word even when it looks like a flag the engine knows
    "claude --append-system-prompt-file notes.md -p hi",
    # text that mentions a flag or the variable
    "echo 'claude --bare'", "echo claude --safe-mode", "grep -r 'claude --bare' docs",
    "echo CLAUDE_CONFIG_DIR=/tmp/cfg", "printf '%s\\n' 'claude --settings {\"disableAllHooks\":true}'",
    "git log --grep='claude --bare'", "cat notes-about-claude-bare.md",
]


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    return tmp_path_factory.mktemp("nested-claude-home").resolve()


def verdict(command, home):
    return run_hook("bash", "Bash", {"command": command}, str(home), home)


@pytest.mark.parametrize("command", BLOCK)
def test_blocks(command, home):
    assert verdict(command, home) == "block"


@pytest.mark.parametrize("command", ASK)
def test_asks(command, home):
    assert verdict(command, home) == "ask"


@pytest.mark.parametrize("command", ALLOW)
def test_allows(command, home):
    assert verdict(command, home) == "allow"


def test_a_script_the_command_runs_is_read(home, tmp_path):
    (tmp_path / "bad.sh").write_text("#!/bin/sh\nclaude --bare -p hi\n")
    (tmp_path / "ok.sh").write_text("#!/bin/sh\nclaude -p hi\n")
    (tmp_path / "Makefile").write_text("agent:\n\tclaude --safe-mode -p hi\n")
    run = lambda c: run_hook("bash", "Bash", {"command": c}, str(tmp_path), home)  # noqa: E731
    assert [run("bash bad.sh"), run("make agent"), run("bash ok.sh")] == ["block", "block", "allow"]


def test_the_monitor_tool_gets_the_bash_verdict(home):
    run = lambda c: run_hook("bash", "Monitor", {"command": c}, str(home), home)  # noqa: E731
    assert [run("claude --bare -p hi"), run("claude -p hi")] == ["block", "allow"]


def test_the_operations_are_named_from_the_argv():
    assert claudeops.commands(["-p", "hi"]) == []
    assert claudeops.commands(["--bar"]) == ["claude --dc:bare"]
    assert claudeops.commands(["--setting-sources", "project"], ["CLAUDE_CONFIG_DIR=x"]) == [
        "claude --dc:no-user-scope", "claude --dc:config-dir"]

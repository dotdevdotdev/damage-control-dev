"""``explain`` reports the verdict the hook gives, and says how it got there.

Every case runs ``python -I -m damage_control explain`` as a subprocess, the way the hook itself is run.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from damage_control import corpus

SCRIPT = "#!/bin/sh\ngit push --force origin main\n"
FILES = {"run.sh": SCRIPT, "Makefile": "clean:\n\tgit push --force origin main\n"}


def explain(command: str, cwd: str, home: Path, mode: str = "default", as_json: bool = True) -> subprocess.CompletedProcess:
    environ = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "PWD": cwd}
    argv = [sys.executable, "-I", "-m", "damage_control", "explain", "--cwd", cwd, "--mode", mode]
    if as_json:
        argv.append("--json")
    return subprocess.run(argv + [command], capture_output=True, text=True, env=environ, cwd=str(home), timeout=120)


def report(command: str, cwd: str, home: Path, mode: str = "default") -> Dict[str, Any]:
    proc = explain(command, cwd, home, mode)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_explain_gives_the_verdict_the_real_hook_gives_for_every_corpus_row():
    data = corpus.load()
    hook = {r["id"]: r["got"] for r in corpus.replay(data)}

    def judge(command: str, cwd: str, home: Path, tool: str) -> str:
        return report(command, cwd, home)["verdict"]["decision"]

    explained = {r["id"]: r["got"] for r in corpus.replay(data, judge=judge)}
    assert explained == hook


@pytest.fixture
def tree(tmp_path: Path):
    home, root = tmp_path / "home", tmp_path / "tree"
    home.mkdir()
    root.mkdir()
    for name, text in FILES.items():
        (root / name).write_text(text)
    return home, os.path.realpath(root)


RULE = "git.git-push-force-use-force-with-lease"

# (command, mode, the parts of the report it must have)
CASES = [
    ("git push --force origin main", "default",
     {"verdict": {"decision": "block", "rule": RULE, "tier": "block"},
      "judged": [{"text": "git push --force origin main", "matched": [{"id": RULE, "tier": "block"}]}]}),
    ("ls", "default",
     {"verdict": {"decision": "allow", "rule": None, "policy_effect": "unchanged"}, "files": [],
      "judged": [{"text": "ls", "matched": []}]}),
    ("git push --force origin main # ask: the release needs it", "default",
     {"verdict": {"decision": "ask", "rule": RULE},
      "ask_comment": {"reason": "the release needs it", "applied": True, "escalated_from": "block"}}),
    ("ls # ask: just checking", "default",
     {"verdict": {"decision": "allow"}, "ask_comment": {"reason": "just checking", "applied": False}}),
    ("git commit -m wip", "default", {"verdict": {"decision": "ask", "tier": "ask", "engine_decision": "ask"}}),
    ("git commit -m wip", "bypass",
     {"verdict": {"decision": "allow", "engine_decision": "ask"}, "in_effect": {"mode": "bypass"}}),
    ("cat${IFS}notes", "default",
     {"words": {"typed": ["cat${IFS}notes"], "after_separator_expansion": "cat notes", "normalized": ["cat${IFS}notes", "cat notes"]}}),
    ("echo 'a b'", "default", {"words": {"typed": ["echo", "a b"], "normalized": ["echo a b"]}}),
    ("R=ls; $R -la", "default", {"words": {"normalized": ["R=ls", "ls -la"]}}),
    ("sh run.sh", "default",
     {"verdict": {"decision": "block", "rule": RULE},
      "files": [{"kind": "script", "status": "ok", "bytes": len(SCRIPT)}],
      "judged": [{"text": "sh run.sh"}, {"text": SCRIPT, "scripted": True, "matched": [{"id": RULE, "tier": "block"}]}]}),
    ("sh missing.sh", "default", {"files": [{"kind": "script", "status": "missing", "bytes": 0}]}),
    ("make clean", "default", {"verdict": {"decision": "block", "rule": RULE}}),
]


def covers(actual: Any, wanted: Any, where: str = "") -> Optional[str]:
    """None when ``actual`` holds everything in ``wanted`` (dicts by key, lists by position), else where it differs."""
    if isinstance(wanted, dict):
        for key, value in wanted.items():
            miss = covers(actual.get(key) if isinstance(actual, dict) else None, value, f"{where}.{key}")
            if miss:
                return miss
        return None
    if isinstance(wanted, list):
        if not isinstance(actual, list) or len(actual) < len(wanted):
            return f"{where}: wanted {wanted!r}, got {actual!r}"
        for i, value in enumerate(wanted):
            miss = covers(actual[i], value, f"{where}[{i}]")
            if miss:
                return miss
        return None
    return None if actual == wanted else f"{where}: wanted {wanted!r}, got {actual!r}"


def test_the_report_says_which_rule_matched_what_was_read_and_what_the_mode_did(tree):
    home, root = tree
    wrong = [(c, m, miss) for c, m, want in CASES for miss in [covers(report(c, root, home, m), want)] if miss]
    assert not wrong, wrong


def test_the_recipe_file_a_task_runner_reads_is_listed_with_its_size(tree):
    home, root = tree
    recipe = report("make clean", root, home)["files"][-1]
    assert (recipe["kind"], recipe["status"], recipe["bytes"]) == ("recipe", "ok", len(FILES["Makefile"]))


def test_the_json_names_the_profile_the_packs_the_limits_and_the_mode_in_effect(tree):
    home, root = tree
    got = report("ls", root, home, "bypass")
    assert got["cwd"] == root
    assert got["in_effect"]["profile"] and got["in_effect"]["rules_loaded"] > 0
    assert got["in_effect"]["safety_enabled"] is True and got["in_effect"]["mode"] == "bypass"
    assert got["in_effect"]["groups"] and isinstance(got["in_effect"]["packs"], list)
    assert got["limits"]["max_script_bytes"] > 0 and got["limits"]["max_command_chars"] > got["limits"]["command_chars"]


def test_the_human_output_shows_the_same_story_in_sections(tree):
    home, root = tree
    cases = {
        "sh run.sh": ["Words", "Files read", "run.sh", f"{len(SCRIPT)} of", "Judged", "Verdict   block", f"decided by: {RULE}", "In effect"],
        "git push --force origin main # ask: the release needs it":
            ["Verdict   ask", '# ask:      "the release needs it" — turned a block into an ask'],
        "git commit -m wip": ["Verdict   ask", "[ask"],
    }
    wrong = {}
    for command, expected in cases.items():
        proc = explain(command, root, home, as_json=False)
        text = proc.stdout
        missing = [s for s in expected if s not in text]
        if proc.returncode != 0 or missing:
            wrong[command] = (proc.returncode, missing, proc.stderr[-200:])
    assert not wrong, wrong

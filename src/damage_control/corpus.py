"""Replay the conformance corpus through the real hook entrypoint.

The corpus (``corpus_rows.json``) is a list of respellings of operations the rules already judge:
each row gives a command, the working directory it runs in, the verdict Claude Code should act on
(``block`` / ``ask`` / ``allow``) and a class naming the spelling trick. Every row is run as the hook
is run in production: a ``python -I -m damage_control.hook bash`` subprocess fed the same JSON payload,
so the table measures the shipped entrypoint, not a helper behind it.

Tokens in a row's ``command`` and ``cwd``: ``@HOME@`` is the throwaway home directory the hook sees,
``@ROOT@`` is a scratch tree built from the corpus's ``files``. Nothing here touches the real home.
"""

import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Tuple

VERDICTS = ("block", "ask", "allow")
ROW_KEYS = {"id", "class", "command", "cwd", "verdict", "source"}
# A row names the tool that carries its command (default ``Bash``); the hook kind is the one registered for it.
OPTIONAL_ROW_KEYS = {"tool"}
SHELL_TOOLS = ("Bash", "PowerShell", "Monitor")


class CorpusError(Exception):
    """The corpus file is malformed."""


def load(path: Path = None) -> Dict[str, Any]:
    text = path.read_text() if path else resources.files("damage_control").joinpath("corpus_rows.json").read_text()
    data = json.loads(text)
    validate(data)
    return data


def validate(data: Dict[str, Any]) -> None:
    classes = data.get("classes")
    rows = data.get("rows")
    if not isinstance(classes, dict) or not isinstance(rows, list) or not isinstance(data.get("files", {}), dict):
        raise CorpusError("corpus needs 'classes' (object), 'rows' (list) and optionally 'files' (object)")
    seen = set()
    for row in rows:
        if not ROW_KEYS <= set(row) <= ROW_KEYS | OPTIONAL_ROW_KEYS:
            raise CorpusError(f"row {row.get('id', row)!r}: keys must be {sorted(ROW_KEYS)} and optionally {sorted(OPTIONAL_ROW_KEYS)}")
        if row.get("tool", "Bash") not in SHELL_TOOLS:
            raise CorpusError(f"row {row['id']!r}: tool must be one of {SHELL_TOOLS}")
        if row["id"] in seen:
            raise CorpusError(f"duplicate row id {row['id']!r}")
        seen.add(row["id"])
        if row["class"] not in classes:
            raise CorpusError(f"row {row['id']!r}: unknown class {row['class']!r}")
        if row["verdict"] not in VERDICTS:
            raise CorpusError(f"row {row['id']!r}: verdict must be one of {VERDICTS}")


def _build_tree(files: Dict[str, str], root: Path) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o755)


def _hook(command: str, cwd: str, home: Path, tool: str = "Bash") -> str:
    environ = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "PWD": cwd}
    payload = {"session_id": "00000000-0000-0000-0000-000000000000", "cwd": cwd, "hook_event_name": "PreToolUse",
               "permission_mode": "default", "tool_name": tool, "tool_input": {"command": command}}
    proc = subprocess.run([sys.executable, "-I", "-m", "damage_control.hook", "bash"], input=json.dumps(payload),
                          capture_output=True, text=True, env=environ, cwd=str(home), timeout=120)
    if proc.returncode == 2:
        return "block"
    if proc.returncode != 0:
        return f"crash-{proc.returncode}"
    return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] if proc.stdout.strip() else "allow"


@contextmanager
def scratch(files: Dict[str, str]) -> Iterator[Tuple[Path, Callable[[str], str]]]:
    """A throwaway home and file tree: yields ``(home, sub)`` where ``sub`` fills in ``@HOME@`` / ``@ROOT@``."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(os.path.realpath(tmp))
        home, root = base / "home", base / "tree"
        home.mkdir()
        root.mkdir()
        _build_tree(files, root)

        def sub(text: str) -> str:
            return text.replace("@HOME@", str(home)).replace("@ROOT@", str(root))

        yield home, sub


def replay(data: Dict[str, Any], judge: Callable[..., str] = _hook) -> List[Dict[str, Any]]:
    """Run every row through ``judge(command, cwd, home, tool)``; each result is the row plus ``got`` and ``ok``."""
    results = []
    with scratch(data.get("files", {})) as (home, sub):
        for row in data["rows"]:
            got = judge(sub(row["command"]), sub(row["cwd"]), home, row.get("tool", "Bash"))
            results.append({**row, "got": got, "ok": got == row["verdict"]})
    return results


def summarize(results: List[Dict[str, Any]], classes: Dict[str, str]) -> List[Tuple[str, int, int]]:
    """``(class, passed, total)`` in the corpus's class order."""
    return [(name, sum(r["ok"] for r in results if r["class"] == name), sum(r["class"] == name for r in results))
            for name in classes]


def table(results: List[Dict[str, Any]], classes: Dict[str, str]) -> str:
    lines = [f"{'class':28} {'pass':>9}"]
    for name, passed, total in summarize(results, classes):
        lines.append(f"{name:28} {f'{passed}/{total}':>9}")
    failed = [r for r in results if not r["ok"]]
    lines.append(f"{'total':28} {f'{len(results) - len(failed)}/{len(results)}':>9}")
    for r in failed:
        lines.append(f"FAIL {r['id']} [{r['class']}] want {r['verdict']}, got {r['got']}: {r['command']}")
    return "\n".join(lines)

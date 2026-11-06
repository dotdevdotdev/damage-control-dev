"""What a nested ``claude`` run does to the guard, however the command line spells it.

A shell command that starts ``claude`` starts a child that loads its own hooks. Some options and one
environment variable change which hooks or settings the child loads, so a child can run every tool call
with no damage control. The typed spelling is not what matters (abbreviations, ``--opt=value``, a launcher
or wrapper in front, a variable-built name), so this module reads the argv with the option grammar and names
the operation. The engine judges each returned canonical command with the rules in ``control-plane.yaml``:

=================================  ====================================================  =====
canonical command                  the operation                                         tier
=================================  ====================================================  =====
``claude --dc:bare``               ``--bare``: hooks, plugins and settings skipped       block
``claude --dc:safe-mode``          ``--safe-mode``: hooks and plugins skipped            block
``claude --dc:disable-all-hooks``  ``--settings`` carrying ``disableAllHooks``            block
``claude --dc:no-user-scope``      ``--setting-sources`` without the user scope           block
``claude --dc:partial-sources``    ``--setting-sources`` without the project or local     ask
``claude --dc:settings-file``      ``--settings`` a file, or JSON the engine cannot read  ask
``claude --dc:plugin-dir``         ``--plugin-dir``: hooks from a directory               ask
``claude --dc:config-dir``         ``CLAUDE_CONFIG_DIR``: another home for the config     ask
=================================  ====================================================  =====

The user scope is where ``install`` registers the guard by default; a list without it drops the guard.
A list that keeps it but drops the project or local scope may drop a guard registered there, so it asks.
A plain ``claude -p "…"`` names no operation. Standard library only.
"""

import json
from typing import Iterable, List

from damage_control import optiongrammar

CONFIG_DIR_VAR = "CLAUDE_CONFIG_DIR"
_SCOPES = ("user", "project", "local")


def _settings_operation(value: str) -> str:
    """``--settings`` takes a file or a JSON text: the JSON is read, a file is not."""
    text = (value or "").strip()
    if not text.startswith("{"):
        return "settings-file"
    try:
        parsed = json.loads(text)
    except ValueError:
        return "settings-file"
    if not isinstance(parsed, dict):
        return "settings-file"
    disabled = next((v for k, v in parsed.items() if k.lower() == "disableallhooks"), False)
    return "disable-all-hooks" if disabled not in (False, None, 0, "false", "False", "") else ""


def _sources_operation(value: str) -> str:
    sources = {s.strip().lower() for s in (value or "").split(",") if s.strip()}
    if "user" not in sources:
        return "no-user-scope"
    return "partial-sources" if not set(_SCOPES) <= sources else ""


def commands(args: List[str], env: Iterable[str] = ()) -> List[str]:
    """Canonical commands for what the argv after ``claude`` does to the guard.

    ``env`` are the ``NAME=value`` words that reach the child: assignments in front of it, ``env``
    arguments, or an exported variable.
    """
    ops: List[str] = []
    for name, value in optiongrammar.claude_options(args):
        if name == "--bare":
            ops.append("bare")
        elif name == "--safe-mode":
            ops.append("safe-mode")
        elif name == "--settings":
            ops.append(_settings_operation(value))
        elif name == "--setting-sources":
            ops.append(_sources_operation(value))
        elif name == "--plugin-dir":
            ops.append("plugin-dir")
    if any(w.partition("=")[0] == CONFIG_DIR_VAR for w in env):
        ops.append("config-dir")
    return [f"claude --dc:{op}" for op in dict.fromkeys(ops) if op]

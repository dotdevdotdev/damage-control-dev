"""Claude Code as an install target (#1209 M5): where its settings live, what a registration is.

A registration is the exec form Claude Code runs without a shell:
``{"command": <absolute interpreter>, "args": ["-I", "-m", "damage_control.hook", kind, ...],
"timeout": N, "onFailure": "block"}``. Our entries are recognized by the package module name
in ``args`` and by nothing else, under any event: no list of event names decides what is ours.

Standard library only.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

HOOK_MODULE = "damage_control.hook"
HARNESS = "claude-code"

# ``onFailure: "block"`` and exec-form ``args`` need Claude Code >= this. Below it a hook crash,
# timeout or missing interpreter lets the tool call RUN, so registering anyway is a weaker
# config than the one asked for.
ONFAILURE_MIN_VERSION = (2, 1, 295)

# matcher -> hook kind. Several matchers share a kind (Read/Grep/Glob), PowerShell is a
# separate tool name with Bash's input shape, and so is Monitor (its ``command`` runs in the background).
MATCHERS: Dict[str, str] = {
    "Bash": "bash",
    "PowerShell": "bash",
    "Monitor": "bash",
    "Edit": "edit",
    "NotebookEdit": "edit",
    "Write": "write",
    "Read": "read",
    "Grep": "read",
    "Glob": "read",
    "LSP": "read",
    "mcp__.*": "mcp",
}

# The ConfigChange hook fires when a settings file or a skill file changes and can stop the change
# applying to the running session. Skill files cannot loosen this guard, so only the four settings
# sources are registered. One entry, one kind, no per-source split.
CONFIG_EVENT = "ConfigChange"
CONFIG_KIND = "config"
CONFIG_SOURCES = ("user_settings", "project_settings", "local_settings", "policy_settings")
CONFIG_MATCHERS: Dict[str, str] = {"|".join(CONFIG_SOURCES): CONFIG_KIND}

PRE_TOOL_USE = "PreToolUse"

# event -> matcher -> hook kind: every registration of ours.
EVENTS: Dict[str, Dict[str, str]] = {PRE_TOOL_USE: MATCHERS, CONFIG_EVENT: CONFIG_MATCHERS}

SCOPES = ("user", "project", "managed")


def settings_path(scope: str, cwd: Optional[Path] = None) -> Path:
    """The settings file ``scope`` registers into."""
    if scope == "user":
        return Path.home() / ".claude" / "settings.json"
    if scope == "project":
        return (cwd or Path.cwd()) / ".claude" / "settings.json"
    if scope == "managed":
        base = (Path("/Library/Application Support/ClaudeCode") if sys.platform == "darwin"
                else Path("/etc/claude-code"))
        return base / "managed-settings.d" / "50-damage-control.json"
    raise ValueError(f"unknown scope {scope!r}; expected one of {SCOPES}")


def parse_version(text: str) -> Optional[Tuple[int, ...]]:
    m = re.match(r"\s*(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(g) for g in m.groups()) if m else None


def detect_version() -> Optional[Tuple[int, ...]]:
    """The installed Claude Code version, or None when ``claude`` is absent or unreadable."""
    try:
        out = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_version(out)


def version_text(version: Optional[Tuple[int, ...]]) -> str:
    return ".".join(map(str, version)) if version else "unknown"


def supports_fail_closed(version: Optional[Tuple[int, ...]]) -> Optional[bool]:
    """True/False once the version is known; None when it could not be read."""
    return None if version is None else version >= ONFAILURE_MIN_VERSION


def hook_args(kind: str, profile: Optional[str] = None) -> List[str]:
    args = ["-I", "-m", HOOK_MODULE, kind]
    if profile:
        args += ["--profile", profile]
    return args


def is_ours(hook: Any) -> bool:
    """A hook dict that runs this package's hook module."""
    args = hook.get("args") if isinstance(hook, dict) else None
    return isinstance(args, list) and HOOK_MODULE in args


def profile_of(hook: Dict[str, Any]) -> Optional[str]:
    """The ``--profile`` path in one of our hook dicts, if any."""
    args = hook.get("args") or []
    return args[args.index("--profile") + 1] if "--profile" in args and args.index("--profile") + 1 < len(args) else None


def kind_of(hook: Dict[str, Any]) -> Optional[str]:
    args = hook.get("args") or []
    i = args.index(HOOK_MODULE) + 1 if HOOK_MODULE in args else len(args)
    return args[i] if i < len(args) else None


class Owned(NamedTuple):
    event: str
    matcher: Any
    hook: Dict[str, Any]


def hook_events(settings: Dict[str, Any]) -> List[str]:
    """Every event in ``settings`` that holds a list of entries, whether or not we register under it."""
    hooks = settings.get("hooks")
    return [event for event, entries in hooks.items() if isinstance(entries, list)] if isinstance(hooks, dict) else []


def event_entries(settings: Dict[str, Any], event: str) -> Optional[List[Any]]:
    hooks = settings.get("hooks")
    entries = hooks.get(event) if isinstance(hooks, dict) else None
    return entries if isinstance(entries, list) else None


def owned_entries(settings: Dict[str, Any]) -> List[Owned]:
    """Every hook of ours in ``settings`` under any event, with its event and matcher. Malformed entries are skipped."""
    found: List[Owned] = []
    for event in hook_events(settings):
        for entry in event_entries(settings, event) or []:
            inner = entry.get("hooks") if isinstance(entry, dict) else None
            if isinstance(inner, list):
                found.extend(Owned(event, entry.get("matcher"), h) for h in inner if is_ours(h))
    return found


def foreign_entry_count(settings: Dict[str, Any]) -> int:
    """Hooks of the events we register under that are not ours: the user's own, left strictly alone."""
    count = 0
    for event in EVENTS:
        for entry in event_entries(settings, event) or []:
            inner = entry.get("hooks") if isinstance(entry, dict) else None
            count += sum(1 for h in inner if not is_ours(h)) if isinstance(inner, list) else 0
    return count


def wanted_hook(interpreter: str, kind: str, timeout: int, fail_closed: bool,
                profile: Optional[str] = None) -> Dict[str, Any]:
    hook: Dict[str, Any] = {"type": "command", "command": interpreter,
                            "args": hook_args(kind, profile), "timeout": timeout}
    if fail_closed:
        hook["onFailure"] = "block"
    return hook


def selftest_command(interpreter: str, kind: str, profile: Optional[str] = None) -> List[str]:
    return [interpreter, *hook_args(kind, profile)]


def absolute_interpreter() -> str:
    return os.path.abspath(sys.executable)

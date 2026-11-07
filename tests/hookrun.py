"""Drive the real hook entrypoint as a subprocess: what Claude Code does with each exit code."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def run_hook(kind: str, tool: str, tool_input: Dict[str, Any], cwd: str, home: Path,
             mode: str = "default", env: Optional[Dict[str, str]] = None,
             tool_use_id: Optional[str] = None) -> str:
    """``block`` (exit 2), ``ask`` / ``allow`` (exit 0), or ``crash-<code>: <stderr tail>``."""
    environ = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "PWD": cwd, **(env or {})}
    payload = {"session_id": "00000000-0000-0000-0000-000000000000", "cwd": cwd, "hook_event_name": "PreToolUse",
               "permission_mode": mode, "tool_name": tool, "tool_input": tool_input,
               **({"tool_use_id": tool_use_id} if tool_use_id else {})}
    proc = subprocess.run(
        [sys.executable, "-I", "-m", "damage_control.hook", kind],
        input=json.dumps(payload), capture_output=True, text=True, env=environ, cwd=str(home), timeout=120,
    )
    if proc.returncode == 2:
        return "block"
    if proc.returncode != 0:
        return f"crash-{proc.returncode}: {proc.stderr[-200:]}"
    return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] if proc.stdout.strip() else "allow"


def run_config_hook(source: str, file_path: str, home: Path, env: Optional[Dict[str, str]] = None) -> str:
    """The ConfigChange hook as Claude Code runs it: ``block`` (exit 2), ``allow`` (exit 0) or ``crash-<code>``."""
    environ = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), **(env or {})}
    payload = {"session_id": "00000000-0000-0000-0000-000000000000", "transcript_path": str(home / "t.jsonl"),
               "cwd": str(home), "hook_event_name": "ConfigChange", "source": source, "file_path": file_path}
    proc = subprocess.run([sys.executable, "-I", "-m", "damage_control.hook", "config"], input=json.dumps(payload),
                          capture_output=True, text=True, env=environ, cwd=str(home), timeout=120)
    if proc.returncode == 2:
        return "block"
    return "allow" if proc.returncode == 0 else f"crash-{proc.returncode}: {proc.stderr[-200:]}"

"""Read-only report on Claude Code's own sandbox, for ``doctor``.

The sandbox is a different layer from this hook (see docs/sandbox.md). This module only reads
settings files and says what they set; it never writes, and it never scores: every finding is
``info``. A file that is missing or does not parse is reported as such, never guessed at.

Key names are from https://code.claude.com/docs/en/sandboxing and
https://code.claude.com/docs/en/settings-reference.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from damage_control import claude_code as cc
from damage_control.harness_config import ConfigError, read_config

RETRY_ASK_RULE = "Bash(dangerouslyDisableSandbox:true)"
_KEYS = ("enabled", "allowUnsandboxedCommands")


def _layers(settings: Optional[str], cwd: Path) -> List[Path]:
    """Settings files to read, lowest precedence first (user, shared project, project local)."""
    if settings:
        return [Path(settings)]
    return [cc.settings_path("user", cwd), cc.settings_path("project", cwd), cwd / ".claude" / "settings.local.json"]


def findings(settings: Optional[str] = None, cwd: Optional[Path] = None) -> List[Any]:
    from damage_control.install import Finding

    def info(code: str, message: str) -> Any:
        return Finding("info", code, "sandbox: " + message)

    merged: Dict[str, Any] = {}
    ask_rules: List[Any] = []
    out: List[Any] = []
    found = 0
    for path in _layers(settings, cwd or Path.cwd()):
        try:
            raw, data = read_config(path)
        except ConfigError as e:
            out.append(info("sandbox-unreadable", f"{path} was not read ({e}); its sandbox settings are unknown"))
            continue
        if raw is None:
            continue
        found += 1
        section = data.get("sandbox")
        if isinstance(section, dict):
            merged.update({k: section[k] for k in _KEYS if k in section})
        permissions = data.get("permissions")
        if isinstance(permissions, dict) and isinstance(permissions.get("ask"), list):
            ask_rules.extend(permissions["ask"])

    if not found:
        return out + [info("sandbox-no-settings", "no settings file found, so the sandbox state is unknown")]
    enabled = merged.get("enabled")
    if enabled is not True:
        state = "explicitly disabled" if enabled is False else "not enabled"
        return out + [info("sandbox-off", f"{state} in the settings files read (managed settings are not read)")]
    out.append(info("sandbox-enabled", "enabled in the settings files read (managed settings are not read)"))
    if merged.get("allowUnsandboxedCommands") is False:
        out.append(info("sandbox-retry", "unsandboxed retry is closed (allowUnsandboxedCommands is false)"))
    else:
        out.append(info("sandbox-retry", "unsandboxed retry is OPEN (allowUnsandboxedCommands is not false)"))
        out.append(info("sandbox-retry-ask", f"ask rule {RETRY_ASK_RULE} is set" if RETRY_ASK_RULE in ask_rules
                        else f"no ask rule {RETRY_ASK_RULE}; see docs/sandbox.md"))
    return out


def snippet() -> str:
    return json.dumps({"sandbox": {"enabled": True, "allowUnsandboxedCommands": False},
                       "permissions": {"ask": [RETRY_ASK_RULE]}}, indent=2)

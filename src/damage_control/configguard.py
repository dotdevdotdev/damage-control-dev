"""The ``ConfigChange`` guard: judge a settings file by what it would do to the safety posture.

Claude Code fires ``ConfigChange`` when a settings file or a skill file changes, whoever wrote it
(an editor, a shell redirect, ``claude config``, a deleted file), and an exit 2 keeps the change
from applying to the running session. The payload names the changed file (``file_path``) and its
source; it carries no contents, so the guard reads the file as it is now.

A change is refused when the file as it now stands would switch damage control off or point it
somewhere else:

* it sets ``disableAllHooks``;
* its ``env`` sets ``HOME``, the config-home variable or the unattended-grants variable, which
  every hook of ours reads;
* it is a file ``init`` registered into, and the registration is no longer the one ``init``
  wrote (an entry removed, rewritten, re-matched or stripped of ``onFailure``), or the file is
  gone or unreadable.

Nothing else is judged: a hook that is not ours, a wider ``permissions.allow``, any other key.
Those are not decidable from the file alone (there is no earlier copy to compare with), and an
allow rule never overrides a hook's block.

A managed-policy change cannot be blocked by a hook, so it is audited as observed. A skill file
cannot change these settings and is allowed.

Standard library only.
"""

import json
import os
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

from damage_control.policy import ALLOW, BLOCK, Verdict

TOOL = "ConfigChange"
RULE_ID = "core.config-change"
POLICY_SOURCE = "policy_settings"
SKILLS_SOURCE = "skills"

Registration = Optional[Tuple[Dict[str, Any], Dict[str, Any]]]


class Change(NamedTuple):
    source: str
    path: str


def protected_env(profile: Any) -> List[str]:
    """Environment variables a settings ``env`` block must not set: the ones every hook of ours reads to find its policy."""
    return [n for n in ("HOME", profile.config_dir_env, profile.unattended_allow_env) if n]


def unsafe_settings(settings: Dict[str, Any], profile: Any) -> List[str]:
    """Why ``settings``, a parsed settings file, would switch damage control off or redirect it."""
    reasons: List[str] = []
    if settings.get("disableAllHooks") is True:
        reasons.append("`disableAllHooks` is true: every hook, ours included, would stop running")
    env = settings.get("env")
    if isinstance(env, dict):
        reasons += [f"`env.{name}` is set: it redirects where the hooks read their policy"
                    for name in protected_env(profile) if name in env]
    return reasons


def read_settings(path: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """``(settings, None)``, or ``(None, why it cannot be read as a settings object)``."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None, "the file is gone"
    except (OSError, ValueError) as e:
        return None, f"the file cannot be read as JSON ({type(e).__name__})"
    return (data, None) if isinstance(data, dict) else (None, "the file is not a JSON object")


def problems(change: Change, profile: Any, registered: Callable[[str], Registration],
             registration_problems: Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], List[str]]) -> List[str]:
    """Every reason the file ``change`` names must not take effect (empty = fine)."""
    if not change.path:
        return ["the change names no file, so it cannot be judged"]
    settings, unreadable = read_settings(change.path)
    recorded = registered(change.path)
    if settings is None:
        return [f"{unreadable}, and damage control is registered in it"] if recorded else []
    found = unsafe_settings(settings, profile)
    if recorded:
        found += registration_problems(settings, *recorded)
    return found


def decide(payload: Dict[str, Any], profile: Any, registered: Callable[[str], Registration],
           registration_problems: Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], List[str]]) -> Verdict:
    """Allow, block, or (for a managed policy file, which a hook cannot stop) allow and audit as observed."""
    source = str(payload.get("source", ""))
    path = payload.get("file_path")
    path = os.path.abspath(path) if isinstance(path, str) and path else ""
    if source == SKILLS_SOURCE:
        return Verdict(ALLOW, audit=("allowed", (TOOL, path), {"user_approved": False}))
    found = problems(Change(source, path), profile, registered, registration_problems)
    reason = "; ".join(found)
    if source == POLICY_SOURCE:
        return Verdict(ALLOW, audit=("observed", (TOOL, path, reason or "no finding"), {}))
    if found:
        return Verdict(BLOCK, reason, RULE_ID,
                       audit=("blocked", (TOOL, path, reason), {"rule_id": RULE_ID}),
                       stderr=(f"SECURITY: Blocked: {source} change refused: {reason}", f"File: {path}"))
    return Verdict(ALLOW, audit=("allowed", (TOOL, path), {"user_approved": False}))

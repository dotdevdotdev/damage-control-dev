"""``damage-control-dev explain``: report how a shell command was judged.

There is one evaluator. ``explain`` runs the same ``policy.Guard`` the hook runs, on the same loaded
configuration, and records what that run did. The recording half of this module is a handful of
``note_*`` calls the engine makes while it judges; they do nothing unless a ``recording()`` is open, and
they never change a decision. The reporting half turns the record, plus the engine's own answers about
the command's words, into a report.

The module imports nothing from the package at load time (the engine imports it), so the report builder
reaches the engine, adapter and packs lazily.
"""

import functools
import shlex
import threading
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional

_STATE = threading.local()

MODES = ("default", "bypass")
_TEXT_WIDTH = 100
_MAX_JUDGED = 20


class Trace:
    """What one decision did: the texts it judged, the files it read, the verdict the engine returned."""

    def __init__(self) -> None:
        self.judged: List[Dict[str, Any]] = []
        self.files: List[Dict[str, Any]] = []
        self.result: Optional[Dict[str, Any]] = None
        self._current: Optional[Dict[str, Any]] = None


def _trace() -> Optional[Trace]:
    return getattr(_STATE, "trace", None)


@contextmanager
def recording() -> Iterator[Trace]:
    trace = Trace()
    _STATE.trace = trace
    try:
        yield trace
    finally:
        _STATE.trace = None


def note_judged(text: str, scripted: bool, consulted: int) -> None:
    """The rule ladder starts on ``text`` (the typed command, a command hidden in it, or a chunk of a script)."""
    trace = _trace()
    if trace is not None:
        trace._current = {"text": text, "scripted": scripted, "rules_consulted": consulted, "matched": []}
        trace.judged.append(trace._current)


def note_match(rule_id: Optional[str], tier: str) -> None:
    """A rule's pattern matched the text being judged. A match is not always the verdict: exemptions and grants follow."""
    trace = _trace()
    if trace is not None and trace._current is not None:
        trace._current["matched"].append({"id": rule_id, "tier": tier})


def traced_read(read: Callable[[str], Any]) -> Callable[[str], Any]:
    """Wrap ``scriptfile.read_script`` so each file the scan opens is recorded with its size."""

    @functools.wraps(read)
    def wrapper(path: str) -> Any:
        found = read(path)
        trace = _trace()
        if trace is not None:
            trace.files.append({"kind": "script", "path": found.real or path, "status": found.status,
                                "bytes": len(found.text.encode("utf-8", "replace")), "why": found.why})
        return found

    return wrapper


def traced_locate(locate: Callable[[Any], Any]) -> Callable[[Any], Any]:
    """Wrap ``recipefile.locate`` so each recipe file a task runner would read is recorded."""

    @functools.wraps(locate)
    def wrapper(run: Any) -> Any:
        found = locate(run)
        trace = _trace()
        if trace is not None:
            trace.files.append({"kind": "recipe", "path": found.label, "status": found.status,
                                "bytes": found.nbytes, "why": found.why})
        return found

    return wrapper


# ---- the report -----------------------------------------------------------------------------------------

def _words(text: str) -> List[str]:
    try:
        return shlex.split(text, comments=True)
    except ValueError:
        return text.split()


def _rule_info(config: Dict[str, Any], rule_id: Optional[str]) -> Dict[str, Any]:
    if not rule_id:
        return {"tier": None, "source": None}
    for rule in config.get("bashToolPatterns", []):
        if isinstance(rule, dict) and rule.get("id") == rule_id:
            return {"tier": "ask" if rule.get("ask") else "bypassable" if rule.get("bypassable") else "block",
                    "source": rule.get("source")}
    return {"tier": "built-in check", "source": None}


def _effect(result: Dict[str, Any], final: str) -> str:
    """How the policy layer treated the engine's answer: unchanged, or demoted / refused."""
    engine_says = result["decision"]
    if engine_says == "ask" and final == "allow":
        return "the engine asked; the permission mode lowered the ask to an allow"
    if engine_says == "ask" and final == "block":
        return "the engine asked; no human is present, so the ask was refused"
    return "unchanged"


def build(command: str, cwd: str, mode: str = "default") -> Dict[str, Any]:
    """Judge ``command`` exactly as the hook does, and describe what happened."""
    from damage_control import adapter, packs, shellexpand
    from damage_control.policy import BYPASS, DEFAULT, Context, Guard, ToolCall

    ns = adapter.hook_namespace()
    real_check = ns.check_command
    seen: Dict[str, Any] = {}

    def check(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        seen["result"] = real_check(*args, **kwargs)
        return seen["result"]

    ns.check_command = check
    config = ns.load_effective_config()
    guard = Guard(config, ns)
    ctx = Context(mode=BYPASS if mode == "bypass" else DEFAULT, unattended=ns.is_unattended())
    with recording() as trace:
        verdict = guard.decide(ToolCall("shell", "Bash", command=command, cwd=cwd), ctx)
    result = seen["result"]

    separator = shellexpand.resolve_separator_variable(command)
    expanded = separator.text if separator.text != command else None
    subcommands: List[str] = []
    ambiguous = None
    for text in (command, expanded):
        if text is not None:
            found, why = ns.normalize_subcommands(text)
            subcommands += [s for s in found if s not in subcommands]
            ambiguous = ambiguous or why
    judged = [j for n, j in enumerate(trace.judged) if (j["text"], j["scripted"]) not in
              {(p["text"], p["scripted"]) for p in trace.judged[:n]}]
    ask_reason = ns.detect_ask_request(command)
    policy_state = packs.effective_state(ns.policy_file_path())
    rows = packs.overview(ns.policy_file_path(), *ns.overlay_dirs())

    report: Dict[str, Any] = {
        "command": command,
        "cwd": cwd,
        "words": {
            "typed": _words(command),
            "after_separator_expansion": expanded,
            "normalized": subcommands,
            "unreadable": ambiguous or separator.why or None,
        },
        "files": trace.files,
        "limits": {
            "command_chars": len(command), "max_command_chars": ns.MAX_COMMAND_CHARS,
            "max_script_bytes": ns.scriptfile.MAX_SCRIPT_BYTES, "max_script_files": ns.MAX_SCRIPT_FILES,
            "max_script_total_bytes": ns.MAX_SCRIPT_TOTAL_BYTES, "max_script_depth": ns.MAX_SCRIPT_DEPTH,
        },
        "judged": judged,
        "verdict": {
            "decision": verdict.decision,
            "reason": verdict.reason or result.get("reason") or "",
            "rule": verdict.rule_id,
            "pattern": result.get("pattern"),
            **_rule_info(config, verdict.rule_id),
            "engine_decision": result["decision"],
            "policy_effect": _effect(result, verdict.decision),
            "unverifiable": verdict.unverifiable,
            "disabled": verdict.disabled,
        },
        "ask_comment": {
            "reason": ask_reason,
            "applied": bool(result.get("escape_ask")),
            "escalated_from": result.get("escalated_from"),
        } if ask_reason else None,
        "in_effect": {
            "profile": ns.PROFILE.name,
            "mode": ctx.mode,
            "unattended": ctx.unattended,
            "safety_enabled": not ns.kill_switch_off(config),
            "rules_loaded": len(config.get("bashToolPatterns", [])),
            "packs": [r["name"] for r in rows if r["kind"] == "pack" and r["enabled"]],
            "groups": [r["name"] for r in rows if r["kind"] == "group" and r["enabled"]],
            "policy_broken": bool(policy_state.get("broken")),
        },
    }
    return report


def _clip(text: str) -> str:
    one = text.replace("\n", "\\n")
    return one if len(one) <= _TEXT_WIDTH else one[: _TEXT_WIDTH - 1] + "…"


def render(report: Dict[str, Any]) -> str:
    """The report as text for a terminal."""
    v, w, eff, lim = report["verdict"], report["words"], report["in_effect"], report["limits"]
    out: List[str] = [f"command   {_clip(report['command'])}", f"cwd       {report['cwd']}", "", "Words"]
    out.append("  typed:       " + " ".join(map(shlex.quote, w["typed"])))
    if w["after_separator_expansion"] is not None:
        out.append(f"  after $IFS:  {_clip(w['after_separator_expansion'])}")
    for sub in w["normalized"]:
        out.append(f"  normalized:  {_clip(sub)}")
    if w["unreadable"]:
        out.append(f"  not fully readable: {w['unreadable']}")
    out += ["", f"Files read (limits: {lim['max_script_bytes']:,} bytes each, {lim['max_script_files']} files, "
                f"{lim['max_script_total_bytes']:,} bytes total, depth {lim['max_script_depth']})"]
    for f in report["files"]:
        size = f"; {f['bytes']:,} of {lim['max_script_bytes']:,} bytes" if f["status"] == "ok" else ""
        out.append(f"  {f['kind']:7} {f['path']}  [{f['status']}{size}]" + (f" {f['why']}" if f["why"] and f["status"] != "ok" else ""))
    if not report["files"]:
        out.append("  none")
    out += ["", f"Judged ({lim['command_chars']:,} of {lim['max_command_chars']:,} characters allowed)"]
    for j in report["judged"][:_MAX_JUDGED]:
        hits = ", ".join(f"{m['id']} ({m['tier']})" for m in j["matched"]) or "no rule matched"
        out.append(f"  {'script' if j['scripted'] else 'command'}: {_clip(j['text'])}")
        out.append(f"      {j['rules_consulted']} rules consulted; {hits}")
    if len(report["judged"]) > _MAX_JUDGED:
        out.append(f"  … and {len(report['judged']) - _MAX_JUDGED} more")
    out += ["", f"Verdict   {v['decision']}"]
    out.append(f"  decided by: {v['rule'] or 'no rule (nothing matched)'}"
               + (f"  [{v['tier']}" + (f", {v['source']}" if v["source"] else "") + "]" if v["rule"] else ""))
    out.append(f"  why:        {v['reason']}")
    if v["pattern"]:
        out.append(f"  pattern:    {_clip(str(v['pattern']))}")
    if v["policy_effect"] != "unchanged":
        out.append(f"  policy:     {v['policy_effect']}")
    if v["unverifiable"]:
        out.append("  an unverifiable ask: bypass mode does not lower it")
    if report["ask_comment"]:
        a = report["ask_comment"]
        out.append(f"  # ask:      \"{a['reason']}\" — " + (
            f"turned a {a['escalated_from']} into an ask for a human; bypass mode does not lower it" if a["applied"]
            else "no effect: nothing here was blocked, or the block cannot be escalated"))
    out += ["", "In effect",
            f"  profile {eff['profile']}; mode {eff['mode']}; {'unattended' if eff['unattended'] else 'a human is present'}; "
            f"safety {'on' if eff['safety_enabled'] else 'OFF (kill switch)'}; {eff['rules_loaded']} rules loaded",
            f"  packs:  {', '.join(eff['packs']) or 'none'}",
            f"  groups: {', '.join(eff['groups']) or 'none'}"]
    return "\n".join(out)

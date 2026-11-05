"""Locating the recipe text a task runner is about to run: the I/O half of the recipe scan.

``invocation(head, args, bases)`` recognizes a command word that runs recipes (``make``, ``just``,
``npm|pnpm|yarn|bun run``) and ``locate(run)`` answers one question for the engine: what shell text
will those recipes run, or why can that not be known? Neither raises. Everything they decide is a
status string and a list of ``Unit`` texts; the engine owns what a status means for the verdict and
judges each unit like a typed command (see SCRIPT INDIRECTION in engine.py).

Covered: ``make`` (Makefile / GNUmakefile / makefile, ``-C``, ``-f``, ``VAR=x`` overrides, targets and
their prerequisites, one level of ``include``), ``package.json`` scripts with ``pre`` / ``post`` hooks
for ``npm``, ``pnpm``, ``yarn`` and ``bun``, and ``just`` (recipes, dependencies, parameters, ``{{x}}``
interpolation of literals, shebang recipes). ``task`` (Taskfile.yml) is a documented gap: it needs a
YAML parser and a half-parse would be worse than none.

Anything the parser cannot resolve (a variable that is computed, a function call, a conditional that
decides a definition, an ``include`` of a glob) is reported in ``Recipe.why`` and becomes an unverifiable
ask in the engine, never an allow. A recipe that is not there is ``MISSING``: running it fails.

Standard library only.
"""

import json
import os
import posixpath
import re
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from damage_control import explain, scriptfile

OK = scriptfile.OK
MISSING = scriptfile.MISSING
UNREADABLE = scriptfile.UNREADABLE
TOO_LARGE = scriptfile.TOO_LARGE

MAX_GOALS = 64  # targets / recipes followed per invocation
MAX_PARENT_WALK = 32
_EXPAND_DEPTH = 8
_UNRESOLVED = "$UNRESOLVED"
_UNSAFE_OPERAND = re.compile(r"[$`*?\[{\x00]")

MAKE = "make"
JUST = "just"
NODE = "node"


class Run(NamedTuple):
    """One place a command runs recipes."""

    runner: str  # make | just | node
    tool: str  # as typed: make, gmake, just, npm, pnpm, yarn, bun
    calls: Tuple[Tuple[str, Tuple[str, ...]], ...]  # (recipe or script name, its arguments); () means the default
    bases: Tuple[str, ...]  # absolute directories the command may run in (tracked cwd, payload cwd)
    directory: str  # -C / --prefix / -d operand, "" when absent
    file: str  # -f / --justfile operand, "" when absent
    overrides: Tuple[Tuple[str, str], ...]  # NAME=value operands
    why: str = ""  # the command line itself cannot be read (a workspace flag, a computed path)


class Unit(NamedTuple):
    text: str
    lang: str  # shell | python | node | perl | ruby


class Recipe(NamedTuple):
    status: str  # OK | MISSING | UNREADABLE | TOO_LARGE
    label: str = ""
    key: str = ""  # identifies this file + targets, for cycle and repeat detection
    units: Tuple[Unit, ...] = ()
    cwd: str = ""  # where the recipes run
    nfiles: int = 0
    nbytes: int = 0
    why: str = ""  # set when part of the recipe could not be read; the engine asks


# ---- recognizing the command ---------------------------------------------------------------------------

_MAKE_VALUE_SHORT = frozenset("CfIoW")
_MAKE_VALUE_LONG = frozenset({
    "--directory", "--file", "--makefile", "--include-dir", "--old-file", "--assume-old", "--what-if",
    "--new-file", "--assume-new",
})
_NODE_TOOLS = frozenset({"npm", "pnpm", "yarn", "bun"})
_NODE_RUN = frozenset({"run", "run-script", "rum", "urn"})
_NODE_DIRECT = {"npm": frozenset({"test", "t", "tst", "start", "stop"}), "pnpm": frozenset({"test", "t", "start"}),
                "yarn": frozenset({"test", "start"}), "bun": frozenset()}
_NODE_DIR_FLAGS = frozenset({"--prefix", "-C", "--dir", "--cwd"})
_NODE_WORKSPACE = frozenset({"-w", "--workspace", "--filter", "-F", "-r", "--recursive", "-ws", "--workspaces",
                             "--workspaces-root", "-iwr", "--include-workspace-root", "--filter-prod"})
_NODE_VALUE_FLAGS = frozenset({"--userconfig", "--globalconfig", "--registry", "--loglevel", "--cache", "--config",
                               "--reporter", "--cwd", "--prefix", "-C", "--dir"})
_NODE_BUILTINS = frozenset({
    "add", "install", "i", "ci", "remove", "rm", "uninstall", "update", "up", "upgrade", "publish", "init",
    "link", "pack", "exec", "dlx", "create", "config", "cache", "list", "ls", "why", "outdated", "audit",
    "store", "env", "patch", "prune", "rebuild", "import", "fetch", "deploy", "setup", "self-update", "bin",
    "root", "dedupe", "info", "login", "logout", "whoami", "version", "workspace", "workspaces", "node", "set",
    "plugin", "constraints", "search", "unlink", "licenses", "global", "help", "x", "completion", "doctor",
    "dist-tag", "owner", "team", "token", "profile", "unpublish", "view", "show", "explain", "fund", "diff",
    "approve-builds", "run", "run-script", "test", "start", "stop", "t", "restart", "tag", "npm", "yarn",
})
_JUST_VALUE_FLAGS = frozenset({"-f", "--justfile", "-d", "--working-directory", "--shell", "--color", "--chooser",
                               "--unstable", "--dotenv-path", "--dotenv-filename", "--command-color", "--dump-format",
                               "--list-heading", "--list-prefix", "--tempdir", "--timestamp-format", "--set-value"})
_JUST_OTHER = frozenset({"-l", "--list", "--summary", "--dump", "--evaluate", "-e", "--edit", "--choose", "--fmt",
                         "--init", "-s", "--show", "--variables", "--completions", "--man", "--check", "-h", "--help",
                         "-V", "--version", "--groups", "--changelog", "--request"})
RUNNERS = frozenset({"make", "gmake", JUST, *_NODE_TOOLS})
_OVERRIDE_RE = re.compile(r"^([A-Za-z_][\w.\-]*)=(.*)$", re.S)


def _is_value(word: str) -> bool:
    return bool(word) and not word.startswith("-")


def _bad_operand(*operands: str) -> str:
    return "its directory or file is computed" if any(o and _UNSAFE_OPERAND.search(o) for o in operands) else ""


def _make_run(tool: str, args: Sequence[str], bases: Tuple[str, ...]) -> Run:
    goals: List[str] = []
    overrides: List[Tuple[str, str]] = []
    directory = file = why = ""
    i = 0
    while i < len(args):
        w = args[i]
        if w == "--":
            goals.extend(args[i + 1 :])
            break
        if w.startswith("--"):
            name, eq, val = w.partition("=")
            if name == "--eval":
                why = why or "it passes make syntax on the command line (--eval)"
            elif name in _MAKE_VALUE_LONG:
                if not eq and i + 1 < len(args):
                    i += 1
                    val = args[i]
                if name == "--directory":
                    directory = val
                elif name in ("--file", "--makefile"):
                    file = val
        elif w.startswith("-") and len(w) > 1:
            for k, ch in enumerate(w[1:], 1):
                if ch in _MAKE_VALUE_SHORT:
                    val = w[k + 1 :]
                    if not val and i + 1 < len(args):
                        i += 1
                        val = args[i]
                    if ch == "C":
                        directory = val
                    elif ch == "f":
                        file = val
                    break
                if ch == "j" and k == len(w) - 1 and i + 1 < len(args) and args[i + 1].isdigit():
                    i += 1
                    break
        else:
            m = _OVERRIDE_RE.match(w)
            if m:
                overrides.append((m.group(1), m.group(2)))
            else:
                goals.append(w)
        i += 1
    return Run(MAKE, tool, tuple((g, ()) for g in goals), bases, directory, file, tuple(overrides),
               why or _bad_operand(directory, file))


def _just_run(args: Sequence[str], bases: Tuple[str, ...]) -> Optional[Run]:
    directory = file = ""
    overrides: List[Tuple[str, str]] = []
    words: List[str] = []
    i = 0
    while i < len(args):
        w = args[i]
        if words or not w.startswith("-"):
            m = None if words else _OVERRIDE_RE.match(w)
            if m:
                overrides.append((m.group(1), m.group(2)))
            else:
                words.append(w)
            i += 1
            continue
        name, eq, val = w.partition("=") if w.startswith("--") else (w, "", "")
        if name in _JUST_OTHER:
            return None  # lists, prints, formats or edits: no recipe runs
        if name == "--set" and i + 2 < len(args):
            overrides.append((args[i + 1], args[i + 2]))
            i += 2
        elif not w.startswith("--") and w[:2] in ("-f", "-d") and len(w) > 2:
            name, val = w[:2], w[2:]
        elif name in _JUST_VALUE_FLAGS and not eq and i + 1 < len(args):
            i += 1
            val = args[i]
        if name in ("-f", "--justfile"):
            file = val
        elif name in ("-d", "--working-directory"):
            directory = val
        i += 1
    return Run(JUST, JUST, tuple((w, ()) for w in words), bases, directory, file, tuple(overrides),
               _bad_operand(directory, file))


def _node_run(tool: str, args: Sequence[str], bases: Tuple[str, ...]) -> Optional[Run]:
    directory = why = ""
    words: List[str] = []
    i = 0
    while i < len(args):
        w = args[i]
        name, eq, val = w.partition("=") if w.startswith("--") else (w, "", "")
        if w == "--":
            break
        if name in _NODE_WORKSPACE:
            why = why or "it selects a workspace, whose package.json is elsewhere"
            if not eq and name in ("-w", "--workspace", "--filter", "-F", "--filter-prod") and i + 1 < len(args):
                i += 1
        elif w.startswith("-"):
            if name in _NODE_VALUE_FLAGS and not eq and i + 1 < len(args):
                i += 1
                val = args[i]
            if name in _NODE_DIR_FLAGS:
                directory = val
        else:
            words.append(w)
        i += 1
    if not words:
        return None
    sub = words[0]
    if sub in _NODE_RUN:
        if len(words) < 2:
            return None  # ``npm run`` lists scripts
        name = words[1]
    elif sub in _NODE_DIRECT[tool]:
        name = {"t": "test", "tst": "test"}.get(sub, sub)
    elif tool in ("yarn", "pnpm") and sub not in _NODE_BUILTINS:
        name = sub
    else:
        return None
    return Run(NODE, tool, ((name, ()),), bases, directory, "", (), why or _bad_operand(directory))


def invocation(head: str, args: Sequence[str], bases: Sequence[str]) -> Optional[Run]:
    """The recipes ``head args`` runs, or None when it is not a task runner invocation this module reads."""
    tool = os.path.basename(head)
    held = tuple(bases)
    if tool in ("make", "gmake"):
        return _make_run(tool, args, held)
    if tool == JUST:
        return _just_run(args, held)
    if tool in _NODE_TOOLS:
        return _node_run(tool, args, held)
    return None


# ---- reading files ------------------------------------------------------------------------------------------

def _dirs(run: Run) -> List[str]:
    out: List[str] = []
    for b in run.bases:
        d = posixpath.normpath(posixpath.join(b, os.path.expanduser(run.directory))) if run.directory else b
        if d not in out:
            out.append(d)
    return out


def _first_readable(paths: Sequence[str], label: str) -> Tuple[Optional["scriptfile.ScriptFile"], Recipe]:
    """The first path that holds text; else None and the outcome: the last unreadable / too-large file, or MISSING."""
    outcome = Recipe(MISSING, label)
    for p in paths:
        f = scriptfile.read_script(p)
        if f.status == OK:
            return f, outcome
        if f.status in (UNREADABLE, TOO_LARGE):
            outcome = Recipe(f.status, label, why=f.why)
    return None, outcome


def _ancestors(d: str) -> List[str]:
    """``d`` and its parents up to the root, nearest first (npm and just search upward)."""
    out = [d]
    while len(out) < MAX_PARENT_WALK and posixpath.dirname(out[-1]) != out[-1]:
        out.append(posixpath.dirname(out[-1]))
    return out


def _find(dirs: Sequence[str], names_in: "Callable[[str], Sequence[str]]", label: str) -> Tuple[Optional["scriptfile.ScriptFile"], str, Recipe]:
    """``(file, directory it was found for, outcome)`` over each candidate directory in turn."""
    outcome = Recipe(MISSING, label)
    for d in dirs:
        f, found = _first_readable(names_in(d), label)
        if f is not None:
            return f, d, found
        if found.status != MISSING:
            outcome = found
    return None, "", outcome


@explain.traced_locate
def locate(run: Run) -> Recipe:
    label_head = f"{run.tool} " + " ".join(c[0] for c in run.calls)
    label_head = label_head.strip()
    if run.why:
        return Recipe(OK, label_head, key=f"{label_head}|{run.bases}", why=run.why)
    loader = {MAKE: _locate_make, JUST: _locate_just, NODE: _locate_node}[run.runner]
    return loader(run, label_head)


def _expand(text: str, defs: Dict[str, Optional[str]], auto: Dict[str, str], depth: int = 0) -> Tuple[str, bool]:
    """``text`` with the make variables it can resolve replaced; ``(text, resolved)``."""
    ok = [True]
    ref = re.compile(r"\$(?:(\$)|([@<^?*+])|\(([^()$]*)\)|\{([^{}$]*)\}|([A-Za-z_])|(.))", re.S)

    def sub(m: "re.Match[str]") -> str:
        if m.group(1):
            return "$"
        key = m.group(2)
        if key:
            if key in auto:
                return auto[key]
            ok[0] = False
            return _UNRESOLVED
        name = m.group(3) if m.group(3) is not None else m.group(4) if m.group(4) is not None else m.group(5)
        if name is None or not re.fullmatch(r"[A-Za-z_][\w.\-]*", name) or depth >= _EXPAND_DEPTH:
            ok[0] = False
            return _UNRESOLVED
        value = defs[name] if name in defs else auto.get(name)
        if value is None:
            ok[0] = False
            return _UNRESOLVED
        inner, inner_ok = _expand(value, defs, auto, depth + 1)
        ok[0] = ok[0] and inner_ok
        return inner

    return ref.sub(sub, text), ok[0]


# ---- make ------------------------------------------------------------------------------------------------------

_MAKE_ASSIGN_RE = re.compile(r"^(?:(?:export|override|private)\s+)*([A-Za-z_][\w.\-]*)\s*(::=|:=|\?=|\+=|!=|=)\s*(.*)$", re.S)
_MAKE_COND_RE = re.compile(r"^\s*(?:ifeq|ifneq|ifdef|ifndef)\b")
_MAKE_INCLUDE_RE = re.compile(r"^(-include|sinclude|include)\s+(.*)$")
_MAKE_PREFIX_RE = re.compile(r"^[@+\-\s]+")
_MAKE_FILES = ("GNUmakefile", "makefile", "Makefile")


class _Rule:
    __slots__ = ("targets", "prereqs", "lines", "static")

    def __init__(self, targets: str, prereqs: str, static: bool) -> None:
        self.targets, self.prereqs, self.lines, self.static = targets, prereqs, [], static


class _Makefile:
    def __init__(self) -> None:
        self.defs: Dict[str, Optional[str]] = {}
        self.rules: List[_Rule] = []
        self.includes: List[str] = []
        self.unknown: List[str] = []  # reasons a part of the file cannot be read
        self.default_goal = ""

    def parse(self, text: str, is_include: bool) -> None:
        logical: List[Tuple[bool, str]] = []
        for raw in text.replace("\r\n", "\n").split("\n"):
            if logical and logical[-1][1].endswith("\\") and not logical[-1][1].endswith("\\\\"):
                tab, prev = logical[-1]
                logical[-1] = (tab, prev + "\n" + raw if tab else prev[:-1].rstrip() + " " + raw.lstrip())
            else:
                logical.append((raw.startswith("\t"), raw))
        cond = 0
        in_define = False
        current: Optional[_Rule] = None
        for is_recipe, line in logical:
            if in_define:
                in_define = not line.strip().startswith("endef")
                continue
            if is_recipe:
                if current is not None:
                    current.lines.append(line[1:])
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            current = None
            if _MAKE_COND_RE.match(stripped):
                cond += 1
                continue
            if re.match(r"^endif\b", stripped):
                cond = max(0, cond - 1)
                continue
            if re.match(r"^(?:else|else\s+if\w*)\b", stripped):
                continue
            if re.match(r"^(?:override\s+)?define\b", stripped):
                m = re.match(r"^(?:override\s+)?define\s+([A-Za-z_][\w.\-]*)", stripped)
                if m:
                    self.defs[m.group(1)] = None
                in_define = True
                continue
            inc = _MAKE_INCLUDE_RE.match(stripped)
            if inc:
                if is_include:
                    self.unknown.append("an included file includes another file")
                else:
                    self.includes.extend(inc.group(2).split("#")[0].split())
                continue
            if stripped.startswith("$"):
                self.unknown.append("it evaluates a make function at the top level")
                continue
            m = _MAKE_ASSIGN_RE.match(stripped)
            if m:
                self._assign(m.group(1), m.group(2), m.group(3).split(" #")[0].rstrip(), cond > 0)
                continue
            if re.match(r"^(?:vpath|export|unexport|undefine)\b", stripped):
                continue
            current = self._rule(stripped)
            if current is None and ":" in stripped.split("#")[0]:
                self.unknown.append("a rule line it cannot read")

    def _assign(self, name: str, op: str, value: str, conditional: bool) -> None:
        if name == ".DEFAULT_GOAL":
            self.default_goal = value
            return
        if conditional or op == "!=" or (op == "+=" and self.defs.get(name, "") is None):
            self.defs[name] = None
        elif op == "?=":
            self.defs.setdefault(name, value)
        elif op == "+=":
            self.defs[name] = f"{self.defs[name]} {value}" if name in self.defs else value
        else:
            self.defs[name] = value

    def _rule(self, line: str) -> Optional[_Rule]:
        head, colon, rest = line.partition(":")
        if not colon or "=" in head or not head.strip():
            return None
        double = rest.startswith(":") and not rest.startswith(":=")
        rest = rest[1:] if double else rest
        rest, semi, inline = rest.partition(";")
        static = ":" in rest
        rule = _Rule(head.strip(), rest.replace("|", " ").split("#")[0].strip() if not static else "", static)
        if semi and inline.strip():
            rule.lines.append(inline.strip())
        self.rules.append(rule)
        return rule


def _stem_match(pattern: str, name: str) -> Optional[str]:
    if "%" not in pattern:
        return None
    head, _, tail = pattern.partition("%")
    if name.startswith(head) and name.endswith(tail) and len(name) >= len(head) + len(tail):
        return name[len(head) : len(name) - len(tail) if tail else len(name)]
    return None


def _locate_make(run: Run, label: str) -> Recipe:
    dirs = _dirs(run)

    def names_in(d: str) -> List[str]:
        if run.file:
            return [posixpath.normpath(posixpath.join(d, os.path.expanduser(run.file)))]
        return [posixpath.join(d, n) for n in _MAKE_FILES]

    main, work, outcome = _find(dirs, names_in, label)
    if main is None:
        return outcome
    make = _Makefile()
    make.parse(main.text, False)
    files = [main]
    for operand in list(make.includes):
        if _UNSAFE_OPERAND.search(operand):
            make.unknown.append(f"an include of {operand} is computed")
            continue
        found, state = _first_readable([posixpath.normpath(posixpath.join(d, os.path.expanduser(operand))) for d in dirs], label)
        if found is None:
            if state.status != MISSING:
                return state
            continue  # missing: make stops with an error, or -include skips it
        files.append(found)
        make.parse(found.text, True)
    defs: Dict[str, Optional[str]] = {"CC": "cc", "CXX": "c++", "RM": "rm -f", "MAKE": "make", "SHELL": "/bin/sh",
                                      "AR": "ar", "CURDIR": work, "MAKEFLAGS": ""}
    defs.update(make.defs)
    defs.update(dict(run.overrides))
    goals = [g for g, _ in run.calls]
    if not goals:
        goals = [make.default_goal] if make.default_goal else []
        if not goals:
            first = next((t for r in make.rules for t in r.targets.split() if not t.startswith(".") and "%" not in t), "")
            goals = [first] if first else []
    defs["MAKECMDGOALS"] = " ".join(goals)
    why = list(dict.fromkeys(make.unknown))
    commands: List[str] = []
    seen: List[str] = []
    queue = list(goals)
    while queue and len(seen) < MAX_GOALS:
        goal = queue.pop(0)
        if goal in seen:
            continue
        seen.append(goal)
        for rule in make.rules:
            names, heads_ok = _expand(rule.targets, defs, {})
            if not heads_ok:
                if goal in rule.targets or "$" in rule.targets:
                    why.append("a rule's target list is computed")
                continue
            stem = ""
            for t in names.split():
                s = goal if t == goal else _stem_match(t, goal)
                if s is not None:
                    stem = "" if t == goal else s
                    break
            else:
                continue
            if rule.static:
                why.append(f"{goal} is built by a static pattern rule")
                continue
            prereq_text = rule.prereqs.replace("%", stem) if stem else rule.prereqs
            prereqs, p_ok = _expand(prereq_text, defs, {})
            if not p_ok:
                why.append(f"the prerequisites of {goal} are computed")
            plist = prereqs.split()
            queue.extend(p for p in plist if p not in seen)
            auto = {"@": goal, "<": plist[0] if plist else "", "^": " ".join(plist), "?": " ".join(plist),
                    "+": " ".join(plist), "*": stem or goal}
            for line in rule.lines:
                text, ok = _expand(_MAKE_PREFIX_RE.sub("", line, count=1), defs, auto)
                commands.append(text)
                if not ok:
                    why.append(f"a line of {goal} uses a variable or function that cannot be resolved")
    key = f"make|{main.real}|{','.join(goals)}|{sorted(dict(run.overrides).items())}"
    shown = f"{label} ({main.real})"
    return Recipe(OK, shown, key, (Unit("\n".join(commands), "shell"),) if commands else (), work, len(files),
                  sum(len(f.text) for f in files), "; ".join(dict.fromkeys(why)))


# ---- package.json scripts ----------------------------------------------------------------------------------------

def _locate_node(run: Run, label: str) -> Recipe:
    name = run.calls[0][0]
    found, _, outcome = _find(_dirs(run), lambda d: [posixpath.join(p, "package.json") for p in _ancestors(d)], label)
    if found is None:
        return outcome
    try:
        scripts = json.loads(found.text).get("scripts")
    except (ValueError, AttributeError):
        return Recipe(MISSING, label)
    if not isinstance(scripts, dict):
        return Recipe(MISSING, label)
    texts = [scripts[n] for n in (f"pre{name}", name, f"post{name}") if isinstance(scripts.get(n), str)]
    if not texts:
        return Recipe(MISSING, label)
    return Recipe(OK, f"{label} ({found.real})", f"node|{found.real}|{name}", (Unit("\n".join(texts), "shell"),),
                  posixpath.dirname(found.real), 1, len(found.text))


# ---- just --------------------------------------------------------------------------------------------------------------

_JUST_IMPORTS = "it imports or nests other justfiles, which are not read"
_JUST_NAMES = ("justfile", "Justfile", ".justfile")
_JUST_HEADER_RE = re.compile(
    r"^@?([A-Za-z_][\w\-]*)((?:\s+[*+$]?[A-Za-z_][\w\-]*(?:\s*=\s*(?:'[^']*'|\"[^\"]*\"|[^\s:'\"]+))?)*)\s*:(?!=)\s*(.*)$"
)
_JUST_ASSIGN_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][\w\-]*)\s*:=\s*(.*)$")
_JUST_ALIAS_RE = re.compile(r"^alias\s+([A-Za-z_][\w\-]*)\s*:=\s*([A-Za-z_][\w\-]*)\s*$")
_JUST_INTERP_RE = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
_JUST_PARAM_RE = re.compile(r"([*+$]?)([A-Za-z_][\w\-]*)(?:\s*=\s*('[^']*'|\"[^\"]*\"|[^\s:'\"]+))?")


class _JustRecipe(NamedTuple):
    params: Tuple[Tuple[str, str, Optional[str]], ...]  # (kind, name, default literal or None)
    deps: str
    body: Tuple[str, ...]
    scripted: bool  # an attribute that changes the interpreter


def _just_literal(expr: str, vars_: Dict[str, Optional[str]]) -> Optional[str]:
    out = ""
    for part in re.split(r"\s+\+\s+", expr.strip()):
        part = part.strip()
        if len(part) >= 2 and part[0] == part[-1] == "'":
            out += part[1:-1]
        elif len(part) >= 2 and part[0] == part[-1] == '"' and "\\" not in part:
            out += part[1:-1]
        elif re.fullmatch(r"[A-Za-z_][\w\-]*", part) and vars_.get(part) is not None:
            out += vars_[part] or ""
        else:
            return None
    return out


def _parse_just(text: str) -> Tuple[Dict[str, _JustRecipe], Dict[str, Optional[str]], Dict[str, str], List[str], List[str]]:
    recipes: Dict[str, _JustRecipe] = {}
    vars_: Dict[str, Optional[str]] = {}
    aliases: Dict[str, str] = {}
    order: List[str] = []
    unknown: List[str] = []
    lines = text.replace("\r\n", "\n").split("\n")
    attrs: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[0] in " \t":
            continue  # a body line outside any recipe
        if stripped.startswith("["):
            attrs.append(stripped)
            continue
        alias = _JUST_ALIAS_RE.match(stripped)
        if alias:
            aliases[alias.group(1)] = alias.group(2)
            continue
        setting = re.match(r"^set\s+([\w\-]+)\s*(?::=\s*(.*))?$", stripped)
        if setting:
            if setting.group(1) in ("shell", "windows-shell") and setting.group(2):
                first = re.search(r"['\"]([^'\"]+)['\"]", setting.group(2))
                if not first or scriptfile.language_of(os.path.basename(first.group(1))) != "shell":
                    unknown.append("its recipes run under a shell setting that is not sh-like")
            continue
        if re.match(r"^(?:import|mod)\b", stripped):
            unknown.append(_JUST_IMPORTS)
            continue
        assign = _JUST_ASSIGN_RE.match(stripped)
        if assign:
            vars_[assign.group(1)] = _just_literal(assign.group(2), vars_)
            continue
        header = _JUST_HEADER_RE.match(stripped)
        body: List[str] = []
        if header:
            while i < len(lines) and (not lines[i].strip() or lines[i][0] in " \t"):
                body.append(lines[i])
                i += 1
            while body and not body[-1].strip():
                body.pop()
            indent = next((len(b) - len(b.lstrip()) for b in body if b.strip()), 0)
            dedented = tuple(b[indent:] if b.strip() else "" for b in body)
            params = tuple((m.group(1), m.group(2), (m.group(3) or "").strip("'\"") if m.group(3) else None)
                           for m in _JUST_PARAM_RE.finditer(header.group(2)))
            name = header.group(1)
            recipes[name] = _JustRecipe(params, header.group(3).split("#")[0].strip(), dedented,
                                        any(re.match(r"^\[\s*(?:script|extension)\b", a) for a in attrs))
            order.append(name)
        else:
            unknown.append("a line it cannot read")
        attrs = []
    return recipes, vars_, aliases, order, unknown


def _just_body(recipe: _JustRecipe, args: Tuple[str, ...], vars_: Dict[str, Optional[str]]) -> Tuple[str, str, bool]:
    """``(text, language, resolved)`` of one recipe's body with its parameters and variables filled in."""
    bound: Dict[str, Optional[str]] = dict(vars_)
    pending = list(args)
    for kind, name, default in recipe.params:
        if kind in ("*", "+"):
            bound[name], pending = " ".join(pending), []
        elif pending:
            bound[name] = pending.pop(0)
        else:
            bound[name] = default
    ok = [True]

    def sub(m: "re.Match[str]") -> str:
        expr = m.group(1)
        value = bound.get(expr) if re.fullmatch(r"[A-Za-z_][\w\-]*", expr) else _just_literal(expr, bound)
        if value is None:
            ok[0] = False
            return _UNRESOLVED
        return value

    lines: List[str] = []
    cont = bool(recipe.body) and recipe.body[0].startswith("#!")  # a shebang recipe's lines are the script's own
    for raw in recipe.body:
        line = raw.replace("{{{{", "\x00")
        line = _JUST_INTERP_RE.sub(sub, line).replace("\x00", "{{")
        lines.append(line if cont or not line.strip() else re.sub(r"^[@\-]+\s*", "", line))
        cont = line.rstrip().endswith("\\")
    text = "\n".join(lines).strip("\n")
    if text.startswith("#!"):
        lang = scriptfile.shebang_language(text)
        return (text, lang, ok[0]) if lang else ("", "shell", ok[0])
    return text, "shell", ok[0]


def _locate_just(run: Run, label: str) -> Recipe:
    dirs = _dirs(run)

    def names_in(d: str) -> List[str]:
        if run.file:
            return [posixpath.normpath(posixpath.join(d, os.path.expanduser(run.file)))]
        return [posixpath.join(p, n) for p in _ancestors(d) for n in _JUST_NAMES]

    main, _, outcome = _find(dirs, names_in, label)
    if main is None:
        return outcome
    recipes, parsed_vars, aliases, order, unknown = _parse_just(main.text)
    vars_: Dict[str, Optional[str]] = dict(parsed_vars)
    vars_.update(dict(run.overrides))
    work = (dirs[0] if run.directory else posixpath.dirname(main.real))
    calls = list(run.calls)
    words = [w for w, _ in calls]
    calls = []
    i = 0
    while i < len(words):
        name = aliases.get(words[i], words[i])
        recipe = recipes.get(name)
        n = len(recipe.params) if recipe else 0
        if recipe and any(k in "*+" for k, _, _ in recipe.params):
            n = len(words)
        calls.append((name, tuple(words[i + 1 : i + 1 + n])))
        i += 1 + n
    if not calls and order:
        calls = [(order[0], ())]
    imports = _JUST_IMPORTS in unknown  # only a recipe not found here can live in an imported file
    why = [u for u in dict.fromkeys(unknown) if u != _JUST_IMPORTS]
    units: List[Unit] = []
    seen: List[str] = []
    queue = list(calls)
    missing = False
    while queue and len(seen) < MAX_GOALS:
        name, args = queue.pop(0)
        recipe = recipes.get(name)
        if recipe is None:
            missing = True
            continue
        if name in seen:
            continue
        seen.append(name)
        if recipe.scripted:
            why.append(f"{name} runs under a script attribute")
        text, lang, ok = _just_body(recipe, args, vars_)
        if not ok:
            why.append(f"{name} uses a value that cannot be resolved")
        if text.strip():
            units.append(Unit(text, lang))
        for dep in recipe.deps.replace("&&", " ").split():
            if dep.startswith("(") or dep.endswith(")") or dep.startswith('"'):
                why.append(f"{name} passes arguments to a dependency")
            elif aliases.get(dep, dep) not in seen:
                queue.append((aliases.get(dep, dep), ()))
    if missing and imports:
        why.append(_JUST_IMPORTS)
    if missing and not units and not why:
        return Recipe(MISSING, label)
    key = f"just|{main.real}|{calls}|{sorted(dict(run.overrides).items())}"
    return Recipe(OK, f"{label} ({main.real})", key, tuple(units), work, 1, len(main.text), "; ".join(dict.fromkeys(why)))

"""What a git command does, whatever it is spelled like: option abbreviations and aliases resolved to the operation.

git accepts any unambiguous prefix of a long option (``--har`` is ``--hard``), ``--no-`` forms that undo an
option, short-option clusters, and aliases given on the command line (``-c alias.x='reset --hard' x``).
Rules that read the typed spelling see none of that. This module reads the argv the way git's own option
parser does and names the operation, so every spelling of a discard-uncommitted-work operation is judged
by the rule for its canonical form:

======================================  ============================================
canonical command                       the operation
======================================  ============================================
``git reset --hard``                    HEAD, index and working tree reset
``git clean --force``                   untracked files deleted
``git switch --discard-changes``        local modifications thrown away on a switch
``git restore --worktree .``            the working tree overwritten from the index or a tree
``git worktree remove --force``         a worktree dropped with whatever is uncommitted in it
``git <verb> --assembled-at-run-time``  the options come from a feeder's input (``xargs``) and cannot be read
======================================  ============================================

Standard library only; the engine calls :func:`commands` and judges each returned command like a typed one.
"""

import shlex
from typing import Dict, FrozenSet, List, NamedTuple, Optional, Set, Tuple

#: git's global options that take a separate value.
GLOBAL_VALUE_OPTS: FrozenSet[str] = frozenset({
    "-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env",
})

ASSEMBLED = "--assembled-at-run-time"

_ALIAS_DEPTH = 5


class _Opt(NamedTuple):
    name: str  # long name, without the leading dashes
    short: str = ""  # one letter, or ""
    arg: int = 0  # 0 no value, 1 a value (attached or the next word), 2 an optional attached value
    neg: bool = True  # has a ``--no-`` form
    long: bool = True  # has a long spelling at all


_SPECS: Dict[str, Tuple[_Opt, ...]] = {
    "reset": (
        _Opt("quiet", "q"), _Opt("no-refresh"), _Opt("refresh"),
        _Opt("mixed", neg=False), _Opt("soft", neg=False), _Opt("hard", neg=False),
        _Opt("merge", neg=False), _Opt("keep", neg=False), _Opt("recurse-submodules", arg=2),
        _Opt("patch", "p"), _Opt("intent-to-add", "N"), _Opt("pathspec-from-file", arg=1),
        _Opt("pathspec-file-nul"),
    ),
    "clean": (
        _Opt("quiet", "q"), _Opt("dry-run", "n"), _Opt("force", "f"), _Opt("interactive", "i"),
        _Opt("d", "d", neg=False, long=False), _Opt("exclude", "e", 1), _Opt("x", "x", neg=False, long=False),
        _Opt("X", "X", neg=False, long=False),
    ),
    "switch": (
        _Opt("create", "c", 1), _Opt("force-create", "C", 1), _Opt("guess"), _Opt("discard-changes"),
        _Opt("quiet", "q"), _Opt("recurse-submodules", arg=2), _Opt("progress"), _Opt("merge", "m"),
        _Opt("conflict", arg=1), _Opt("detach", "d"), _Opt("track", "t", 2), _Opt("force", "f"),
        _Opt("orphan", arg=1), _Opt("overwrite-ignore"), _Opt("ignore-other-worktrees"),
    ),
    "restore": (
        _Opt("source", "s", 1), _Opt("staged", "S"), _Opt("worktree", "W"), _Opt("ignore-unmerged"),
        _Opt("overlay"), _Opt("quiet", "q"), _Opt("recurse-submodules", arg=2), _Opt("progress"),
        _Opt("merge", "m"), _Opt("conflict", arg=1), _Opt("ours", "2", neg=False),
        _Opt("theirs", "3", neg=False), _Opt("patch", "p"), _Opt("ignore-skip-worktree-bits"),
        _Opt("pathspec-from-file", arg=1), _Opt("pathspec-file-nul"),
    ),
    "worktree remove": (_Opt("force", "f"),),
}

#: verbs whose options (not only their operands) decide what they do: what a feeder's input could change.
_OPTION_DECIDED = frozenset({"reset", "clean", "switch", "restore", "checkout", "worktree remove"})


class _Parsed(NamedTuple):
    active: Dict[str, bool]  # option -> in effect after its last occurrence (a ``--no-`` form undoes it)
    ever: Set[str]  # options given at least once, undone or not
    operands: List[str]
    terminated: bool  # a ``--`` was seen


def _long_match(spec: Tuple[_Opt, ...], name: str) -> Optional[Tuple[_Opt, bool]]:
    """The option (and whether it is the ``--no-`` form) a long-option word names, or None if unknown or ambiguous."""
    forms: List[Tuple[str, _Opt, bool]] = []
    for o in spec:
        if not o.long:
            continue
        forms.append((o.name, o, False))
        if o.neg:
            forms.append(("no-" + o.name, o, True))
    for form, o, negated in forms:
        if form == name:
            return o, negated
    hits = [(o, negated) for form, o, negated in forms if form.startswith(name)]
    return hits[0] if len(hits) == 1 else None


def _parse(spec: Tuple[_Opt, ...], words: List[str]) -> _Parsed:
    """Read ``words`` as git's option parser does: abbreviations, ``--no-`` forms, clusters, ``--``."""
    by_short = {o.short: o for o in spec if o.short}
    active: Dict[str, bool] = {}
    ever: Set[str] = set()
    operands: List[str] = []
    terminated = False
    i = 0
    while i < len(words):
        w = words[i]
        i += 1
        if terminated or w == "-" or not w.startswith("-"):
            operands.append(w)
            continue
        if w == "--":
            terminated = True
            continue
        if w.startswith("--"):
            name, eq, _value = w[2:].partition("=")
            hit = _long_match(spec, name)
            if hit is None:
                continue  # unknown or ambiguous: git stops with an error and does nothing
            opt, negated = hit
            active[opt.name] = not negated
            ever.add(opt.name)
            if opt.arg == 1 and not eq and not negated:
                i += 1
            continue
        k = 1
        while k < len(w):
            opt = by_short.get(w[k])
            k += 1
            if opt is None:
                continue
            active[opt.name] = True
            ever.add(opt.name)
            if opt.arg == 1:
                if k >= len(w):
                    i += 1
                break
            if opt.arg == 2:
                break
    return _Parsed(active, ever, operands, terminated)


def _whole_tree(pathspec: str) -> bool:
    """A pathspec that selects everything under the current directory: ``.``, ``*``, ``:/``, ``:(top)*`` …"""
    rest = pathspec
    if rest.startswith(":("):
        close = rest.find(")")
        if close < 0 or any(m.strip() in ("exclude", "attr") or m.startswith("attr:") for m in rest[2:close].split(",")):
            return False
        rest = rest[close + 1 :]
    elif rest.startswith(":"):
        magic = 1
        while magic < len(rest) and rest[magic] in "/!^":
            magic += 1
        if any(c in "!^" for c in rest[1:magic]):
            return False
        rest = rest[magic:]
    while rest.startswith("./"):
        rest = rest[2:]
    return rest in ("", ".", "*", "**")


def _git_words(args: List[str]) -> Tuple[List[str], List[str], Dict[str, str]]:
    """``(global options kept, words from the verb on, aliases defined with -c)`` of the argv after ``git``."""
    kept: List[str] = []
    aliases: Dict[str, str] = {}
    i = 0
    while i < len(args) and args[i].startswith("-") and args[i] != "--":
        w = args[i]
        if w in GLOBAL_VALUE_OPTS and i + 1 < len(args):
            if w == "-c":
                key, _eq, value = args[i + 1].partition("=")
                if key.lower().startswith("alias."):
                    aliases[key[6:]] = value
            else:
                kept += [w, args[i + 1]]
            i += 2
        else:
            kept.append(w)
            i += 1
    return kept, args[i:], aliases


def _quoted(words: List[str]) -> str:
    return " ".join(shlex.quote(w) for w in words)


def _verb_and_args(words: List[str]) -> Tuple[str, List[str]]:
    """``("worktree remove", rest)`` for a two-word verb, else ``(verb, rest)``."""
    if not words:
        return "", []
    if words[0] == "worktree":
        sub = next((w for w in words[1:] if not w.startswith("-")), "")
        if sub == "remove":
            at = words.index("remove")
            return "worktree remove", words[at + 1 :]
    return words[0], words[1:]


def _operations(verb: str, rest: List[str], assembled: bool) -> List[str]:
    """Canonical commands for the discard operations ``verb rest`` performs (see the module table)."""
    out: List[str] = []
    spec = _SPECS.get(verb)
    parsed = _parse(spec, rest) if spec else None
    if assembled and verb in _OPTION_DECIDED and "--" not in rest:
        out.append(f"git {verb} {ASSEMBLED}")
    if parsed is None:
        return out
    if verb == "reset" and "hard" in parsed.ever:
        # any --hard counts, even one a later mode option overrides: the rule has always read it that way
        out.append("git reset --hard")
    elif verb == "clean":
        if parsed.active.get("force") and not parsed.active.get("dry-run"):
            out.append("git clean --force")
    elif verb == "switch":
        if parsed.active.get("force") or parsed.active.get("discard-changes"):
            out.append("git switch --discard-changes")
    elif verb == "restore":
        worktree = parsed.active.get("worktree") or not parsed.active.get("staged")
        if worktree and any(_whole_tree(p) for p in parsed.operands):
            out.append("git restore --worktree .")
    elif verb == "worktree remove":
        if parsed.active.get("force"):
            out.append("git worktree remove --force")
    return out


def commands(args: List[str], assembled: bool = False) -> List[str]:
    """Commands the argv after ``git`` performs, in canonical spelling, for the engine to judge like typed ones.

    Two kinds: an alias given with ``-c`` is replaced by what it names (``git reset --hard``, ``git push
    --force`` …, whatever the alias holds), and each discard operation is named by its canonical command.
    ``assembled`` says the argv is extended at run time by a feeder (``xargs``), which can add any option.
    """
    kept, words, aliases = _git_words(args)
    out: List[str] = []
    for _ in range(_ALIAS_DEPTH):
        verb, rest = _verb_and_args(words)
        out += _operations(verb, rest, assembled)
        target = aliases.get(words[0]) if words else None
        if target is None or target.startswith("!"):
            break
        try:
            expansion = shlex.split(target)
        except ValueError:
            break
        words = expansion + words[1:]
        out.append(_quoted(["git", *kept, *words]))
    return list(dict.fromkeys(out))

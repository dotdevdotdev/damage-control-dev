"""Differential respelling over the conformance corpus.

Every corpus row that is judged ``block`` or ``ask`` is respelled by a set of transformations that must
not change what the command does or how the rules judge it: quote splits, backslashes, the field
separator variable for a space, ``~`` / ``$HOME`` / ``${HOME}`` / absolute / a variable for the home
directory, repeated slashes, ``.`` and ``..`` segments, brace groups and (where the platform folds case)
letter case. Each respelling is replayed through the real hook and must get the row's verdict.

Generation is deterministic for a seed, and bounded: ``generate`` returns at most ``n`` respellings,
spread over the rows and families rather than taken from the first rows alone.
"""

import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, NamedTuple, Optional

from damage_control import corpus

HOME_FORMS = ("~", "$HOME", "${HOME}", "@HOME@")
_HOME_PREFIX = re.compile(r"(?<![\w$@~])(~|\$HOME|\$\{HOME\}|@HOME@)(?=/)")
_PATH_END = r"[^\s;|<>(),}'\"]*"
_HOME_PATH = re.compile(r"(?<![\w$@~])(?:~|\$HOME|\$\{HOME\}|@HOME@)" + _PATH_END)
_SHELL_SPECIAL = set("'\"\\$`;|(){}<")
_PLAIN_WORD = re.compile(r"^[A-Za-z0-9_./~-]+$")
DEFAULT_N = 200
DEFAULT_SEED = 1


class Respelling(NamedTuple):
    row_id: str
    family: str
    command: str
    cwd: str
    verdict: str
    plain: str
    tool: str = "Bash"
    packs: tuple = ()
    environment: tuple = ()


def _plain_words(command: str) -> List[int]:
    """Indexes of words that can be edited in place: only when the command has no quoting or expansion."""
    if any(c in _SHELL_SPECIAL for c in command):
        return []
    words = command.split(" ")
    return [i for i, w in enumerate(words) if _PLAIN_WORD.match(w) and not w.startswith("-")]


def _edit_word(command: str, insert: str) -> List[str]:
    words = command.split(" ")
    out = []
    for i in _plain_words(command):
        w = words[i]
        low = 2 if w.startswith("~") else 1
        for pos in range(low, len(w)):
            if w[pos - 1] == "/" and w[pos] == "/":
                continue
            out.append(" ".join(words[:i] + [w[:pos] + insert + w[pos:]] + words[i + 1:]))
    return out


def quote_split(command: str, cwd: str, rng: random.Random) -> List[str]:
    return _edit_word(command, '""')


def backslash(command: str, cwd: str, rng: random.Random) -> List[str]:
    return _edit_word(command, "\\")


def separator_variable(command: str, cwd: str, rng: random.Random) -> List[str]:
    if any(c in _SHELL_SPECIAL for c in command) or "IFS" in command:
        return []
    out = []
    for m in re.finditer(" ", command):
        nxt = command[m.end():m.end() + 1]
        if nxt and (nxt.isalnum() or nxt == "_"):
            variants = ["${IFS}"]
        else:
            variants = ["${IFS}", "$IFS"]
        out.extend(command[:m.start()] + v + command[m.end():] for v in variants)
    return out


def home_form(command: str, cwd: str, rng: random.Random) -> List[str]:
    out = []
    for m in _HOME_PREFIX.finditer(command):
        out.extend(command[:m.start()] + f + command[m.end():] for f in HOME_FORMS if f != m.group(1))
    return out


def home_variable(command: str, cwd: str, rng: random.Random) -> List[str]:
    """The home prefix held in a variable assigned first, plain or inside braces."""
    out = []
    for m in _HOME_PREFIX.finditer(command):
        for ref in ("$hh", "${hh}"):
            body = command[:m.start()] + ref + command[m.end():]
            out.append(f"hh={m.group(1)}; {body}")
    return out


def _slash_edits(command: str, insert: str) -> List[str]:
    out = []
    for m in _HOME_PATH.finditer(command):
        path = m.group(0)
        for s in re.finditer("/", path):
            if s.end() >= len(path):
                continue
            out.append(command[:m.start()] + path[:s.start()] + insert + path[s.start():] + command[m.end():])
    return out


def repeated_slash(command: str, cwd: str, rng: random.Random) -> List[str]:
    return _slash_edits(command, "/")


def dot_segment(command: str, cwd: str, rng: random.Random) -> List[str]:
    return _slash_edits(command, "/.") + _slash_edits(command, "/xx/..")


def brace_group(command: str, cwd: str, rng: random.Random) -> List[str]:
    if "{" in command:
        return []
    return [command[:m.start()] + "{" + m.group(0) + ",/tmp/zz}" + command[m.end():]
            for m in _HOME_PATH.finditer(command) if "," not in m.group(0) and command[m.start() - 1:m.start()] != "="]


def letter_case(command: str, cwd: str, rng: random.Random) -> List[str]:
    if sys.platform not in ("darwin", "win32"):
        return []
    out = []
    for m in _HOME_PATH.finditer(command):
        path = m.group(0)
        start = path.find("/")
        if start < 0 or path.startswith("@HOME@"):
            continue
        out.append(command[:m.start()] + path[:start] + path[start:].upper() + command[m.end():])
    return out


FAMILIES: Dict[str, Callable[[str, str, random.Random], List[str]]] = {
    "quote-split": quote_split,
    "backslash": backslash,
    "separator-variable": separator_variable,
    "home-form": home_form,
    "home-variable": home_variable,
    "repeated-slash": repeated_slash,
    "dot-segment": dot_segment,
    "brace-group": brace_group,
    "letter-case": letter_case,
}


def generate(rows: List[Dict[str, Any]], n: int = DEFAULT_N, seed: int = DEFAULT_SEED,
             exclude: Optional[Callable[[Respelling], bool]] = None) -> List[Respelling]:
    """At most ``n`` respellings of the ``block`` / ``ask`` rows, the same list for the same arguments.

    ``exclude`` drops respellings before they are counted (a miss class that already has an open issue).
    Candidates are pooled per (row, family); the pool is shuffled by ``seed`` and drawn round-robin, so
    every family and row that has candidates appears before any one of them appears twice.
    """
    rng = random.Random(seed)
    pools = []
    for row in rows:
        if row["verdict"] == "allow":
            continue
        for family, make in FAMILIES.items():
            variants = sorted({v for v in make(row["command"], row["cwd"], rng) if v != row["command"]})
            rng.shuffle(variants)
            found = [Respelling(row["id"], family, v, row["cwd"], row["verdict"], row["command"], row.get("tool", "Bash"),
                                tuple(row.get("packs", ())), tuple(sorted(row.get("env", {}).items()))) for v in variants]
            found = [r for r in found if not (exclude and exclude(r))]
            if found:
                pools.append(found)
    rng.shuffle(pools)
    out: List[Respelling] = []
    depth = 0
    while len(out) < n and any(len(p) > depth for p in pools):
        for found in pools:
            if depth < len(found) and len(out) < n:
                out.append(found[depth])
        depth += 1
    return out


def run(data: Dict[str, Any], n: int = DEFAULT_N, seed: int = DEFAULT_SEED,
        exclude: Optional[Callable[[Respelling], bool]] = None, workers: int = 8) -> Dict[str, Any]:
    """Replay the respellings through the real hook; ``mismatches`` lists every one whose verdict differs."""
    return replay(data, generate(data["rows"], n, seed, exclude), seed, workers)


def replay(data: Dict[str, Any], respellings: List[Respelling], seed: int = DEFAULT_SEED,
           workers: int = 8) -> Dict[str, Any]:
    with corpus.scratch(data.get("files", {})) as (home, sub):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            got = list(pool.map(lambda r: corpus._hook(*corpus.row_call(
                {"command": r.command, "cwd": r.cwd, "tool": r.tool, "packs": list(r.packs), "env": dict(r.environment)},
                home, sub)), respellings))
    mismatches = [{**r._asdict(), "got": g} for r, g in zip(respellings, got) if g != r.verdict]
    return {"count": len(respellings), "seed": seed, "mismatches": mismatches}


def report(result: Dict[str, Any]) -> str:
    lines = [f"{result['count'] - len(result['mismatches'])}/{result['count']} respellings keep their verdict (seed {result['seed']})"]
    for m in result["mismatches"]:
        lines.append(f"DIFF {m['row_id']} [{m['family']}] want {m['verdict']}, got {m['got']}: {m['command']}")
    return "\n".join(lines)

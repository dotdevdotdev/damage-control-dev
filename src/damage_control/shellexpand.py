"""Shell expansions that only rewrite spelling: resolve them so the rules judge what the shell runs.

``cat${IFS}file`` and ``cat file`` run the same program with the same operand. The shell
replaces ``$IFS`` with its separator list (space, tab, newline by default) before it splits
the line into words, so a rule that reads the text has to read the expanded text.
``resolve_separator_variable`` does that rewrite for the default separator variable and says
plainly when it cannot: a command that reassigns or unsets the variable, or transforms it,
gets a reason instead of a guess.

A reference inside quotes is resolved too. A quoted string is very often a program for another
shell (``bash -c '…'``, ``ssh host '…'``), and that shell expands it. The rewritten command goes
through the same masking as any other, so text that is only quoted data is judged exactly as
it would be with spaces typed in.

Standard library only.
"""

import re
from typing import NamedTuple, Tuple

DEFAULT_SEPARATORS = " \t\n"  # what an unmodified IFS holds

# $IFS (not $IFSX), ${IFS}, ${IFS:off} / ${IFS:off:len}, or ${IFS<anything else>} (unresolvable)
_IFS_REF_RE = re.compile(r"\$(?:IFS(?![A-Za-z0-9_])|\{IFS([^}]*)\})")
_SUBSTRING_RE = re.compile(r":(\d+)(?::(\d+))?")
# $9 / ${9} right after a separator: the usual way to keep it from running into the next word
_EMPTY_POSITIONAL_RE = re.compile(r"\$(?:[1-9]|\{[1-9]\})")
_REASSIGNED_RE = re.compile(
    r"(?<![\w$])IFS\+?="
    r"|\b(?:local|declare|typeset|export|readonly|unset)\s+(?:-\w+\s+)*IFS\b"
)
# the command gives $1…$9 a value of its own, so a trailing $9 is not known to be empty
_POSITIONALS_SET_RE = re.compile(r"\bset\s+--|\(\s*\)\s*[{(]|\bfunction\s+\w")


class Separator(NamedTuple):
    text: str  # the command with each separator reference replaced
    why: str = ""  # non-empty: the command defines or transforms IFS, so the text is not what runs


def resolve_separator_variable(command: str) -> Separator:
    """``command`` with every ``$IFS`` the shell would expand replaced by the separator it yields.

    A reference behind a backslash stays as typed. Each separator character becomes one space,
    because a rule asks where words end, not which whitespace ended them. The text is returned
    unchanged when there is nothing to resolve.
    """
    if "IFS" not in command:
        return Separator(command)
    drop_positionals = not _POSITIONALS_SET_RE.search(command)
    out = []
    why = ""
    i, n = 0, len(command)
    while i < n:
        ch = command[i]
        if ch == "\\":
            out.append(command[i : i + 2])
            i += 2
            continue
        m = _IFS_REF_RE.match(command, i) if ch == "$" else None
        if not m:
            out.append(ch)
            i += 1
            continue
        value, reason = _separator_value(m.group(1))
        why = why or reason
        out.append(value)
        i = m.end()
        while drop_positionals:
            p = _EMPTY_POSITIONAL_RE.match(command, i)
            if not p:
                break
            i = p.end()
    text = "".join(out)
    if text != command and not why and _REASSIGNED_RE.search(command):
        why = "the command changes IFS, so $IFS is not the default separator"
    return Separator(text, why)


def _separator_value(modifier: object) -> Tuple[str, str]:
    """(replacement text, why-not) for the part of ``${IFS…}`` after the name."""
    if not modifier:
        return " ", ""
    m = _SUBSTRING_RE.fullmatch(str(modifier))
    if not m:
        return " ", f"${{IFS{modifier}}} transforms the separator list"
    start = int(m.group(1))
    end = start + int(m.group(2)) if m.group(2) is not None else None
    return " " * len(DEFAULT_SEPARATORS[start:end]), ""

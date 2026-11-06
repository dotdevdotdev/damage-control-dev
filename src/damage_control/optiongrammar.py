"""Which operand is the program: the option grammar of interpreters and of the launchers in front of them.

Script indirection reads the file a command runs, so it has to know where an interpreter's options end.
Two questions are answered here, each from the real grammar of the tool and not from which letters
appear in a word:

* ``script_operand(lang, args)``: the file ``python|node|perl|ruby`` is run on. A short-option cluster is
  read left to right: a letter that takes a value ends the cluster (``-Wignore::DeprecationWarning`` is
  a warning filter, however many letters it holds), and a letter that carries the program inline
  (``-c``, ``-e``) means there is no file.
* ``LAUNCHER_VALUE_OPTS``: the options of ``uv run`` / ``uvx`` / ``npx`` / ``pipx run`` / ``poetry run``
  that take a separate value, so the word after ``--with`` is not mistaken for the command.

Standard library only.
"""

from typing import Dict, FrozenSet, NamedTuple, Optional, List

from damage_control import nonexec


class _Grammar(NamedTuple):
    inline: FrozenSet[str]  # short letters whose argument is the program text
    value: FrozenSet[str]  # short letters taking a value: the rest of the word, else the next word
    rest: FrozenSet[str]  # short letters that swallow the rest of the word (never the next one)
    digits: FrozenSet[str]  # short letters that swallow only the digits after them (``-l``, ``-0``)
    long_inline: FrozenSet[str]  # long options whose argument is the program text
    long_value: FrozenSet[str]  # long options taking a separate value


_NONE: FrozenSet[str] = frozenset()

_GRAMMARS: Dict[str, _Grammar] = {
    "python": _Grammar(
        inline=frozenset("cm"), value=frozenset("WXQ"), rest=_NONE, digits=_NONE,
        long_inline=_NONE, long_value=frozenset({"--check-hash-based-pycs"}),
    ),
    "node": _Grammar(
        inline=frozenset("ep"), value=frozenset("rC"), rest=_NONE, digits=_NONE,
        long_inline=frozenset({"--eval", "--print"}),
        long_value=frozenset({"--require", "--import", "--loader", "--experimental-loader", "--conditions"}),
    ),
    "perl": _Grammar(
        inline=frozenset("eE"), value=frozenset("IMm"), rest=frozenset("iFCdDx"), digits=frozenset("l0"),
        long_inline=_NONE, long_value=_NONE,
    ),
    "ruby": _Grammar(
        inline=frozenset("e"), value=frozenset("rICE"), rest=frozenset("KFixWT"), digits=frozenset("0"),
        long_inline=_NONE, long_value=_NONE,
    ),
}


def script_operand(lang: str, args: List[str]) -> Optional[str]:
    """The script file ``python|node|perl|ruby`` is run on, or None when the program is inline / a module / stdin."""
    g = _GRAMMARS[lang]
    i = 0
    while i < len(args):
        w = args[i]
        if w == "--":
            return args[i + 1] if i + 1 < len(args) else None
        if w == "-":
            return None
        if not w.startswith("-"):
            return w
        if nonexec.runs_no_program(lang, w) or w in g.long_inline:
            return None
        if w.startswith("--"):
            i += 2 if w in g.long_value else 1
            continue
        step = _cluster(g, w)
        if step is None:
            return None
        i += step
    return None


def _cluster(g: _Grammar, word: str) -> Optional[int]:
    """How many words the short-option cluster ``word`` takes, or None when a letter in it carries the program."""
    k = 1
    while k < len(word):
        ch = word[k]
        if ch in g.inline:
            return None
        if ch in g.value:
            return 1 if k + 1 < len(word) else 2
        if ch in g.rest:
            return 1
        k += 1
        if ch in g.digits:
            while k < len(word) and word[k].isdigit():
                k += 1
    return 1


_UV_VALUE = frozenset({
    "--with", "--with-editable", "--with-requirements", "--python", "-p", "--project", "--directory", "--env-file",
    "--extra", "--group", "--only-group", "--no-group", "--package", "--index", "--default-index", "--index-url",
    "-i", "--extra-index-url", "--find-links", "-f", "--index-strategy", "--keyring-provider", "--config-file",
    "--cache-dir", "--refresh-package", "--reinstall-package", "--upgrade-package", "-P", "--constraints", "-c",
    "--overrides", "--exclude-newer", "--resolution", "--prerelease", "--link-mode", "--color", "--script",
})

# launcher -> its options that take a separate value (an attached ``--with=x`` is one word and needs no entry)
LAUNCHER_VALUE_OPTS: Dict[str, FrozenSet[str]] = {
    "uv": _UV_VALUE,
    "uvx": _UV_VALUE | {"--from"},
    "npx": frozenset({"-p", "--package", "--registry", "--userconfig", "--cache", "-w", "--workspace", "--prefix"}),
    "pipx": frozenset({"--spec", "--python", "--pip-args", "--index-url", "--path"}),
    "poetry": frozenset({"-C", "--directory", "-P", "--project"}),
}

# ``uv run`` / ``pipx run`` / ``npm exec``: the subcommand keeps the launcher's options
LAUNCHER_SUBCOMMANDS = frozenset({"run", "exec", "dlx"})


# ``claude``: long options by name, with whether they take a value. Claude Code's parser needs the whole
# word for a long option; an abbreviation is read as the one option it is a prefix of, so a spelling no
# parser would accept is judged like the real one and never allowed because it looks unfamiliar.
_CLAUDE_FLAGS = frozenset({
    "--bare", "--safe-mode", "--print", "--verbose", "--continue", "--fork-session", "--chrome", "--no-chrome",
    "--dangerously-skip-permissions", "--allow-dangerously-skip-permissions", "--strict-mcp-config", "--ide",
    "--no-session-persistence", "--include-partial-messages", "--replay-user-messages", "--disable-slash-commands",
    "--mcp-debug", "--version", "--help", "--resume", "--debug", "--worktree", "--tmux",
})
_CLAUDE_VALUE_OPTS = frozenset({
    "--settings", "--setting-sources", "--plugin-dir", "--add-dir", "--mcp-config", "--allowed-tools",
    "--allowedtools", "--disallowed-tools", "--disallowedtools", "--tools", "--system-prompt", "--append-system-prompt",
    "--system-prompt-file", "--append-system-prompt-file", "--permission-mode", "--permission-prompt-tool",
    "--model", "--fallback-model", "--output-format", "--input-format", "--max-turns", "--max-budget-usd",
    "--session-id", "--agents", "--agent", "--betas", "--debug-file", "--effort", "--name", "--file",
    "--json-schema", "--from-pr",
})
_CLAUDE_LONG = _CLAUDE_FLAGS | _CLAUDE_VALUE_OPTS
_CLAUDE_SHORT_VALUE = frozenset("n")


def _claude_long(name: str) -> str:
    """The long option an (abbreviated) ``--name`` stands for: itself, else its one unambiguous completion."""
    key = name.lower()
    if key in _CLAUDE_LONG:
        return key
    hits = [o for o in _CLAUDE_LONG if o.startswith(key)]
    return hits[0] if len(hits) == 1 else key


def claude_options(args: List[str]) -> List[tuple]:
    """``(long option, value or None)`` for each option on a ``claude`` command line, in order.

    ``--opt=value`` and ``--opt value`` give the same pair; a value option takes the next word whatever it
    looks like; ``--`` ends the options; the words that are not options (the prompt, a subcommand) are skipped.
    """
    out: List[tuple] = []
    i = 0
    while i < len(args):
        w = args[i]
        i += 1
        if w == "--":
            break
        if w.startswith("--") and len(w) > 2:
            name, eq, value = w.partition("=")
            long = _claude_long(name)
            if long in _CLAUDE_VALUE_OPTS and not eq:
                value = args[i] if i < len(args) else None
                i += 1
            out.append((long, value if (eq or long in _CLAUDE_VALUE_OPTS) else None))
        elif w.startswith("-") and len(w) > 1 and w[1] in _CLAUDE_SHORT_VALUE and len(w) == 2:
            i += 1
    return out

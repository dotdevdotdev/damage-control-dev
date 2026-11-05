"""A verb that expands to the empty string.

An empty expansion vanishes and the shell runs the next word, so ``x=; $x ls`` is ``ls`` and
``x=; $x rm -rf /`` is ``rm -rf /``: the remainder is judged as typed. A variable the command never
sets still asks (what it holds is unknown). Each row drives the real hook entrypoint as a subprocess.
"""

from hookrun import run_hook

# (command, verdict)
EMPTY_VERB = [
    # assigned the empty string, three spellings, then used as the verb
    ("x=; $x ls", "allow"),
    ("x=\"\"; $x ls", "allow"),
    ("x=''; $x ls", "allow"),
    ("x=; ${x} ls", "allow"),
    ("x=\"\"; \"$x\" ls", "allow"),
    ("x=${y:-}; $x ls", "allow"),
    ("export x=; $x ls", "allow"),
    ("x=; echo hi; $x ls", "allow"),
    ("x=; for f in a; do $x ls; done", "allow"),
    ("x=; bash -c '$x ls'", "allow"),
    ("x=; $x && ls", "allow"),
    ("x=; $x", "allow"),
    # a destructive remainder still blocks
    ("x=; $x rm -rf /", "block"),
    ("x=\"\"; $x rm -rf /", "block"),
    ("x=''; ${x} rm -rf /", "block"),
    ("x=\"\"; \"$x\" rm -rf /", "block"),
    ("x=; echo hi; $x rm -rf /", "block"),
    ("x=; bash -c '$x rm -rf /'", "block"),
    # literal quoted-empty verbs
    ("\"\" ls", "allow"),
    ("'' ls", "allow"),
    ("\"\" rm -rf /", "block"),
    ("'' rm -rf /", "block"),
    # never set: the remainder is judged as typed, and what the variable might hold asks
    ("$u rm -rf /", "block"),
    ("$u ls", "ask"),
    # a variable that is set to a program keeps resolving to it
    ("x=ls; $x -la", "allow"),
    ("x=rm; $x -rf /", "block"),
]


def test_a_verb_that_expands_to_nothing_leaves_its_remainder_judged_as_typed(tmp_path):
    bad = [
        (cmd, want, got)
        for cmd, want in EMPTY_VERB
        for got in [run_hook("bash", "Bash", {"command": cmd}, "/tmp", tmp_path)]
        if got != want
    ]
    assert not bad, bad

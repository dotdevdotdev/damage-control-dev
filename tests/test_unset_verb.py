"""A verb that is a variable the command does not set.

An empty expansion vanishes and the shell runs the next word, so ``$u rm -rf /`` is ``rm -rf /``.
Whether the variable is empty or holds a program name from the environment is not knowable here:
the command is judged as the empty reading, and what remains unknown asks. A variable the command
sets keeps resolving to what it holds. Each row drives the real hook entrypoint as a subprocess.
"""

from hookrun import run_hook

HOME = "/golden/home"

# (cwd, command, verdict)
UNSET_VERB = [
    # the empty reading is the next word, judged as typed
    ("/tmp", "$u rm -rf /", "block"),
    ("/tmp", "${u} rm -rf /", "block"),
    ("/tmp", "\"$u\" rm -rf /", "block"),
    ("/tmp", "echo hi; $u rm -rf /", "block"),
    ("/tmp", "for f in a; do $u rm -rf /; done", "block"),
    ("/tmp", "bash -c '$u rm -rf /'", "block"),
    (HOME, "$u cat ~/.ssh/id_rsa", "block"),
    # what the variable holds is not knowable: an unverifiable ask
    ("/tmp", "$u ls", "ask"),
    ("/tmp", "$CC -o x main.c", "ask"),
    ("/tmp", "$u", "ask"),
    ("/tmp", "$u && ls", "ask"),
    ("/tmp", "bash -c '$u ls'", "ask"),
    ("/tmp", "x=ls; $x -la; $u pwd", "ask"),
]

# Variables the command sets, and expansions that are not in the verb slot, are unchanged.
SET_OR_ELSEWHERE = [
    ("/tmp", "x=ls; $x -la", "allow"),
    ("/tmp", "x=rm; $x -rf /", "block"),
    ("/tmp", "for f in ls pwd; do $f; done", "allow"),
    ("/tmp", "f=echo; $f hi", "allow"),
    ("/tmp", "${CMD:-ls} -la", "allow"),
    ("/tmp", "$HOME/bin/tool", "allow"),
    ("/tmp", "ls $u", "allow"),
    ("/tmp", "echo \"$u\"", "allow"),
    ("/tmp", "ls; echo $HOME", "allow"),
]


def _verdicts(table, tmp_path):
    return [
        (cwd, cmd, want, got)
        for cwd, cmd, want in table
        for got in [run_hook("bash", "Bash", {"command": cmd}, cwd, tmp_path)]
        if got != want
    ]


def test_a_verb_taken_from_an_unset_variable_is_judged_empty_and_otherwise_asks(tmp_path):
    bad = _verdicts(UNSET_VERB, tmp_path)
    assert not bad, bad


def test_variables_the_command_sets_and_expansions_outside_the_verb_slot_are_unchanged(tmp_path):
    bad = _verdicts(SET_OR_ELSEWHERE, tmp_path)
    assert not bad, bad

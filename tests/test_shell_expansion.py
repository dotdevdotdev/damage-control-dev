"""A command is judged as the words the shell will run, not as it is spelled.

The separator variable is the case here: ``cat${IFS}file`` runs ``cat file``. Each row drives
the real hook entrypoint as a subprocess (exit 2 = block, exit 0 with an ``ask`` envelope = ask,
exit 0 and silence = allow) and gives the verdict the same command typed with spaces gets.
"""

from hookrun import run_hook

HOME = "/golden/home"
SECRET = "~/.ssh/id_rsa"

# (cwd, command, verdict). Every spelled row has a spaced twin in the controls below.
RESOLVED = [
    # the verb position: the separator ends the verb and starts an operand
    (HOME, f"cat${{IFS}}{SECRET}", "block"),
    ("/tmp", f"cat${{IFS}}{SECRET}", "block"),
    (HOME, f"cat$IFS{SECRET}", "block"),
    ("/tmp", f"cat$IFS{SECRET}", "block"),
    (HOME, f"cat${{IFS:0:1}}{SECRET}", "block"),
    (HOME, f"cat$IFS$9{SECRET}", "block"),
    (HOME, f"cat${{IFS}}-n${{IFS}}{SECRET}", "block"),
    # the operand position: separators between arguments and around a redirect
    (HOME, "echo${IFS}x${IFS}>${IFS}~/.zshenv", "block"),
    ("/tmp", "echo${IFS}x>${IFS}~/.zshenv", "block"),
    (HOME, "echo$IFS\"x\">$IFS~/.zshenv", "block"),
    (HOME, "cp${IFS}/golden/stage/a${IFS}$HOME/.gitconfig", "block"),
    ("/tmp", "rm${IFS}-rf${IFS}/", "block"),
    ("/tmp", "rm${IFS}-rf${IFS}$HOME", "block"),
    # concatenated with a quoted word
    (HOME, f"cat${{IFS}}\"$HOME/.ssh/id_rsa\"", "block"),
    ("/tmp", "\"rm\"${IFS}\"-rf\"${IFS}/", "block"),
    (HOME, f"cat \"${{IFS}}\"{SECRET}", "block"),
    # a program handed to another shell is expanded by that shell
    (HOME, f"bash -c 'cat${{IFS}}{SECRET}'", "block"),
    (HOME, f"sh -c \"cat$IFS{SECRET}\"", "block"),
    (HOME, f"ssh host 'cat${{IFS}}{SECRET}'", "block"),
    # unchanged controls: the same commands typed with spaces, and IFS uses that name nothing guarded
    (HOME, f"cat {SECRET}", "block"),
    (HOME, "echo x > ~/.zshenv", "block"),
    ("/tmp", "rm -rf /", "block"),
    (HOME, f"bash -c 'cat {SECRET}'", "block"),
    ("/tmp", "cat${IFS}/etc/hostname", "allow"),
    ("/tmp", "ls$IFS-la", "allow"),
    ("/tmp", "echo hi${IFS}there", "allow"),
    ("/tmp", "echo \"a${IFS}b\"", "allow"),
    ("/tmp", "printf %s \"$IFS\" | od -c", "allow"),
    ("/tmp", "echo $IFSX /etc/hostname", "allow"),
    ("/tmp", "while IFS= read -r l; do echo \"$l\"; done < /etc/hostname", "allow"),
]

# An expansion that cannot be resolved statically stays an unverifiable ask.
UNRESOLVED = [
    ("/tmp", "IFS=,; cat${IFS}/etc/hostname", "ask"),
    ("/tmp", "unset IFS; cat${IFS}/etc/hostname", "ask"),
    ("/tmp", "local IFS=:; echo $IFS", "ask"),
    ("/tmp", "echo ${IFS#?}", "ask"),
    ("/tmp", "cat${IFS%?}/etc/hostname", "ask"),
]


def _verdicts(table, tmp_path):
    return [
        (cwd, cmd, want, got)
        for cwd, cmd, want in table
        for got in [run_hook("bash", "Bash", {"command": cmd}, cwd, tmp_path)]
        if got != want
    ]


def test_the_real_hook_judges_every_separator_spelling_as_the_spaced_command(tmp_path):
    bad = _verdicts(RESOLVED, tmp_path)
    assert not bad, bad


def test_a_separator_the_command_redefines_or_transforms_is_an_unverifiable_ask(tmp_path):
    bad = _verdicts(UNRESOLVED, tmp_path)
    assert not bad, bad

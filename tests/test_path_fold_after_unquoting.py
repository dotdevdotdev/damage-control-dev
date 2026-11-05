"""A quote or backslash inside a guarded path does not hide its dot segments or repeated slashes,
and a braced variable reference does not hide them either.

The shell removes the quote or backslash, expands the variable and the brace group, and only then opens the
path, so ``~/./.""zshenv``, ``${hh}//.zshenv`` and ``{${hh}/.zshenv,/tmp/zz}`` name the file the plain
spelling names. Each row drives the real hook entrypoint as a subprocess; controls name an unprotected file
through the same spellings and stay allowed.
"""

from hookrun import run_hook

# (command, verdict); @HOME@ is the hook's home directory
CASES = [
    # a quote or backslash next to a dot segment or repeated slash, read-only class
    ('echo x > ~/./.""zshenv', "block"),
    ("echo x > ~/./\\.zshenv", "block"),
    ('echo x > ~//"".zshenv', "block"),
    ("echo x > ~//.\\zshenv", "block"),
    ("echo x > ~/./'.zshenv'", "block"),
    ('echo x > ~/./""x/../.zshenv', "block"),
    ('echo x > "~"/./.zshenv', "block"),
    ('echo x > $HOME//"".zshenv', "block"),
    ('echo x > @HOME@/./.""zshenv', "block"),
    # no-delete class
    ('rm ~/""./.claude/notes.txt', "block"),
    ("rm ~//\\.claude/notes.txt", "block"),
    # a braced variable reference followed by a repeated slash or dot segment
    ("hh=~; echo x > ${hh}//.zshenv", "block"),
    ("hh=~; echo x > ${hh}/./.zshenv", "block"),
    ("hh=@HOME@; echo x > ${hh}///.zshenv", "block"),
    ("hh=~; rm ${hh}//.claude/notes.txt", "block"),
    # a braced variable reference inside a brace group
    ("hh=@HOME@; echo x > {${hh}/.zshenv,/tmp/zz}", "block"),
    ("hh=~; echo x > {${hh}/./.zshenv,/tmp/zz}", "block"),
    ("hh=~; echo x > {/tmp/zz,${hh}//.zshenv}", "block"),
    # both at once
    ('hh=~; echo x > ${hh}//.""zshenv', "block"),
    # controls: the same spellings naming an unprotected file
    ('echo x > ~/./""notes.txt', "allow"),
    ("echo x > ~//\\notes.txt", "allow"),
    ('rm ~/""./project/notes.txt', "allow"),
    ("hh=~; echo x > ${hh}//notes.txt", "allow"),
    ("hh=~; echo x > ${hh}/./notes.txt", "allow"),
    ("hh=@HOME@; echo x > {${hh}/notes.txt,/tmp/zz}", "allow"),
    ("hh=~; echo x > {${hh}/./notes.txt,/tmp/zz}", "allow"),
    # a literal brace group of words is not a variable reference
    ("echo x > {a,b}/./notes.txt", "allow"),
]


def test_a_guarded_path_keeps_its_verdict_when_quotes_or_a_braced_variable_surround_its_dot_segments(tmp_path):
    bad = []
    for command, want in CASES:
        got = run_hook("bash", "Bash", {"command": command.replace("@HOME@", str(tmp_path))}, "/tmp", tmp_path)
        if got != want:
            bad.append((command, want, got))
    assert not bad, bad

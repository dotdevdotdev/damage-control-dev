"""A guarded path is judged as the file it names, whatever ``.``, ``..`` and ``/`` are doing in it.

Each row respells a protected path (read-only, zero-access and no-delete classes) with ``.`` or ``..``
segments, repeated or trailing slashes, ``~`` / ``$HOME`` / absolute anchors, from several working
directories, and must get the verdict the plain spelling gets. Controls name an unprotected file
through the same segments and stay allowed. The table drives the real hook entrypoint as a subprocess.
"""

from test_relative_path_operands import ELSEWHERE, FAKE_HOME, _hook

H = FAKE_HOME
PROJECT = H + "/project"

# (cwd, command, verdict)
CASES = [
    # read-only class: shell profile
    ("/tmp", "echo x > ~/./.zshenv", "block"),
    ("/tmp", "echo x > ~/foo/../.zshenv", "block"),
    ("/tmp", "echo x > ~//.zshenv", "block"),
    ("/tmp", "echo x > $HOME/./.zshenv", "block"),
    ("/tmp", "echo x > $HOME/x/../.zshenv", "block"),
    ("/tmp", "echo x > ${HOME}/./.zshenv", "block"),
    ("/tmp", "echo x > ${HOME}//.zshenv", "block"),
    ("/tmp", "echo x > " + H + "/./.zshenv", "block"),
    ("/tmp", "echo x > " + H + "/x/../.zshenv", "block"),
    ("/tmp", "echo x > " + H + "//.zshenv", "block"),
    ("/tmp", "echo x > /tmp/../" + H.lstrip("/") + "/.zshenv", "block"),
    (PROJECT, "echo x > ../x/../.zshenv", "block"),
    (PROJECT, "echo x > ./../.zshenv", "block"),
    (H, "echo x > ./.zshenv", "block"),
    (H, "echo x > ././.zshenv", "block"),
    (H, "echo x > x/../.zshenv", "block"),
    ("/tmp", "echo x | tee ~/./.bashrc", "block"),
    ("/tmp", "cp /golden/stage/a ~/./.gitconfig", "block"),
    ("/tmp", "echo x > {" + H + "/./.zshenv,/tmp/zz}", "block"),
    ("/tmp", "echo x > {~/./.zshenv,/tmp/zz}", "block"),
    ("/tmp", "echo x > ~/.zshenv/", "block"),
    ("/tmp", "echo x > ~/.zshenv/.", "block"),
    ("/tmp", "echo x > ~/.zshenv/./", "block"),
    ("/tmp", "echo x > ~/.zshenv/x/..", "block"),
    ("/tmp", "echo x > '~/./.zshenv'", "block"),
    ("/tmp", 'echo x > "$HOME/./.zshenv"', "block"),
    ("/tmp", 'echo x > "' + H + '/x/../.zshenv"', "block"),
    # git hooks (read-only class) via -C / --git-dir style values
    ("/tmp", "git -C ~/./.ssh show HEAD:id_rsa", "block"),
    ("/tmp", "git --git-dir=~/./.ssh log", "block"),
    ("/tmp", "tar cf /tmp/a.tar -C ~/./.ssh id_rsa", "block"),
    ("/tmp", "d=~/./.ssh; cat $d/id_rsa", "block"),
    ("/tmp", "d=$HOME/x/..; cat $d/.ssh/id_rsa", "block"),
    ("/tmp", "d=~; cat $d/./.ssh/id_rsa", "block"),
    ("/tmp", "cat ~/./{.ssh,x}/id_rsa", "block"),
    ("/tmp", "cat ~/{.,x}/.ssh/id_rsa", "block"),
    ("/tmp", "echo x > " + PROJECT + "/./.git/hooks/pre-commit", "block"),
    ("/tmp", "echo x > " + PROJECT + "/src/../.git/hooks/pre-commit", "block"),
    (PROJECT, "echo x > ./.git/./hooks/pre-commit", "block"),
    (PROJECT + "/src", "echo x > ../.git/hooks/pre-commit", "block"),
    (PROJECT + "/src", "echo x > ./../.git/hooks/pre-commit", "block"),
    (PROJECT, "echo x > .git//hooks//pre-commit", "block"),
    # zero-access class
    ("/tmp", "cat ~/./.ssh/id_rsa", "block"),
    ("/tmp", "cat ~/x/../.ssh/id_rsa", "block"),
    ("/tmp", "cat ~/.ssh/./id_rsa", "block"),
    ("/tmp", "cat ~/.ssh/x/../id_rsa", "block"),
    ("/tmp", "cat ~/.ssh//id_rsa", "block"),
    ("/tmp", "cat $HOME/./.ssh/id_rsa", "block"),
    ("/tmp", "cat ${HOME}/x/../.ssh/id_rsa", "block"),
    ("/tmp", "cat " + H + "/./.ssh/id_rsa", "block"),
    ("/tmp", "cat " + H + "/x/../.ssh/id_rsa", "block"),
    ("/tmp", "cat " + H + "//.ssh//id_rsa", "block"),
    ("/tmp", "cat /" + H + "/.ssh/id_rsa", "block"),
    (PROJECT, "cat ../.ssh/id_rsa", "block"),
    (PROJECT, "cat ./../.ssh/id_rsa", "block"),
    (PROJECT, "cat ../x/../.ssh/id_rsa", "block"),
    (H + "/.ssh", "cat ./id_rsa", "block"),
    (H + "/.ssh", "cat ../.ssh/id_rsa", "block"),
    (H, "cat ./.ssh/./id_rsa", "block"),
    ("/tmp", "cat {" + H + "/./.ssh/id_rsa,/tmp/zz}", "block"),
    ("/tmp", "cat ~/./.config/gh/hosts.yml", "block"),
    ("/tmp", "cat ~/.config/x/../gh/hosts.yml", "block"),
    ("/tmp", "cat $HOME/.cargo/./credentials.toml", "block"),
    ("/tmp", "cat ~/.ssh/", "block"),
    ("/tmp", "cat ~/.ssh/.", "block"),
    ("/tmp", "ls ~/./.ssh/", "block"),
    # no-delete class
    ("/tmp", "rm ~/./.claude/notes.txt", "block"),
    ("/tmp", "rm ~/x/../.claude/notes.txt", "block"),
    ("/tmp", "rm $HOME/./.claude/notes.txt", "block"),
    ("/tmp", "rm " + H + "/./.claude/notes.txt", "block"),
    ("/tmp", "rm " + H + "//.claude//notes.txt", "block"),
    (H, "rm ./.claude/./notes.txt", "block"),
    (H + "/.claude", "rm ./notes.txt", "block"),
    (H + "/.claude", "rm ../.claude/notes.txt", "block"),
    (PROJECT, "rm ../.claude/notes.txt", "block"),
    (PROJECT, "rm ./../.claude/notes.txt", "block"),
    (PROJECT + "/.git", "unlink ./HEAD", "block"),
    (PROJECT + "/.git", "unlink ../.git/HEAD", "block"),
    (PROJECT, "unlink ./.git/./HEAD", "block"),
    (PROJECT, "unlink .git//HEAD", "block"),
    # controls: unprotected names through the same segments
    ("/tmp", "echo x > ~/./notes.txt", "allow"),
    ("/tmp", "echo x > ~/x/../notes.txt", "allow"),
    ("/tmp", "echo x > $HOME/./notes.txt", "allow"),
    ("/tmp", "echo x > " + H + "/x/../notes.txt", "allow"),
    (PROJECT, "echo x > ../x/../notes.txt", "allow"),
    ("/tmp", "cat ~/./notes.txt", "allow"),
    (PROJECT, "cat ../notes.txt", "allow"),
    (ELSEWHERE, "echo x > ./.zshenv", "allow"),
    (ELSEWHERE, "cat ./.ssh/./id_rsa", "allow"),
    (ELSEWHERE, "cat x/../.ssh/id_rsa", "allow"),
    (ELSEWHERE, "echo x > x/../.zshenv", "allow"),
    ("/tmp", "echo x > /tmp/../tmp/zz", "allow"),
]


def test_a_guarded_path_is_judged_as_the_file_it_names_through_dot_segments(tmp_path):
    bad = [(cwd, cmd, want, got) for cwd, cmd, want in CASES for got in [_hook(cwd, cmd, tmp_path)] if got != want]
    assert not bad, "\n".join(map(str, bad))

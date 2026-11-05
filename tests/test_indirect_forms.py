"""Two spellings that hide what a command runs or where a path points, judged through the real hook.

An interpreter name the shell reassembles from quoted or escaped pieces runs the same script, so the
script is read. A path held in a variable built from earlier variables is the same path as the one
typed out. Each table drives the hook entrypoint as a subprocess (exit 2 = block).
"""

from damage_control import shellexpand

from hookrun import run_hook

BAD_PY = "import os\nos.system('rm -rf /')\n"
CLEAN_PY = "print('hi')\n"

SCRIPT_CASES = [
    ("python3 bad.py", "block"),
    ('pyt""hon3 bad.py', "block"),
    ('p""ython3 bad.py', "block"),
    ("py\\thon3 bad.py", "block"),
    ("'python3' bad.py", "block"),
    ('"python3" bad.py', "block"),
    ('pyt""hon3 clean.py', "allow"),
    ("py\\thon3 clean.py", "allow"),
]


def test_a_script_run_through_a_split_interpreter_name_is_judged_by_its_contents(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "bad.py").write_text(BAD_PY)
    (root / "clean.py").write_text(CLEAN_PY)
    home = tmp_path / "home"
    home.mkdir()
    got = [(command, run_hook("bash", "Bash", {"command": command}, str(root), home)) for command, _ in SCRIPT_CASES]
    assert got == SCRIPT_CASES


PATH_CASES = [
    ("d=$HOME/x/..; cat $d/.ssh/id_rsa", "block"),
    ("hh=$HOME; d=$hh/x/..; cat $d/.ssh/id_rsa", "block"),
    ("hh=$HOME; d=${hh}/x/..; cat $d/.ssh/id_rsa", "block"),
    ("a=$HOME; b=$a/x; c=$b/..; cat $c/.ssh/id_rsa", "block"),
    ("a=$HOME; b=$a/x/..; c=${b}/.ssh; cat $c/id_rsa", "block"),
    ("h=$HOME; d=$h/x; cat $d/.ssh/id_rsa", "allow"),
    ("hh=$HOME; d=$hh/x/..; cat $d/notes.txt", "allow"),
]


def test_a_path_held_in_a_variable_built_from_another_variable_is_resolved(tmp_path):
    got = [(command, run_hook("bash", "Bash", {"command": command}, "/tmp", tmp_path)) for command, _ in PATH_CASES]
    assert got == PATH_CASES


CHAINS = [
    ({"h": "$HOME", "d": "$h/x"}, {"h": "$HOME", "d": "$HOME/x"}),
    ({"h": "/a", "d": "${h}/x"}, {"h": "/a", "d": "/a/x"}),
    ({"h": "/a", "d": "$hx/x"}, {"h": "/a", "d": "$hx/x"}),
    ({"d": "$h/x", "h": "/a"}, {"d": "$h/x", "h": "/a"}),
    ({"a": "/r", "b": "$a/s", "c": "$b/t"}, {"a": "/r", "b": "/r/s", "c": "/r/s/t"}),
]


def test_assignment_chain_replaces_only_earlier_whole_name_references():
    assert [shellexpand.resolve_assignment_chain(assigns) for assigns, _ in CHAINS] == [want for _, want in CHAINS]

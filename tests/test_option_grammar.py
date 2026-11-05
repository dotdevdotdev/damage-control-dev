"""Which operand is the program: interpreter option clusters and the options of launchers in front of an interpreter.

Each table drives the real hook entrypoint (exit 2 = block) over a data file whose text holds guarded
operations, next to a harmless file. A command that runs the file must be judged on what it holds; a
command that does not run it (the program is inline) must give it the verdict of the harmless one.
"""

from pathlib import Path

import pytest

from hookrun import run_hook

DATA = "import os\nos.system('rm -rf /')\nrequire('child_process').execSync('rm -rf /');\nrm -rf /\n"
HARMLESS = "name: example\n"

# The file is the program: the option cluster before it holds a letter that takes a value (or no value at all).
CLUSTER_RUNS_FILE = [
    "python3 -Wignore::DeprecationWarning {f}", "python3 -BWerror::ResourceWarning {f}", "python3 -W error {f}",
    "python3 -Wc {f}", "python3 -Xdev {f}", "python3 -X importtime {f}", "python3 -Bu {f}",
    "perl -I lib {f}", "perl -Ilib -MCarp {f}", "perl -pi.bak {f}", "perl -Fe {f}", "perl -l {f}",
    "ruby -rjson {f}", "ruby -I lib {f}", "ruby -W:no-deprecated {f}", "ruby -Ku {f}", "ruby -C . {f}",
    "node -r ./hook.js {f}", "node --require ./hook.js {f}",
]
# The program is inline (or a module): the file is an argument.
CLUSTER_INLINE = [
    "python3 -Bc 'print(1)' {f}", "python3 -c 'print(1)' {f}", "python3 -Bm json.tool {f}", "python3 -Wignore -c 'x' {f}",
    "perl -lne 'print' {f}", "perl -ne 'print' {f}", "perl -pe 's/a/b/' {f}", "perl -le 'print 1' {f}",
    "ruby -ne 'puts' {f}", "ruby -ane 'puts' {f}", "ruby -e 'puts 1' {f}",
    "node -pe '1' {f}", "node -e '1' {f}",
]

# A launcher with option arguments in front of an interpreter that runs the file. The second item is
# the verdict the same command gets over the harmless file.
WRAPPED = [
    ("uvx --with requests python3 {f}", "allow"),
    ("uvx --with requests --python 3.12 python3 {f}", "allow"),
    ("uvx --from somepkg python3 {f}", "allow"),
    ("npx --package somepkg node {f}", "allow"),
    ("npx -p somepkg node {f}", "allow"),
    ("pipx run --spec somepkg python3 {f}", "allow"),
    ("pipx run --python python3 python3 {f}", "allow"),
    ("poetry run python3 {f}", "allow"),
    ("poetry run --directory . python3 {f}", "allow"),
    ("uv run --with requests python3 {f}", "ask"),
    ("uv run --python 3.12 --with requests python3 {f}", "ask"),
    ("env -u SOMEVAR python3 {f}", "allow"),
    ("env -i -C . python3 {f}", "allow"),
    ("nohup python3 {f}", "allow"),
    ("timeout -k 5 10 python3 {f}", "allow"),
    ("timeout 1.5 python3 {f}", "allow"),
    ("time -p python3 {f}", "allow"),
]


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    root = Path(tmp_path_factory.mktemp("grammar")).resolve()
    (root / "data.yaml").write_text(DATA)
    (root / "harmless.yaml").write_text(HARMLESS)
    return root


@pytest.fixture
def home(tmp_path):
    (tmp_path / "home").mkdir()
    return tmp_path / "home"


def _verdict(command, tree, home):
    return run_hook("bash", "Bash", {"command": command}, str(tree), home)


def test_a_file_after_an_option_cluster_that_takes_a_value_is_read_as_the_script(tree, home):
    wrong = [(t, v) for t in CLUSTER_RUNS_FILE if (v := _verdict(t.format(f="data.yaml"), tree, home)) != "block"]
    assert wrong == []


def test_a_harmless_file_after_the_same_clusters_stays_allowed(tree, home):
    wrong = [(t, v) for t in CLUSTER_RUNS_FILE if (v := _verdict(t.format(f="harmless.yaml"), tree, home)) != "allow"]
    assert wrong == []


def test_a_cluster_that_carries_the_program_leaves_the_file_an_argument(tree, home):
    wrong = []
    for template in CLUSTER_INLINE:
        with_data = _verdict(template.format(f="data.yaml"), tree, home)
        with_harmless = _verdict(template.format(f="harmless.yaml"), tree, home)
        if with_data != with_harmless or with_data != "allow":
            wrong.append((template, with_data, with_harmless))
    assert wrong == []


def test_the_script_behind_a_launcher_with_option_arguments_is_judged(tree, home):
    wrong = [(t, v) for t, _ in WRAPPED if (v := _verdict(t.format(f="data.yaml"), tree, home)) != "block"]
    assert wrong == []


def test_a_harmless_script_behind_the_same_launchers_gets_its_usual_verdict(tree, home):
    wrong = []
    for template, expected in WRAPPED:
        got = _verdict(template.format(f="harmless.yaml"), tree, home)
        if got != expected:
            wrong.append((template, got, expected))
    assert wrong == []

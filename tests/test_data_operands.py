"""A file named as an operand that no command runs is data: its text does not decide the verdict.

Script indirection reads a file only when the command runs it. Each row of the table is a command
over a data file whose text holds guarded operations, next to the same command over a harmless file;
the real hook (exit 2 = block) must give both the same verdict. The same data file run as a script
still blocks.
"""

from pathlib import Path

import pytest

from hookrun import run_hook

DATA = "import os\nos.system('rm -rf /')\nrequire('child_process').execSync('rm -rf /');\nrm -rf /\n"
HARMLESS = "name: example\n"

# Commands where the file is only an argument. {f} is the data file or the harmless one.
NOT_RUN = [
    "shasum {f}", "shasum -a 256 {f}", "cat {f}", "wc -l {f}", "diff {f} harmless.yaml", "diff harmless.yaml {f}",
    "grep -n name {f}", "head -n 3 {f}", "tail {f}", "sort {f}", "file {f}", "stat {f}",
    "node --eval='1' {f}", "node --print=1 {f}", "node --check {f}", "node -c {f}", "node --version {f}",
    "python3 --version {f}", "python3 -V {f}", "python3 --help {f}",
    "perl -v {f}", "perl -V:osname {f}", "ruby --version {f}", "ruby -c {f}",
    "bash -n {f}", "sh -en {f}", "bash --version {f}", "bash --help {f}",
]
# The same file handed to an interpreter that runs it.
RUN = ["bash {f}", "sh ./{f}", "source {f}", "python3 {f}", "node {f}", "perl {f}", "ruby {f}", "./{f}"]


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    root = Path(tmp_path_factory.mktemp("operands")).resolve()
    (root / "data.yaml").write_text(DATA)
    (root / "data.yaml").chmod(0o755)
    (root / "harmless.yaml").write_text(HARMLESS)
    (root / "harmless.yaml").chmod(0o755)
    return root


@pytest.fixture
def home(tmp_path):
    (tmp_path / "home").mkdir()
    return tmp_path / "home"


def test_a_data_file_operand_gets_the_verdict_of_a_harmless_one(tree, home):
    wrong = []
    for template in NOT_RUN:
        with_data = run_hook("bash", "Bash", {"command": template.format(f="data.yaml")}, str(tree), home)
        with_harmless = run_hook("bash", "Bash", {"command": template.format(f="harmless.yaml")}, str(tree), home)
        if with_data != with_harmless or with_data != "allow":
            wrong.append((template, with_data, with_harmless))
    assert wrong == []


def test_the_same_file_run_as_a_script_still_blocks(tree, home):
    wrong = []
    for template in RUN:
        got = run_hook("bash", "Bash", {"command": template.format(f="data.yaml")}, str(tree), home)
        if got != "block":
            wrong.append((template, got))
    assert wrong == []

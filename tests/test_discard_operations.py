"""Operations that discard uncommitted work get one verdict per operation, however git is asked to spell them.

Each row drives the real hook entrypoint (exit 2 = block). The tiers: a hard reset and a forced clean block;
a forced switch, a whole-tree restore and a forced worktree removal ask; a dry run, a soft or mixed reset,
an index-only restore and a plain removal stay allowed. Text that only mentions an operation is not one.
"""

import pytest

from hookrun import run_hook

BLOCK = [
    # the canonical forms (controls: judged before the helper existed)
    "git reset --hard", "git clean -fd", "git clean -f",
    # option abbreviations: git accepts any unambiguous prefix
    "git reset --har", "git reset --ha", "git reset --h", "git clean --for", "git clean --f", "git clean --no-dry-run -fd",
    "git clean -n --no-dry-run -f",
    # prefixes and globals around the verb
    "git -C . reset --har", "sudo git reset --har", "env GIT_PAGER=cat git reset --har", 'sh -c "git reset --har"',
    # an alias names the operation
    "git -c alias.x='reset --hard' x", "git -c alias.x='reset --har' x", "git -c alias.x='clean -f' x",
    "git -c alias.a=b -c alias.b='reset --hard' a",
    # the feeder's input is the option
    "echo --hard | xargs git reset --hard",
]
ASK = [
    "git checkout -f", "git checkout .", "git restore .",
    "git switch -f main", "git switch --force main", "git switch --discard-changes main", "git switch --discard main",
    "git switch --di main", "git switch -fc newbranch",
    "git restore --worktree .", "git restore --wor .", "git restore -W .", "git restore -SW .",
    "git restore --source=HEAD --staged --worktree .", "git restore --source HEAD -- .", "git restore '*'",
    "git restore ':/'", "git restore ':(top)*'", "git restore ./", "git restore --staged --worktree --no-staged .",
    "git worktree remove --force ../wt", "git worktree remove --fo ../wt", "git worktree remove -f ../wt",
    "git worktree remove -f -f ../wt",
    "git -C . switch -f main", "sudo git restore -W .", 'sh -c "git switch -f main"',
    "git -c alias.x='switch -f' x main", "git -c alias.x='restore -W' x .",
    "echo --hard | xargs git reset", "git ls-files -m | xargs git restore", "echo x | xargs -n1 git worktree remove",
    "echo -f | xargs git clean -n",
]
ALLOW = [
    "git reset --soft HEAD~1", "git reset --mixed", "git reset --so HEAD~1", "git reset HEAD file.txt", "git reset",
    "git clean -n", "git clean --dry-run -fd", "git clean --dry -fd", "git clean --d --for", "git clean -nfd",
    "git clean -fn",
    "git switch main", "git switch -c feature", "git switch --no-discard-changes main", "git switch --d main",
    "git switch -f --no-force main", "git switch --f main",
    "git restore --staged .", "git restore -S .", "git restore --st .", "git restore --staged --no-worktree .",
    "git restore file.txt", "git restore --source=HEAD~1 src/a.py", "git restore --staged -W src/a.py",
    "git worktree remove ../wt", "git worktree remove -f --no-force ../wt", "git worktree list", "git worktree add ../wt",
    "git -c alias.co=status co",
    "git ls-files -m | xargs git restore --", "echo x | xargs git status",
    # text that mentions an operation
    "echo 'git reset --har'", "echo git switch -f main", "printf 'git restore --worktree .\\n'",
    "grep -r 'git clean --for' docs", "git log --grep='git reset --har'", "echo 'run git worktree remove --force to drop it'",
]


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    return tmp_path_factory.mktemp("discard-home").resolve()


def verdict(command, home):
    return run_hook("bash", "Bash", {"command": command}, str(home), home)


@pytest.mark.parametrize("command", BLOCK)
def test_blocks(command, home):
    assert verdict(command, home) == "block"


@pytest.mark.parametrize("command", ASK)
def test_asks(command, home):
    assert verdict(command, home) == "ask"


@pytest.mark.parametrize("command", ALLOW)
def test_allows(command, home):
    assert verdict(command, home) == "allow"

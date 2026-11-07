"""A protected path is judged as the path the shell resolves, however the command spells it.

Before the rules look at a word, the shell has removed its quotes, expanded its brace groups, applied
the ``cd`` that came before it and, on a case-insensitive filesystem, treated letter case as irrelevant.
Each test here covers one of those steps in the machinery every path class shares (control plane,
zero-access, read-only, no-delete), and pairs it with a spelling that must stay allowed.
"""

import pytest

from damage_control import engine


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".ssh").mkdir()
    (home / "project").mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def cfg():
    config = engine.load_config(engine.bundled_rule_sources(), engine.bundled_tooldefs_dir())
    config["safety"] = {"enabled": True, "disabled_rules": []}
    return config


def _verdicts(cfg, cwd, commands):
    return {c: engine.check_command(c, cfg, cwd=str(cwd))["decision"] for c in commands}


def _wrong(cfg, cwd, commands, want):
    return {c: d for c, d in _verdicts(cfg, cwd, commands).items() if d != want}


# --- the fold of a path run keeps what a continuation still needs ---------------------------------

def test_the_path_fold_keeps_the_slash_a_brace_group_or_glob_continues(home):
    h = str(home)
    assert engine.canonicalize_command("touch ~/dir/{a,b}") == f"touch {h}/dir/{{a,b}}"
    assert engine.canonicalize_command("mv ~/{a,b} x") == f"mv {h}/{{a,b}} x"
    assert engine.canonicalize_command("ls ~/dir/*") == f"ls {h}/dir/*"
    assert engine.canonicalize_command("ls ~/dir/$x") == f"ls {h}/dir/$x"


def test_the_path_fold_keeps_the_start_of_a_name_a_quote_continues(home):
    h = str(home)
    assert engine.canonicalize_command('touch ~/.""name') == f'touch {h}/.""name'
    assert engine.canonicalize_command('touch ~/""name') == f'touch {h}/""name'
    assert engine.canonicalize_command("touch ~/.\\name") == f"touch {h}/.\\name"
    # the segments before the continued name still fold
    assert engine.canonicalize_command('touch ~/a/../.""name') == f'touch {h}/.""name'


def test_the_path_fold_still_folds_a_word_that_ends(home):
    h = str(home)
    for spelled in ("~/a/./b/", "~//a/b", "~/x/../a/b", '"~/a/./b"'):
        assert engine.canonicalize_command(f"cat {spelled}").replace('"', "") == f"cat {h}/a/b", spelled


# --- brace groups and quotes in a move source ------------------------------------------------------

def test_a_move_scan_reads_the_words_the_shell_makes_of_a_brace_group(home):
    scan = engine.producer_scan("mv {a,b} c")
    assert [(op.sources, op.dests) for op in scan.direct] == [(["a", "b"], ["c"])]
    scan = engine.producer_scan("mv ~/dir/{a,b} c")
    assert [op.sources for op in scan.direct] == [[f"{home}/dir/a", f"{home}/dir/b"]]


def test_a_brace_group_keeps_the_shell_order_so_the_last_word_stays_the_destination(home):
    scan = engine.producer_scan("mv x {a,b}")
    assert [(op.sources, op.dests) for op in scan.direct] == [(["x", "a"], ["b"])]


def test_a_move_scan_reads_a_verb_the_quotes_split_and_a_home_variable(home):
    for spelled in ('m""v $HOME/x /tmp/y', "m\\v ${HOME}/x /tmp/y", "'m'v ~/x /tmp/y"):
        assert [op.sources for op in engine.producer_scan(spelled).direct] == [[f"{home}/x"]], spelled


@pytest.mark.parametrize("command", [
    "mv {~/.claude,/tmp/zz} /tmp/x",
    "mv ~/{.claude,zz} /tmp/x",
    "mv $HOME/{.claude,zz} /tmp/x",
    'm""v ~/.claude /tmp/x',
    "mv $HOME/.claude /tmp/x",
    "mv ${HOME}/.claude /tmp/x",
    "mv ~/.claude/{settings.json,zz} /tmp/x",
    "touch ~/.claude/{settings.json,zz}",
    'touch ~/.""claude/settings.json',
    'touch ~/.claude/""settings.json',
])
def test_a_respelled_protected_path_is_judged_like_the_plain_one(home, cfg, command):
    assert engine.check_command(command, cfg, cwd="/tmp")["decision"] == "block"


def test_a_similarly_named_path_beside_a_protected_one_stays_allowed(home, cfg):
    commands = [
        "mv {~/.claude-notes,/tmp/zz} /tmp/x",
        "mv ~/{.claude-notes,zz} /tmp/x",
        "touch ~/.claude-notes/{settings.json,zz}",
        'touch ~/.claude-notes/""settings.json',
        "mv {/tmp/a,/tmp/b} /tmp/c",
    ]
    assert not _wrong(cfg, "/tmp", commands, "allow")


# --- a relative cd, then a relative operand ---------------------------------------------------------

def test_cd_scopes_resolve_a_relative_first_cd_against_the_start_directory(home):
    known, unknown = engine._cwd_scopes("cd .ssh && cat id_rsa", str(home))
    assert [scope for scope, _rest in known] == [f"{home}/.ssh"] and not unknown
    known, unknown = engine._cwd_scopes("cd .ssh && cat id_rsa")
    assert not known and unknown


@pytest.mark.parametrize("command", [
    "cd .claude && touch settings.json",
    "cd .claude && mv settings.json /tmp/x",
    "cd .claude && echo x > settings.json",
    "cd .claude; touch settings.json",
    "cd .ssh && cat id_rsa",
    'cd .""ssh && cat id_rsa',
    'cd ".ssh" && cat id_rsa',
    "cd .s\\sh && cat id_rsa",
    'c""d .ssh && cat id_rsa',
    "c\\d .ssh && cat id_rsa",
    'c""d .claude && touch settings.json',
    'cd .""claude && touch settings.json',
    "cd .c\\laude && touch settings.json",
    "cd project && cd ../.claude && touch settings.json",
    'c""d project && cd ../.claude && touch settings.json',
    "c\\d project && cd ../.claude && touch settings.json",
])
def test_a_relative_cd_into_a_protected_directory_is_judged_by_where_it_lands(home, cfg, command):
    assert engine.check_command(command, cfg, cwd=str(home))["decision"] == "block"


@pytest.mark.parametrize("verb", ["cd", 'c""d', "c\\d", "'c'd"])
def test_a_quote_split_cd_verb_still_moves_the_directory(home, cfg, verb):
    assert engine.check_command(f"{verb} .. && touch .claude/settings.json", cfg, cwd=str(home / "project"))["decision"] == "block"


def test_a_relative_cd_into_the_protected_directory_from_below_the_home_directory(home, cfg):
    assert engine.check_command("cd .. && touch .claude/settings.json", cfg, cwd=str(home / "project"))["decision"] == "block"


def test_a_relative_cd_that_lands_elsewhere_stays_allowed(home, cfg):
    commands = [
        "cd project && touch settings.json",
        "cd .claude-notes && touch settings.json",
        "cd .ssh-notes && cat id_rsa",
        "cd .claude && cd ../project && touch settings.json",
        "cd .. && touch .claude/settings.json",  # the directory above the home directory
    ]
    assert not _wrong(cfg, home, commands, "allow")


# --- letter case on a case-insensitive filesystem ----------------------------------------------------

def _fold(monkeypatch, on):
    monkeypatch.setattr(engine, "_casefolds_paths", lambda path: on)


@pytest.mark.parametrize("command", [
    "mv ~/.CLAUDE /tmp/x",
    "mv ~/.Claude/ /tmp/x",
    "mv {~/.CLAUDE,/tmp/zz} /tmp/x",
    "mv ~/{.CLAUDE,zz} /tmp/x",
    "touch ~/.CLAUDE/settings.json",
    "cd .CLAUDE && touch settings.json",
    "cd .SSH && cat id_rsa",
])
def test_a_letter_case_variant_of_a_protected_path_is_judged_like_the_plain_one(home, cfg, monkeypatch, command):
    _fold(monkeypatch, True)
    assert engine.check_command(command, cfg, cwd=str(home))["decision"] == "block"


def test_a_letter_case_variant_stays_allowed_where_the_filesystem_tells_case_apart(home, cfg, monkeypatch):
    _fold(monkeypatch, False)
    assert engine.check_command("mv ~/.CLAUDE /tmp/x", cfg, cwd="/tmp")["decision"] == "allow"


def test_a_letter_case_variant_outside_the_protected_tree_stays_allowed_with_folding_on(home, cfg, monkeypatch):
    _fold(monkeypatch, True)
    commands = ["mv /tmp/.CLAUDE /tmp/x", "mv ~/.CLAUDE-notes /tmp/x", "cd /tmp/.CLAUDE && touch settings.json"]
    assert not _wrong(cfg, home, commands, "allow")

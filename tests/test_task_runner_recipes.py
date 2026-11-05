"""A command that starts a task runner is judged on the recipe text it will run.

``make``, ``npm|pnpm|yarn|bun run`` and ``just`` run text that lives in a Makefile, ``package.json`` or
justfile. The scan locates it (recipefile.py) and judges it like a script. The first table drives the
real hook entrypoint (exit 2 = block); the corpus runs in-process so file states a subprocess cannot
build cheaply (a file over the cap, a deep chain) are real files too.
"""

import os
import time
from pathlib import Path

import pytest

from damage_control import engine, recipefile
from damage_control.engine import bundled_rule_sources, bundled_tooldefs_dir, check_command, load_config

from hookrun import run_hook

BAD = "rm -rf /"
FORCE_PUSH = "git push --force origin main"

MAKEFILE = f"""OUT = /
CFLAGS := -O2
REMOTE = --force origin
.PHONY: all clean build gen tidy compile unk deep pre fine ship
all: build
build: gen
\t@$(CC) $(CFLAGS) -o app main.c
gen:
\t-echo gen
clean:
\t{BAD}
tidy:
\t$(RM) -r $(OUT)
compile:
\t$(CC) -o $@ $<
unk:
\techo $(shell uname)
deep: clean
\techo done
pre: bad_dep
bad_dep:
\t{FORCE_PUSH}
fine:
\techo hello \\
\t  world
ship:
\tgit push $(REMOTE) main
"""

FILES = {
    # make
    "mk/Makefile": MAKEFILE,
    "mk/sub/Makefile": f"clean:\n\t{BAD}\n",
    "mk/other.mk": f"wipe:\n\t{BAD}\n",
    "mk_default/Makefile": f"clean:\n\t{BAD}\n",
    "mk_default_ok/Makefile": "all:\n\techo ok\nclean:\n\t" + BAD + "\n",
    "mk_gnu/GNUmakefile": f"wipe:\n\t{BAD}\n",
    "mk_gnu/Makefile": "wipe:\n\techo harmless\n",
    "mk_inc/Makefile": "include common.mk\nall: wipe\n",
    "mk_inc/common.mk": f"wipe:\n\t{BAD}\n",
    "mk_inc2/Makefile": "include a.mk\n",
    "mk_inc2/a.mk": "include b.mk\nwipe:\n\techo ok\n",
    "mk_inc_opt/Makefile": "-include missing.mk\nall:\n\techo ok\n",
    "mk_cond/Makefile": "ifeq ($(X),1)\nDIR=/\nendif\nwipe:\n\techo $(DIR)\nok:\n\techo ok\n",
    "mk_pattern/Makefile": f"%.o: %.c\n\t{BAD}\n",
    "mk_loop/Makefile": "a: b\n\techo a\nb: a\n\techo b\n",
    "mk_recurse/Makefile": "a:\n\t$(MAKE) b\nb:\n\t$(MAKE) c\nc:\n\t$(MAKE) d\nd:\n\t$(MAKE) e\ne:\n\techo e\n",
    "mk_recurse_bad/Makefile": f"a:\n\t$(MAKE) b\nb:\n\t$(MAKE) -C inner wipe\n",
    "mk_recurse_bad/inner/Makefile": f"wipe:\n\t{BAD}\n",
    "mk_huge/Makefile": "all:\n" + "\techo x\n" * 80000,
    "mk_clean/Makefile": "all:\n\techo hi\n\tls -la\n",
    # npm family
    "npm/package.json": (
        '{"name":"x","scripts":{"nuke":"%s","build":"echo b","lint":"echo ok","test":"echo t",'
        '"posttest":"%s","prebuild":"echo pre","chain":"npm run nuke","start":"node server.js"}}' % (BAD, FORCE_PUSH)
    ),
    "npm/sub/keep": "",
    "npm_bad_json/package.json": "{ not json",
    "npm_no_scripts/package.json": '{"name":"x"}',
    "npm_pre/package.json": '{"scripts":{"build":"echo b","prebuild":"%s"}}' % BAD,
    # just
    "just/justfile": f"""set dotenv-load
root := "/"
default: build
build:
    echo build
nuke:
    rm -rf {{{{root}}}}
wipe target:
    rm -rf {{{{target}}}}
safe target="build":
    echo {{{{target}}}}
dep: nuke
    echo done
shebang:
    #!/usr/bin/env python3
    import os
    os.system('{BAD}')
unk:
    echo {{{{ invocation_directory() }}}}
""",
    "just_import/justfile": "import 'more.just'\nbuild:\n    echo ok\n",
    "just_default_bad/justfile": f"nuke:\n    {BAD}\n",
    # task: a documented gap, not parsed
    "task/Taskfile.yml": f"version: '3'\ntasks:\n  nuke:\n    cmds:\n      - {BAD}\n",
}


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    root = Path(os.path.realpath(tmp_path_factory.mktemp("recipes")))
    for name, text in FILES.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (root / "empty").mkdir()
    return root


@pytest.fixture(scope="module")
def cfg():
    config = load_config(bundled_rule_sources(), bundled_tooldefs_dir())
    config["safety"] = {"enabled": True, "disabled_rules": []}
    return config


@pytest.fixture
def home(tmp_path):
    (tmp_path / "home").mkdir()
    return tmp_path / "home"


# (cwd relative to the tree, command, verdict)
CORPUS = [
    # make: the named target, its prerequisites, variables, line prefixes, continuations
    ("mk", "make clean", "block"), ("mk", "make deep", "block"), ("mk", "make pre", "block"),
    ("mk", "make tidy", "block"),  # $(RM) -r $(OUT) with OUT = /
    ("mk", "make all", "allow"), ("mk", "make build", "allow"), ("mk", "make fine", "allow"),
    ("mk", "make compile", "allow"), ("mk", "make nothere", "allow"), ("mk", "make all build", "allow"),
    ("mk", "make all clean", "block"), ("mk", "make -j4 clean", "block"), ("mk", "make -j 4 -k clean", "block"),
    ("mk", "make -s clean", "block"), ("mk", "gmake clean", "block"), ("mk", "sudo make clean", "block"),
    ("mk", "/usr/bin/make clean", "block"), ("mk", "FOO=1 make clean", "block"), ("mk", "bash -c 'make clean'", "block"),
    ("mk", "ls && make clean", "block"), ("mk", "make clean | tee log", "block"),
    ("mk", "make clean # ask: reviewed", "ask"), ("mk", "make clean # allow: reviewed", "block"),
    # the default goal, -C, -f, cd, command-line variables
    ("mk_default", "make", "block"), ("mk_default_ok", "make", "allow"), ("mk_default_ok", "make clean", "block"),
    ("mk", "make -C sub clean", "block"), ("mk", "make --directory=sub clean", "block"),
    (".", "make -C mk/sub clean", "block"), (".", "cd mk/sub && make clean", "block"),
    ("mk", "make -f other.mk wipe", "block"), ("mk", "make --file other.mk wipe", "block"),
    ("mk", "make -C missing clean", "allow"), (".", "make clean", "allow"),
    # a command-line variable beats the Makefile's: the force flag goes, the plain push (an ask) stays
    ("mk", "make ship", "block"), ("mk", "make ship REMOTE=origin", "ask"), ("mk", "make REMOTE=--force ship", "block"),
    ("mk", "make OUT=/ compile", "allow"),
    ("mk_gnu", "make wipe", "block"),  # GNUmakefile outranks Makefile
    # include: one level
    ("mk_inc", "make wipe", "block"), ("mk_inc", "make", "block"), ("mk_inc2", "make wipe", "ask"),
    ("mk_inc_opt", "make", "allow"),
    # what cannot be resolved is an ask, not an allow
    ("mk", "make unk", "ask"), ("mk_cond", "make wipe", "ask"), ("mk_cond", "make ok", "allow"),
    ("mk", "make --eval='x:=1' all", "ask"),
    # pattern rules, cycles, recursion
    ("mk_pattern", "make foo.o", "block"), ("mk_loop", "make a", "allow"),
    ("mk_recurse", "make a", "ask"), ("mk_recurse_bad", "make a", "block"),
    # budgets
    ("mk_huge", "make all", "ask"), ("mk_clean", "make all", "allow"),
    # npm, pnpm, yarn, bun
    ("npm", "npm run nuke", "block"), ("npm", "npm run-script nuke", "block"), ("npm", "pnpm run nuke", "block"),
    ("npm", "yarn run nuke", "block"), ("npm", "bun run nuke", "block"), ("npm", "yarn nuke", "block"),
    ("npm", "pnpm nuke", "block"), ("npm", "npm run chain", "block"), ("npm", "npm --silent run nuke", "block"),
    ("npm", "npm run nuke -- --flag", "block"), ("npm", "npm test", "block"),  # posttest hook
    ("npm", "npm t", "block"), ("npm", "pnpm test", "block"), ("npm", "yarn test", "block"),
    # a clean or absent recipe adds nothing: the verdict is the typed command's own ("typed")
    ("npm", "npm run build", "typed"), ("npm", "npm run lint", "typed"), ("npm", "npm start", "typed"),
    ("npm", "npm run missing", "typed"), ("npm", "npm run", "typed"), ("npm", "npm install", "typed"),
    ("npm", "pnpm install", "typed"), ("npm", "yarn add left-pad", "typed"), ("npm", "bun test", "typed"),
    ("npm", "yarn build", "typed"), ("npm", "npm run nuke # ask: reviewed", "ask"),
    ("npm_pre", "npm run build", "block"),  # prebuild hook
    ("npm/sub", "npm run nuke", "block"), ("npm/sub", "npm --prefix .. run nuke", "block"),
    ("npm", "npm --prefix sub run nuke", "block"), ("npm", "cd sub && npm run nuke", "block"),
    ("npm", "npm run -w pkg build", "ask"), ("npm", "pnpm --filter pkg run build", "ask"),
    ("npm", "npm run build --workspaces", "ask"),
    ("npm_bad_json", "npm run nuke", "typed"), ("npm_no_scripts", "npm run nuke", "typed"),
    (".", "npm run nuke", "typed"),
    # just
    ("just", "just nuke", "block"), ("just", "just wipe /", "block"), ("just", "just dep", "block"),
    ("just", "just shebang", "block"), ("just", "just -f justfile nuke", "block"),
    ("just", "just --justfile justfile nuke", "block"), (".", "just -d just nuke", "block"),
    ("just", "just build nuke", "block"), ("just", "just nuke # ask: reviewed", "ask"),
    ("just", "just", "allow"), ("just", "just build", "allow"), ("just", "just safe", "allow"),
    ("just", "just safe x", "allow"), ("just", "just missing", "allow"), ("just", "just --list", "allow"),
    ("just", "just --evaluate", "allow"), ("just", "just unk", "ask"),
    ("just_import", "just build", "allow"), ("just_import", "just elsewhere", "ask"),
    ("just_default_bad", "just", "block"), ("just_default_bad/..", "just nuke", "allow"),
    # task is a documented gap: the Taskfile is not read
    ("task", "task nuke", "allow"),
    # typed commands are judged as before
    (".", "echo hi", "allow"), (".", "make --version", "allow"), (".", "rm -rf /", "block"),
]


@pytest.mark.parametrize("cwd,command,want", CORPUS, ids=[f"{i:03d}-{c[1][:44]}" for i, c in enumerate(CORPUS)])
def test_operation_corpus(tree, cfg, cwd, command, want):
    result = check_command(command, cfg, cwd=str(tree / cwd))
    if want == "typed":
        want = check_command(command, cfg, cwd=str(tree / "empty"))["decision"]
    assert result["decision"] == want, (result["decision"], result.get("id"), result["reason"])


# -- the real hook --------------------------------------------------------------------------------------------

HOOK_TABLE = [
    ("mk", "make clean", "block"), ("mk", "make all", "allow"), ("mk", "make unk", "ask"),
    ("mk", "make clean # ask: reviewed", "ask"), ("mk_huge", "make all", "ask"),
    ("npm", "npm run nuke", "block"), ("npm", "npm test", "block"), ("npm", "npm run -w pkg build", "ask"),
    ("just", "just nuke", "block"), ("just", "just build", "allow"), ("just", "just unk", "ask"),
    ("just", "just nuke # ask: reviewed", "ask"), ("task", "task nuke", "allow"),
]


@pytest.mark.parametrize("cwd,command,want", HOOK_TABLE, ids=[f"{c[1][:40]}" for c in HOOK_TABLE])
def test_the_real_hook_reads_the_recipe(tree, home, cwd, command, want):
    assert run_hook("bash", "Bash", {"command": command}, str(tree / cwd), home) == want


# -- findings, budgets, verdict class ---------------------------------------------------------------------------

def test_a_finding_names_the_runner_the_file_and_the_rule(tree, cfg):
    result = check_command("make clean", cfg, cwd=str(tree / "mk"))
    assert result["decision"] == "block"
    assert result["id"] == "core.rm-with-recursive-or-force-flags"
    assert "make clean" in result["reason"] and str(tree / "mk" / "Makefile").lower() in result["reason"].lower()
    assert "core.rm-with-recursive-or-force-flags" in result["reason"]


def test_a_recipe_verdict_is_the_verdict_class_of_the_typed_line(tree, cfg):
    typed = check_command(FORCE_PUSH, cfg)
    in_recipe = check_command("make bad_dep", cfg, cwd=str(tree / "mk"))
    assert (in_recipe["decision"], in_recipe["id"]) == (typed["decision"], typed["id"])


def test_unverifiable_recipes_name_themselves_and_survive_bypass(tree, cfg):
    unk = check_command("make unk", cfg, cwd=str(tree / "mk"))
    assert (unk["decision"], unk["id"], unk.get("unverifiable")) == ("ask", "core.recipe-unverifiable", True)
    workspace = check_command("npm run -w pkg build", cfg, cwd=str(tree / "npm"))
    assert (workspace["id"], workspace.get("unverifiable")) == ("core.recipe-unverifiable", True)
    assert check_command("make all", cfg, cwd=str(tree / "mk")).get("unverifiable") is None


def test_the_size_depth_and_time_budgets_name_themselves(tree, cfg, monkeypatch):
    assert check_command("make all", cfg, cwd=str(tree / "mk_huge"))["id"] == "core.script-too-large"
    assert check_command("make a", cfg, cwd=str(tree / "mk_recurse"))["id"] == "core.script-depth"
    monkeypatch.setattr(engine, "MAX_SCRIPT_SCAN_SECONDS", -1)
    result = check_command("make all", cfg, cwd=str(tree / "mk_clean"))
    assert (result["decision"], result["id"], result.get("unverifiable")) == ("ask", "core.script-budget", True)


def test_an_unreadable_makefile_asks(tree, cfg):
    path = tree / "mk_denied" / "Makefile"
    path.parent.mkdir(exist_ok=True)
    path.write_text(f"clean:\n\t{BAD}\n")
    path.chmod(0)
    try:
        result = check_command("make clean", cfg, cwd=str(path.parent))
    finally:
        path.chmod(0o644)
    assert result["decision"] in ("ask", "block")  # readable when the tests run as root: a block


def test_the_kill_switch_and_disabled_rules_apply_inside_recipes(tree, cfg):
    off = {"safety": {"enabled": False}, "bashToolPatterns": []}
    assert check_command("make clean", off, cwd=str(tree / "mk"))["decision"] == "allow"
    config = dict(cfg, safety={"enabled": True, "disabled_rules": ["core.rm-with-recursive-or-force-flags"]})
    assert check_command("make clean", config, cwd=str(tree / "mk"))["decision"] != "block"


# -- the recipe locators ----------------------------------------------------------------------------------------

def test_invocation_recognizes_only_runs(tmp_path):
    base = (str(tmp_path),)
    runs = {
        "make": ("make", ["clean"]), "npm": ("npm", ["run", "x"]), "just": ("just", ["x"]),
        "pnpm": ("pnpm", ["test"]), "yarn": ("yarn", ["build"]), "bun": ("bun", ["run", "x"]),
    }
    for name, (head, args) in runs.items():
        assert recipefile.invocation(head, args, base) is not None, name
    for head, args in (("npm", ["install"]), ("npm", ["run"]), ("yarn", ["add", "x"]),
                       ("bun", ["test"]), ("just", ["--list"]), ("task", ["x"]), ("ls", ["-la"])):
        assert recipefile.invocation(head, args, base) is None, (head, args)


def test_make_command_line_parsing(tmp_path):
    run = recipefile.invocation("make", ["-j", "4", "-C", "d", "-f", "f.mk", "A=1", "t1", "--", "t2"], (str(tmp_path),))
    assert run.directory == "d" and run.file == "f.mk"
    assert run.overrides == (("A", "1"),)
    assert [c[0] for c in run.calls] == ["t1", "t2"]


def test_a_typical_recipe_stays_inside_the_script_budget(tree, cfg):
    start = time.perf_counter()
    for _ in range(5):
        check_command("make build", cfg, cwd=str(tree / "mk"))
        check_command("npm run build", cfg, cwd=str(tree / "npm"))
        check_command("just build", cfg, cwd=str(tree / "just"))
    assert (time.perf_counter() - start) / 15 < 0.5


def test_reverting_the_recipe_reader_goes_red(tree, cfg, monkeypatch):
    """The mutation check: with no recipe found, no block survives and no verdict comes from a recipe."""
    wanted = [(cwd, c, want) for cwd, c, want in CORPUS if want in ("block", "ask") and c != "rm -rf /"]
    monkeypatch.setattr(recipefile, "locate", lambda run: recipefile.Recipe(recipefile.MISSING))
    reverted = [(c, want, check_command(c, cfg, cwd=str(tree / cwd))) for cwd, c, want in wanted]
    assert [c for c, want, r in reverted if want == "block" and r["decision"] == "block"] == []
    assert [c for c, _, r in reverted if r.get("scriptscan")] == []
    assert sum(want == "block" for _, want, _ in reverted) > 40  # the rows that went red: the reader earns them

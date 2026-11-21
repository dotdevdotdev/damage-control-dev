"""A sed script that runs the ``eval`` builtin, and the regex that finds it staying linear."""

import time

import pytest

from damage_control import engine


@pytest.mark.parametrize("script, executes", [
    ("1e eval x", True),
    ("/p/e eval x", True),
    ("s/a/eval x/e", True),
    ("s!a!eval x!e", True),
    ("s/a\\/b/eval x/e", True),
    ("s/a/eval x/g", False),
    ("p; s/eval/x/", False),
])
def test_sed_scripts_that_run_eval(script, executes):
    assert engine._eval_sed_executes(script) is executes


def test_a_backslash_run_in_an_s_command_does_not_backtrack_exponentially():
    started = time.perf_counter()
    engine._eval_sed_executes("s!" + "\\a" * 40 + " eval")
    assert time.perf_counter() - started < 1

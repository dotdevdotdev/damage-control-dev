"""The per-directory resolver answers exactly what ``os.path.realpath`` + ``os.stat`` answer."""

import os

import pytest

from damage_control import engine


@pytest.fixture
def tree(tmp_path):
    root = str(tmp_path.resolve())
    os.makedirs(f"{root}/d/sub")
    open(f"{root}/d/file", "w").close()
    os.link(f"{root}/d/file", f"{root}/d/hard")
    os.symlink(f"{root}/d", f"{root}/dirlink")
    os.symlink(f"{root}/d/file", f"{root}/d/filelink")
    os.symlink(f"{root}/d/missing", f"{root}/d/dangling")
    os.symlink("loop", f"{root}/loop")
    return root


def _paths(root):
    return [
        f"{root}/d", f"{root}/d/file", f"{root}/d/hard", f"{root}/d/sub", f"{root}/dirlink",
        f"{root}/dirlink/file", f"{root}/dirlink/sub/x", f"{root}/d/filelink", f"{root}/d/dangling",
        f"{root}/loop", f"{root}/loop/x", f"{root}/nope", f"{root}/nope/a/b", f"{root}/d/file/x",
        f"{root}/d/../d/file", f"{root}//d/file", f"{root}/d/./file", "/", "/nonexistent/a/b", "rel/path",
    ]


def test_resolve_matches_realpath_and_stat(tree):
    for path in _paths(tree):
        for memo in (False, True):
            ctx = engine.decision_memo() if memo else None
            if ctx:
                ctx.__enter__()
            try:
                real, st = engine._resolve(path)
            finally:
                if ctx:
                    ctx.__exit__(None, None, None)
            assert real == os.path.realpath(path), path
            try:
                want = os.stat(os.path.realpath(path))
            except OSError:
                want = None
            assert (st is None) == (want is None), path
            if st is not None:
                assert os.path.samestat(st, want), path

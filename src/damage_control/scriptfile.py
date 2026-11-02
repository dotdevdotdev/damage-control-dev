"""Reading a script the shell is about to run: the I/O half of the script-indirection scan.

``read_script(path)`` answers one question for the engine: what text will an interpreter
read from this path, or why can that not be known? It never raises, never blocks on a
special file, and never reads more than ``MAX_SCRIPT_BYTES``. Everything it decides is a
status string; the engine owns what a status means for the verdict.

This is a seatbelt, not a sandbox: the file is read when the hook runs and can change
before the shell runs it (see docs/threat-model.md, "Script indirection").

Standard library only.
"""

import os
import re
import stat
from typing import NamedTuple, Optional

MAX_SCRIPT_BYTES = 256 * 1024  # the same ceiling a typed command gets (engine.MAX_COMMAND_CHARS)
_BINARY_SNIFF_BYTES = 8192
_MAGIC = (b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
          b"\xca\xfe\xba\xbe", b"MZ")
# Kernel and device trees: reading one can block or never end.
_NO_FOLLOW_PREFIXES = ("/dev/", "/proc/", "/sys/")

OK = "ok"
MISSING = "missing"
UNREADABLE = "unreadable"
SPECIAL = "special"  # a directory, device, FIFO or socket: nothing to read, nothing a shell would parse
BINARY = "binary"
TOO_LARGE = "too-large"


class ScriptFile(NamedTuple):
    status: str
    real: str  # realpath of the file ("" when it could not be resolved)
    text: str = ""
    why: str = ""


def read_script(path: str) -> ScriptFile:
    """The text at ``path`` (symlinks resolved), or a status saying why there is none."""
    try:
        real = os.path.realpath(path)
    except (OSError, ValueError) as e:
        return ScriptFile(UNREADABLE, "", why=type(e).__name__)
    if real in ("/dev", "/proc", "/sys") or real.startswith(_NO_FOLLOW_PREFIXES):
        return ScriptFile(SPECIAL, real)
    try:
        mode = os.stat(real).st_mode
    except (FileNotFoundError, NotADirectoryError):
        return ScriptFile(MISSING, real)
    except (OSError, ValueError) as e:  # a symlink loop, EACCES on a parent
        return ScriptFile(UNREADABLE, real, why=getattr(e, "strerror", None) or type(e).__name__)
    if not stat.S_ISREG(mode):
        return ScriptFile(SPECIAL, real)
    try:
        fd = os.open(real, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
    except OSError as e:
        return ScriptFile(UNREADABLE, real, why=e.strerror or type(e).__name__)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):  # swapped for a device between stat and open
            return ScriptFile(SPECIAL, real)
        data = os.read(fd, MAX_SCRIPT_BYTES + 1)
        while 0 < len(data) <= MAX_SCRIPT_BYTES:
            more = os.read(fd, MAX_SCRIPT_BYTES + 1 - len(data))
            if not more:
                break
            data += more
    except OSError as e:
        return ScriptFile(UNREADABLE, real, why=e.strerror or type(e).__name__)
    finally:
        os.close(fd)
    if data.startswith(_MAGIC) or b"\0" in data[:_BINARY_SNIFF_BYTES]:
        return ScriptFile(BINARY, real)  # before the size check: system binaries are large and are not scripts
    if len(data) > MAX_SCRIPT_BYTES:
        return ScriptFile(TOO_LARGE, real, why=f"over {MAX_SCRIPT_BYTES:,} bytes")
    return ScriptFile(OK, real, data.decode("utf-8", "replace"))


_INTERPRETER_LANGS = (
    (re.compile(r"(?:ba|z|k|da|a)?sh"), "shell"),
    (re.compile(r"pypy\d*(?:\.\d+)*|python\d*(?:\.\d+)*"), "python"),
    (re.compile(r"node(?:js)?|bun|deno"), "node"),
    (re.compile(r"perl\d*(?:\.\d+)*"), "perl"),
    (re.compile(r"ruby\d*(?:\.\d+)*"), "ruby"),
)

_EXTENSION_LANGS = {
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".ksh": "shell",
    ".py": "python", ".js": "node", ".mjs": "node", ".cjs": "node",
    ".pl": "perl", ".rb": "ruby", ".ipynb": "notebook",
}


def language_of(interpreter: str) -> Optional[str]:
    """``shell | python | node | perl | ruby`` for an interpreter's name or path, else None."""
    name = os.path.basename(interpreter)
    for rx, lang in _INTERPRETER_LANGS:
        if rx.fullmatch(name):
            return lang
    return None


def shebang_language(text: str) -> Optional[str]:
    """The language a ``#!`` line names (``/usr/bin/env -S python3 -u`` too); None for none or an unknown one."""
    if not text.startswith("#!"):
        return None
    words = text[2:].split("\n", 1)[0].split()
    if words and os.path.basename(words[0]) == "env":
        words = [w for w in words[1:] if not w.startswith("-") and "=" not in w]
    return language_of(words[0]) if words else None


def extension_language(path: str) -> Optional[str]:
    return _EXTENSION_LANGS.get(os.path.splitext(path)[1].lower())

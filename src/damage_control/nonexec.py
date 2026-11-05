"""Interpreter flags after which a file operand is data, not a program.

Script indirection reads a file only when the command runs it. ``node --check x`` parses the file and
runs nothing, ``python3 --version x`` prints a version and exits, ``bash -n x`` only reports syntax: the
operand that follows such a flag is an argument, so the scan does not read the file as a script.

``runs_no_program(lang, word)`` is asked once per option word, in order, while the engine walks an
interpreter's leading options. Standard library only.
"""

_NO_PROGRAM = {
    "shell": frozenset({"--version", "--help"}),
    "python": frozenset({"-V", "-VV", "--version", "-h", "--help", "-?"}),
    "node": frozenset({"-v", "--version", "-h", "--help", "-c", "--check", "--v8-options"}),
    "perl": frozenset({"-v", "-V", "-h", "--help", "--version"}),
    "ruby": frozenset({"--version", "-h", "--help", "-c"}),
}
# Flags that carry their program or query in the same word (``--eval=1``): the next operand is an argument.
_ATTACHED_PROGRAM = {"node": ("--eval=", "--print="), "perl": ("-V:",)}


def runs_no_program(lang: str, word: str) -> bool:
    """True when ``word``, an option of an interpreter in ``lang``, means no file is run."""
    if word in _NO_PROGRAM.get(lang, ()):
        return True
    if word.startswith(_ATTACHED_PROGRAM.get(lang, ())):
        return True
    # ``bash -n`` / ``sh -en``: read for syntax, never executed
    return lang == "shell" and len(word) > 1 and word[0] == "-" and word[1:].isalpha() and "n" in word

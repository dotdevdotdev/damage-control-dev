"""The Claude Code hook entry: ``python -I -m damage_control.hook <kind> [--profile PATH]``.

This file is the bootstrap wrapper, and it imports nothing but ``os`` and ``sys`` at module
level. Python exits 1 when an import fails or an exception escapes, and Claude Code treats
exit 1 as "no decision" (the tool call RUNS). The only exit that stops a call is 2, so every
way this process can fail before the real hook is running is caught here and turned into 2:
an unimportable engine, a half-upgraded install, a syntax error in a rules module.

What it cannot catch is a failure BEFORE this file runs (no interpreter, no ``damage_control``
package). That is what ``"onFailure": "block"`` in the registration is for.

``-I`` is mandatory, not a tidy-up: ``python -m`` puts the working directory first on
``sys.path``, and that tree is writable by the agent being policed, so a planted ``json.py``
would be imported as the hook's own ``json``. ``-I`` also drops ``PYTHON*`` variables and the
user site directory.
"""

import os
import sys


# The hand-back hook runs on every prompt Claude Code submits, and an exit 2 there erases the user's
# prompt, so it is the one kind that fails open and never loads the engine.
APPROVAL_KIND = "approval"


def _is_approval(argv) -> bool:
    return list(argv[:1]) == [APPROVAL_KIND]


def _block(reason: str) -> None:
    """Exit 2 whatever state stderr is in (0 for the hand-back hook, which must never stop a prompt)."""
    if _is_approval(sys.argv[1:]):
        os._exit(0)
    try:
        sys.stderr.write(f"SECURITY: Blocked: damage-control hook could not start ({reason}) — failing closed\n")
        sys.stderr.flush()
    finally:
        os._exit(2)


def _excepthook(exc_type, exc, tb) -> None:
    try:
        import traceback

        traceback.print_exception(exc_type, exc, tb)
    except BaseException:
        pass
    _block(f"{exc_type.__name__}: {exc}")


sys.excepthook = _excepthook


def main(argv) -> None:
    if _is_approval(argv):
        from damage_control import handback

        sys.stdout.write(handback.run(sys.stdin.read(1_000_000)))
        sys.stdout.flush()
        return
    try:
        from damage_control.adapter import run_hook
    except BaseException as e:  # SystemExit and KeyboardInterrupt included: nothing may exit 0 or 1 here
        _block(f"import failed: {type(e).__name__}: {e}")
        return
    run_hook(argv)


if __name__ == "__main__":
    main(sys.argv[1:])

"""Quoted text a command only prints or sends is data, not a path the command touches.

``echo "see ~/.ssh/id_rsa"`` and ``notifier send "moved ~/.ssh/id_rsa"`` name a path in
prose; the verb prints or sends the string and opens nothing. The zero-access mention rule reads
every spelling of a guarded path anywhere in the command, so it needs this text out of the way —
the way :func:`damage_control.engine.mask_prose_operands` already does for ``git commit -m`` and
``gh pr create --body``.

The decision is by what the verb does with its arguments, never by how the argument is spelled:

* ``echo`` / ``printf`` print every quoted argument. Never masked when the command pipes, groups,
  or substitutes — the text could then become another command's operand (``| xargs cat``).
* The profile's ``message_commands`` send their quoted positional text. The
  value of ``--body-file`` is a path the command reads, so it stays visible.
* A heredoc body feeding ``cat`` / ``tee`` / a git or gh message verb is written or printed text.
  A body feeding a shell, an interpreter or a pipe stays visible.

A command holding any substitution is left whole: the text could then run.

Redirect targets, operands of any other verb and quoted paths given to ``cat`` are never touched.
"""

import os
import re
from typing import List, Tuple

PLACEHOLDER = '"DATA"'
_PRINTERS = {"echo", "printf"}
_PATH_FLAGS = {"--body-file"}
_HEREDOC_WRITERS = {"cat", "tee"}
_SUBSTITUTION_RE = re.compile(r"\$\(|`|<\(|>\(")
_MARKER_SEGMENT_END_RE = re.compile(r"[;&|\n(`]")


def _is_message_command(texts: List[str]) -> bool:
    """A command the profile names as one that sends its quoted positional text (``Profile.message_commands``)."""
    from . import engine

    head = os.path.basename(texts[0])
    return any(len(argv) <= len(texts) and head == argv[0] and tuple(texts[1:len(argv)]) == argv[1:]
               for argv in engine.PROFILE.message_commands)


def _quoted_argument_spans(command: str) -> List[Tuple[int, int]]:
    """Spans of quoted words that are plain printed or sent text."""
    from . import engine

    tokens = engine._prose_tokens(command)
    if not tokens:
        return []
    raws = [t[2] for t in tokens]
    if "|" in raws or "(" in raws or ")" in raws or "{" in raws:
        return []
    spans: List[Tuple[int, int]] = []
    seg: List[Tuple[int, int, str]] = []

    def _flush() -> None:
        words: List[Tuple[int, int, str]] = []
        after_redirect = False
        for t in seg:
            if t[2] in (">", "<"):
                after_redirect = True
            elif after_redirect:
                after_redirect = False
            else:
                words.append(t)
        if not words:
            return
        texts = [w[2] for w in words]
        printer = os.path.basename(texts[0]) in _PRINTERS
        if not printer and not _is_message_command(texts):
            return
        for k, (s, e, raw) in enumerate(words):
            if k == 0 or not engine._pure_quoted_value(raw):
                continue
            if not printer and texts[k - 1] in _PATH_FLAGS:
                continue
            spans.append((s, e))

    for tok in tokens:
        if tok[2] in (";", "&", "\n"):
            _flush()
            seg = []
        else:
            seg.append(tok)
    _flush()
    return spans


def _data_heredocs(command: str) -> List[Tuple[int, int]]:
    """``(body_start, body_end)`` of each heredoc whose body is only written or printed."""
    from . import engine

    spans: List[Tuple[int, int]] = []
    for h in engine._heredocs(command):
        marker_line = command[h.start : h.body_start]
        if "|" in marker_line:
            continue
        words = _MARKER_SEGMENT_END_RE.split(command[: h.start])[-1].split()
        if not words:
            continue
        head = os.path.basename(words[0])
        if head in _HEREDOC_WRITERS or _takes_message(head, words):
            spans.append((h.body_start, h.body_end))
    return spans


def _takes_message(head: str, words: List[str]) -> bool:
    from . import engine

    if head == "git":
        return any(t in ("commit", "tag") for t in words[1:4])
    return (
        head == "gh"
        and len(words) > 2
        and words[1] in engine._GH_PROSE_GROUPS
        and words[2] in engine._GH_PROSE_VERBS
    )


def mask_data_operands(command: str) -> str:
    """``command`` with printed, sent and written text replaced by an inert placeholder.

    Returns ``command`` unchanged when it holds a substitution (the text may then run) or when
    nothing qualifies.
    """
    if _SUBSTITUTION_RE.search(command):
        return command
    quoted = [(s, e, PLACEHOLDER) for s, e in _quoted_argument_spans(command)]
    bodies = [(s, e, "DATA\n") for s, e in _data_heredocs(command)] if "<<" in command else []
    edits = sorted(quoted + bodies)
    if not edits:
        return command
    out: List[str] = []
    pos = 0
    for s, e, text in edits:
        if s < pos:
            continue
        out.append(command[pos:s])
        out.append(text)
        pos = e
    out.append(command[pos:])
    return "".join(out)

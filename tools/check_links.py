#!/usr/bin/env python3
"""Fail if a relative link in the repository's Markdown files does not resolve.

Checks ``[text](target)`` links in README.md, SECURITY.md, CONTRIBUTING.md and docs/*.md:
the target file must exist, and a ``#fragment`` must match a heading in that file (GitHub's
slug rules) or an explicit ``<a id=...>``. External ``http(s)``/``mailto`` links are not fetched.

    check_links.py        # exit 1 and list every broken link
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Set

ROOT = Path(__file__).resolve().parent.parent
LINK_RE = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
ANCHOR_RE = re.compile(r'<a\s+(?:id|name)="([^"]+)"')


def slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, drop punctuation except ``-`` and ``_``, spaces to ``-``."""
    text = re.sub(r"`", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> Set[str]:
    found: Set[str] = set()
    counts: dict = {}
    in_fence = False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(line)
        if m:
            base = slug(m.group(2))
            n = counts.get(base, 0)
            counts[base] = n + 1
            found.add(base if n == 0 else f"{base}-{n}")
        found.update(ANCHOR_RE.findall(line))
    return found


def markdown_files() -> List[Path]:
    return sorted([*ROOT.glob("*.md"), *ROOT.glob("docs/*.md")])


def check(path: Path) -> List[str]:
    problems: List[str] = []
    in_fence = False
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for target in LINK_RE.findall(line):
            if re.match(r"[a-z][a-z0-9+.-]*:", target):
                continue
            name, _, fragment = target.partition("#")
            dest = (path.parent / name).resolve() if name else path
            where = f"{path.relative_to(ROOT)}:{number}"
            if not dest.exists():
                problems.append(f"{where}: {target}: no such file")
            elif fragment and dest.suffix == ".md" and fragment not in anchors(dest):
                problems.append(f"{where}: {target}: no heading '#{fragment}' in {dest.relative_to(ROOT)}")
    return problems


def main() -> int:
    problems = [p for f in markdown_files() for p in check(f)]
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

"""Heading-TOC and anchored-section extraction.

Section-span semantics are adapted from gx-linear-skills' binding_slicer: a section
spans from its heading line through the line before the next heading of equal or higher
level, or to end of file.
"""

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_ANCHOR_RE = re.compile(r"\s*\{#([A-Za-z0-9][A-Za-z0-9_-]*)\}\s*")


@dataclass(frozen=True, slots=True)
class Heading:
    """One markdown heading. ``line`` is 1-indexed. ``text`` keeps the anchor marker."""

    level: int
    text: str
    anchor: str | None
    line: int


def build_toc(body: str) -> list[Heading]:
    """Return all ATX headings in ``body`` in document order.

    Args:
        body: Markdown document text.

    Returns:
        A list of Heading, each with its level, text, optional ``{#anchor}`` id, and
        1-indexed line number.
    """
    headings: list[Heading] = []
    for i, line in enumerate(body.splitlines(), start=1):
        match = _HEADING_RE.match(line)
        if match is None:
            continue
        level = len(match.group(1))
        raw_text = match.group(2)
        anchor_match = _ANCHOR_RE.search(raw_text)
        anchor = anchor_match.group(1) if anchor_match else None
        headings.append(Heading(level=level, text=raw_text, anchor=anchor, line=i))
    return headings


def section_span(headings: list[Heading], idx: int, total_lines: int) -> tuple[int, int]:
    """Return the inclusive 1-indexed line range for ``headings[idx]``.

    Args:
        headings: The document TOC from ``build_toc``.
        idx: Index into ``headings`` of the section of interest.
        total_lines: Total line count of the document.

    Returns:
        ``(start, end)`` from the heading line through the line before the next heading
        of equal or higher level, or to ``total_lines``.
    """
    head = headings[idx]
    end = total_lines
    for nxt in headings[idx + 1 :]:
        if nxt.level <= head.level:
            end = nxt.line - 1
            break
    return (head.line, end)


def section_text(body: str, span: tuple[int, int]) -> str:
    """Return the text of a section span with the heading's ``{#anchor}`` marker removed.

    Args:
        body: Markdown document text.
        span: Inclusive 1-indexed ``(start, end)`` line range.

    Returns:
        The joined lines of the span, with the anchor marker stripped from the first
        (heading) line.
    """
    lines = body.splitlines()
    start, end = span
    chunk = lines[start - 1 : end]
    if chunk:
        chunk[0] = _ANCHOR_RE.sub(" ", chunk[0]).rstrip()
    return "\n".join(chunk)

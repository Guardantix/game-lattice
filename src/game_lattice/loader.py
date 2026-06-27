"""Assemble parsed docs into a Lattice. Pure: no filesystem access."""

from collections import defaultdict

from .error_types import DuplicateIdError
from .model import Edge, Lattice, Location, Node, ParsedDoc
from .resolve import split_ref
from .sections import Heading, build_toc, section_span


def build_lattice(docs: list[ParsedDoc]) -> Lattice:
    """Build the lattice from parsed docs.

    Args:
        docs: Tracked files with validated frontmatter and bodies.

    Returns:
        A Lattice with the id index, nodes, reverse adjacency, and ancestor map.

    Raises:
        DuplicateIdError: If any two ids (file or anchor) collide.
    """
    index: dict[str, Location] = {}
    sources: dict[str, str] = {}
    ancestors: dict[str, tuple[str, ...]] = {}

    for doc in docs:
        _register(
            doc.meta.id,
            Location(path=doc.path, kind="file", span=(1, _line_count(doc.body))),
            index,
            sources,
            f"file {doc.path}",
        )
        toc = build_toc(doc.body)
        total = _line_count(doc.body)
        anchored = [(i, h) for i, h in enumerate(toc) if h.anchor is not None]
        spans: dict[str, tuple[int, int]] = {}
        for i, head in anchored:
            anchor = head.anchor
            if anchor is None:
                continue
            span = section_span(toc, i, total)
            spans[anchor] = span
            _register(
                anchor,
                Location(path=doc.path, kind="section", span=span),
                index,
                sources,
                f"anchor in {doc.path}",
            )
        _record_ancestors(anchored, spans, ancestors)

    nodes: dict[str, Node] = {}
    dependents: defaultdict[str, set[str]] = defaultdict(set)
    for doc in docs:
        edges: list[Edge] = []
        for raw in doc.meta.derives_from:
            tid = split_ref(raw.ref)
            target_id = tid if tid in index else None
            edges.append(Edge(target_ref=raw.ref, target_id=target_id, seen=raw.seen))
            if target_id is not None:
                dependents[target_id].add(doc.meta.id)
        nodes[doc.meta.id] = Node(
            id=doc.meta.id,
            title=doc.meta.title,
            layer=doc.meta.layer,
            authority=doc.meta.authority,
            path=doc.path,
            body=doc.body,
            derives_from=tuple(edges),
            tickets=tuple(doc.meta.tickets),
        )

    return Lattice(
        nodes_by_id=nodes,
        index=index,
        dependents={k: frozenset(v) for k, v in dependents.items()},
        ancestors=ancestors,
    )


def _line_count(body: str) -> int:
    return max(1, len(body.splitlines()))


def _register(
    id_: str,
    location: Location,
    index: dict[str, Location],
    sources: dict[str, str],
    where: str,
) -> None:
    if id_ in index:
        msg = f"duplicate id {id_!r}: already registered at {sources[id_]}, again at {where}"
        raise DuplicateIdError(msg)
    index[id_] = location
    sources[id_] = where


def _record_ancestors(
    anchored: list[tuple[int, Heading]],
    spans: dict[str, tuple[int, int]],
    ancestors: dict[str, tuple[str, ...]],
) -> None:
    for _, head in anchored:
        anchor = head.anchor
        if anchor is None:
            continue
        start, end = spans[anchor]
        containing: list[tuple[tuple[int, int], str]] = []
        for _, other in anchored:
            oid = other.anchor
            if oid is None or oid == anchor:
                continue
            ostart, oend = spans[oid]
            if (ostart < start and oend >= end) or (ostart <= start and oend > end):
                containing.append(((ostart, oend), oid))
        containing.sort(key=lambda item: item[0][1] - item[0][0], reverse=True)
        ancestors[anchor] = tuple(oid for _, oid in containing)

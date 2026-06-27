"""Reverse-walk the lattice to find every doc affected by a change to a target."""

from pathlib import Path

from .model import Lattice, Node
from .resolve import split_ref


def expand_targets(lattice: Lattice, token: str) -> set[str]:
    """Expand an impact token into the full set of target ids it touches.

    Args:
        lattice: The built lattice.
        token: A bare id or ``namespace#id`` ref naming a file or section anchor.

    Returns:
        For a file id: the id plus all section anchors in its file. For a section
        anchor: the anchor plus its anchored ancestors. Empty if the id is unknown.
    """
    target_id = split_ref(token)
    location = lattice.index.get(target_id)
    if location is None:
        return set()
    if location.kind == "file":
        return {target_id} | _anchors_in_file(lattice, location.path)
    return {target_id} | set(lattice.ancestors.get(target_id, ()))


def impact(lattice: Lattice, token: str) -> list[Node]:
    """Return every downstream node affected by a change to ``token``.

    Args:
        lattice: The built lattice.
        token: A bare id or ``namespace#id`` ref.

    Returns:
        Affected nodes, sorted by id, walking ``dependents`` transitively.
    """
    queue = list(expand_targets(lattice, token))
    visited_targets: set[str] = set()
    affected: set[str] = set()
    while queue:
        current = queue.pop()
        if current in visited_targets:
            continue
        visited_targets.add(current)
        for source_id in lattice.dependents.get(current, frozenset()):
            if source_id in affected:
                continue
            affected.add(source_id)
            queue.append(source_id)
            node = lattice.nodes_by_id.get(source_id)
            if node is not None:
                queue.extend(_anchors_in_file(lattice, node.path))
    return [lattice.nodes_by_id[i] for i in sorted(affected)]


def _anchors_in_file(lattice: Lattice, path: Path) -> set[str]:
    return {
        anchor
        for anchor, loc in lattice.index.items()
        if loc.kind == "section" and loc.path == path
    }

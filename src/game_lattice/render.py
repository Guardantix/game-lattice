"""Render the lattice as Mermaid or DOT."""

from .model import Lattice


def _label(lattice: Lattice, node_id: str) -> str:
    node = lattice.nodes_by_id.get(node_id)
    title = node.title if node is not None and node.title else node_id
    return title.replace('"', "'")


def to_mermaid(lattice: Lattice, stale_edges: set[tuple[str, str]]) -> str:
    """Render a Mermaid ``graph TD``.

    Args:
        lattice: The built lattice.
        stale_edges: ``(source_id, target_id)`` pairs to draw with a dashed arrow.

    Returns:
        Mermaid source. Edges run upstream (target) to downstream (source).
    """
    lines = ["graph TD"]
    for node_id in sorted(lattice.nodes_by_id):
        lines.append(f'    {node_id}["{_label(lattice, node_id)}"]')
    for node_id in sorted(lattice.nodes_by_id):
        for edge in lattice.nodes_by_id[node_id].derives_from:
            if edge.target_id is None:
                continue
            arrow = "-.->" if (node_id, edge.target_id) in stale_edges else "-->"
            lines.append(f"    {edge.target_id} {arrow} {node_id}")
    return "\n".join(lines) + "\n"


def to_dot(lattice: Lattice, stale_edges: set[tuple[str, str]]) -> str:
    """Render a Graphviz DOT digraph.

    Args:
        lattice: The built lattice.
        stale_edges: ``(source_id, target_id)`` pairs to draw dashed.

    Returns:
        DOT source. Edges run upstream (target) to downstream (source).
    """
    lines = ["digraph lattice {"]
    for node_id in sorted(lattice.nodes_by_id):
        lines.append(f'    "{node_id}" [label="{_label(lattice, node_id)}"];')
    for node_id in sorted(lattice.nodes_by_id):
        for edge in lattice.nodes_by_id[node_id].derives_from:
            if edge.target_id is None:
                continue
            style = " [style=dashed]" if (node_id, edge.target_id) in stale_edges else ""
            lines.append(f'    "{edge.target_id}" -> "{node_id}"{style};')
    lines.append("}")
    return "\n".join(lines) + "\n"

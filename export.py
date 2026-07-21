from __future__ import annotations

import hashlib
import json
import re

import networkx as nx


def _sanitize_identifier(name: str) -> str:
    """Turn an arbitrary node name into a valid Mermaid/DOT identifier.

    Every non-alphanumeric character collapses to "_", which is lossy:
    two genuinely different names (e.g. "pkg.a_b" and "pkg.a.b") can
    produce the identical sanitized string, silently merging two unrelated
    nodes into one in the rendered diagram. A short hash of the original
    (pre-sanitized) name is appended so every distinct node name always
    gets a distinct identifier, regardless of what characters it contains.
    """
    sanitized = re.sub(r"[^0-9A-Za-z_]", "_", name) or "node"
    suffix = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    return f"{sanitized}_{suffix}"


def _escape_label(label: str) -> str:
    return label.replace('"', '\\"')


def to_mermaid(graph: nx.DiGraph) -> str:
    lines = ["flowchart TD"]
    for node in sorted(graph.nodes):
        node_id = _sanitize_identifier(str(node))
        lines.append(f'    {node_id}["{_escape_label(str(node))}"]')

    for source, target, data in sorted(graph.edges(data=True)):
        source_id = _sanitize_identifier(str(source))
        target_id = _sanitize_identifier(str(target))
        if data.get("confidence") == "resolved":
            lines.append(f"    {source_id} --> {target_id}")
        else:
            lines.append(f"    {source_id} -.-> {target_id}")

    return "\n".join(lines) + "\n"


def to_dot(graph: nx.DiGraph) -> str:
    lines = ["digraph G {"]
    for node in sorted(graph.nodes):
        node_id = _sanitize_identifier(str(node))
        lines.append(f'    {node_id} [label="{_escape_label(str(node))}"];')

    for source, target, data in sorted(graph.edges(data=True)):
        source_id = _sanitize_identifier(str(source))
        target_id = _sanitize_identifier(str(target))
        if data.get("confidence") == "resolved":
            lines.append(
                f'    {source_id} -> {target_id} [color="#1f77b4", style="solid"];'
            )
        else:
            lines.append(
                f'    {source_id} -> {target_id} [color="#d62728", style="dashed"];'
            )

    lines.append("}")
    return "\n".join(lines) + "\n"


def to_json(graph: nx.DiGraph) -> str:
    nodes = [{"id": str(node), "label": str(node)} for node in sorted(graph.nodes)]
    edges = [
        {
            "source": str(source),
            "target": str(target),
            "confidence": str(data.get("confidence", "unresolved")),
        }
        for source, target, data in sorted(graph.edges(data=True))
    ]
    return json.dumps({"nodes": nodes, "edges": edges}, indent=2) + "\n"

from __future__ import annotations

import json
import re

import networkx as nx


def _sanitize_identifier(name: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z_]", "_", name)
    return sanitized or "node"


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

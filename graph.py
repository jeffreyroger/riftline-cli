"""
Graph layer: scans a whole package, chains every file's resolution together,
and builds the dependency graph the rest of the tool queries.
"""
from __future__ import annotations

from pathlib import Path

import networkx as nx

from .parser import parse
from .resolver import module_name_for_file, resolve_calls_for_file, build_class_method_table


def find_python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def build_graph(root: Path) -> nx.DiGraph:
    files = find_python_files(root)

    # Pass 1: parse every file, compute its module name and symbol table.
    parsed_by_module: dict[str, tuple[Path, object]] = {}
    for path in files:
        module = module_name_for_file(root, path)
        parsed_by_module[module] = (path, parse(path))

    all_symbols = {mod: parsed.symbols for mod, (_, parsed) in parsed_by_module.items()}
    all_parsed_files = [parsed for _, parsed in parsed_by_module.values()]
    class_method_table = build_class_method_table(all_parsed_files, root=root)

    # Pass 2: resolve every call in every file against every other file's
    # symbol table, and add each result as a graph edge.
    graph = nx.DiGraph()
    for module, (path, parsed) in parsed_by_module.items():
        for fn in parsed.functions:
            graph.add_node(
                f"{module}.{fn.name}", file=str(path), lineno=fn.lineno, end_lineno=fn.end_lineno
            )

        for call in resolve_calls_for_file(parsed, module, all_symbols, class_method_table):
            graph.add_edge(call.caller, call.callee, confidence=call.confidence)

    return graph


def blast_radius(graph: nx.DiGraph, target: str) -> set[str]:
    """Everyone who depends on `target`, directly or transitively."""
    if target not in graph:
        raise KeyError(
            f"'{target}' not found in graph. Run 'riftline scan' first or check the symbol name."
        )
    return nx.ancestors(graph, target)


def function_at_line(graph: nx.DiGraph, file: str, lineno: int) -> str | None:
    """Given a changed line number, find the function whose span contains it
    (used for git-diff-driven impact analysis, Week 2+)."""
    for node, data in graph.nodes(data=True):
        if data.get("file") == file and data.get("lineno", -1) <= lineno <= data.get("end_lineno", -1):
            return node
    return None


def real_nodes(graph: nx.DiGraph) -> list[str]:
    """Nodes that are actual defined functions -- excludes 'unknown:x' stubs,
    which exist only as edge targets for unresolved calls, never as
    something you'd query the blast radius *of*."""
    return [n for n in graph.nodes if not n.startswith("unknown:")]


def hotspots(graph: nx.DiGraph, limit: int | None = None) -> list[tuple[str, int]]:
    """Rank every real function by the size of its blast radius, descending.
    This is the 'general scan' -- no symbol name needed. The top of this
    list is exactly the set of functions where a 'small' change is most
    likely to silently break something far away.
    """
    ranked = [(node, len(nx.ancestors(graph, node))) for node in real_nodes(graph)]
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    if limit is not None:
        ranked = ranked[:limit]
    return ranked


def find_symbol(graph: nx.DiGraph, query: str) -> list[str]:
    """Fuzzy-match a partial or short name against every real node's fully
    qualified name, so you don't have to know/type the exact dotted path.

    Match rules, in order of preference:
      1. Exact match (e.g. you did paste the full FQN) -> that one node.
      2. Suffix match on '.<query>' (e.g. "square" matches
         "synthetic_pkg.core.math_ops.square") -> all such matches.
      3. Substring match anywhere in the FQN -> all such matches, as a
         last-resort fallback.
    Returns a list so the caller can decide: 0 -> not found, 1 -> use it
    directly, 2+ -> ask the user to disambiguate.
    """
    nodes = real_nodes(graph)
    if query in nodes:
        return [query]

    suffix_matches = [n for n in nodes if n == query or n.endswith(f".{query}")]
    if suffix_matches:
        return suffix_matches

    substring_matches = [n for n in nodes if query in n]
    return substring_matches

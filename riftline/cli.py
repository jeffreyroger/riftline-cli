"""
riftline: a CLI that shows the blast radius of a code change before you make it.

NOTE: built with argparse (stdlib) instead of Typer/Rich, since this sandbox
has no network access to pip install them. The command surface below (scan /
hotspots / impact / diff) matches the SRS's intent -- swapping the CLI
framework later only touches this file.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .graph import build_graph, blast_radius, hotspots, find_symbol, find_python_files


def _validated_root(path_str: str) -> Path:
    """Resolve a path and fail loudly if it's wrong, instead of silently
    scanning nothing. This is the fix for the confusing 'No functions
    found' with no explanation that used to happen on a bad path."""
    root = Path(path_str).resolve()
    if not root.exists():
        print(f"Error: path does not exist: {root}")
        print("Check for a typo, or run 'dir' (Windows) / 'ls' (Mac/Linux) to see what's actually there.")
        raise SystemExit(1)
    if not root.is_dir():
        print(f"Error: not a directory: {root}")
        raise SystemExit(1)
    py_files = find_python_files(root)
    if not py_files:
        print(f"Error: no .py files found under: {root}")
        print("Check the path points at the folder that actually contains the code "
              "(e.g. the folder with __init__.py / .py files in it, not its parent).")
        raise SystemExit(1)
    return root


def cmd_scan(args: argparse.Namespace) -> None:
    root = _validated_root(args.path)
    graph = build_graph(root)
    resolved = sum(1 for _, _, d in graph.edges(data=True) if d.get("confidence") == "resolved")
    unresolved = sum(1 for _, _, d in graph.edges(data=True) if d.get("confidence") == "unresolved")
    print(f"Scanned: {root}")
    print(f"  functions found : {graph.number_of_nodes()}")
    print(f"  edges resolved  : {resolved}")
    print(f"  edges unresolved: {unresolved}  (flagged, not guessed)")


def cmd_hotspots(args: argparse.Namespace) -> None:
    """The general, no-symbol-needed scan: rank every function by blast-radius
    size so you can see your riskiest chokepoints without knowing any names."""
    root = _validated_root(args.path)
    graph = build_graph(root)
    ranked = hotspots(graph, limit=args.limit)

    if not ranked:
        print("No functions found.")
        return

    print(f"Top {len(ranked)} riskiest functions in {root} (by blast-radius size):")
    width = max(len(name) for name, _ in ranked)
    for name, count in ranked:
        if count == 0:
            continue
        print(f"  {name.ljust(width)}   {count} dependent(s)")


def _resolve_symbol_or_exit(graph, query: str) -> str:
    matches = find_symbol(graph, query)
    if not matches:
        print(f"Error: no function matching '{query}' was found in the scanned code.")
        raise SystemExit(1)
    if len(matches) > 1:
        print(f"'{query}' is ambiguous -- {len(matches)} functions match:")
        for m in sorted(matches):
            print(f"  - {m}")
        print("Re-run with one of the full names above.")
        raise SystemExit(1)
    return matches[0]


def cmd_impact(args: argparse.Namespace) -> None:
    root = _validated_root(args.path)
    graph = build_graph(root)

    symbol = _resolve_symbol_or_exit(graph, args.symbol)
    if symbol != args.symbol:
        print(f"(matched '{args.symbol}' -> {symbol})")

    affected = blast_radius(graph, symbol)
    if not affected:
        print(f"No known dependents of {symbol}. Safe to change in isolation.")
        return

    print(f"Blast radius of {symbol}:")
    for name in sorted(affected):
        print(f"  - {name}")


def cmd_diff(args: argparse.Namespace) -> None:
    print("Not implemented yet -- planned for Week 2 (git integration).")
    print("For now, use: riftline hotspots   (no name needed)")
    print("          or: riftline impact <name or partial name>")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="riftline", description="Know what breaks before you break it."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Parse a package and print a graph summary.")
    p_scan.add_argument("path", nargs="?", default=".", help="Root of the package to scan.")
    p_scan.set_defaults(func=cmd_scan)

    p_hotspots = sub.add_parser(
        "hotspots", help="Rank every function by blast-radius size. No symbol name needed."
    )
    p_hotspots.add_argument("path", nargs="?", default=".", help="Root of the package to scan.")
    p_hotspots.add_argument("--limit", type=int, default=15, help="Show top N (default 15).")
    p_hotspots.set_defaults(func=cmd_hotspots)

    p_impact = sub.add_parser("impact", help="Show what breaks if SYMBOL changes.")
    p_impact.add_argument(
        "symbol",
        help="Function name -- full dotted path, or just the short name "
        "(e.g. 'square' or 'mypkg.core.square'). Short names auto-resolve "
        "if unambiguous.",
    )
    p_impact.add_argument("--path", default=".", help="Root of the package to scan.")
    p_impact.set_defaults(func=cmd_impact)

    p_diff = sub.add_parser("diff", help="Compute impact from a git diff (Week 2+).")
    p_diff.set_defaults(func=cmd_diff)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

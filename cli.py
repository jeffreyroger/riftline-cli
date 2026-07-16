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
from .parser import clear_parse_failures, get_parse_failures
from .export import to_dot, to_json, to_mermaid
from .testmapper import suggest_test_file


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


def _print_test_suggestions(file_paths: list) -> None:
    """Additive, clearly-labeled section -- never blended into the graph-edge
    output above it. suggest_test_file() is a naming-convention heuristic,
    not a resolved fact (SRS 1.4), so this always prints under its own
    explicit "unverified" heading rather than reusing the blast-radius
    list format."""
    print()
    print("Possible related tests (unverified, naming-convention only):")
    found_any = False
    for path in sorted(set(file_paths)):
        suggestion = suggest_test_file(path)
        if suggestion:
            print(f"  - {path} -> {suggestion}")
            found_any = True
    if not found_any:
        print("  - no matching test file found")


def _print_parse_failures(failures: list) -> None:
    if not failures:
        return
    print(f"{len(failures)} file(s) failed to parse:")
    for failure in failures:
        location = f"{failure.path}"
        if failure.line is not None:
            location = f"{location}:{failure.line}"
        print(f"  - {location}: {failure.message}")


def cmd_scan(args: argparse.Namespace) -> None:
    clear_parse_failures()
    root = _validated_root(args.path)
    graph = build_graph(root)
    failures = get_parse_failures()
    resolved = sum(1 for _, _, d in graph.edges(data=True) if d.get("confidence") == "resolved")
    unresolved = sum(1 for _, _, d in graph.edges(data=True) if d.get("confidence") == "unresolved")
    print(f"Scanned: {root}")
    print(f"  functions found : {graph.number_of_nodes()}")
    print(f"  edges resolved  : {resolved}")
    print(f"  edges unresolved: {unresolved}  (flagged, not guessed)")
    _print_parse_failures(failures)


def cmd_hotspots(args: argparse.Namespace) -> None:
    """The general, no-symbol-needed scan: rank every function by blast-radius
    size so you can see your riskiest chokepoints without knowing any names."""
    clear_parse_failures()
    root = _validated_root(args.path)
    graph = build_graph(root)
    ranked = hotspots(graph, limit=args.limit)

    failures = get_parse_failures()
    if not ranked:
        print("No functions found.")
        _print_parse_failures(failures)
        return

    print(f"Top {len(ranked)} riskiest functions in {root} (by blast-radius size):")
    width = max(len(name) for name, _ in ranked)
    for name, count in ranked:
        if count == 0:
            continue
        print(f"  {name.ljust(width)}   {count} dependent(s)")
    _print_parse_failures(failures)


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
    clear_parse_failures()
    root = _validated_root(args.path)
    graph = build_graph(root)
    failures = get_parse_failures()

    symbol = _resolve_symbol_or_exit(graph, args.symbol)
    if symbol != args.symbol:
        print(f"(matched '{args.symbol}' -> {symbol})")

    affected = blast_radius(graph, symbol)
    if not affected:
        print(f"No known dependents of {symbol}. Safe to change in isolation.")
        _print_test_suggestions([graph.nodes[symbol]["file"]])
        _print_parse_failures(failures)
        return

    print(f"Blast radius of {symbol}:")
    for name in sorted(affected):
        print(f"  - {name}")
    _print_test_suggestions([graph.nodes[symbol]["file"]])
    _print_parse_failures(failures)


def cmd_export(args: argparse.Namespace) -> None:
    clear_parse_failures()
    root = _validated_root(args.path)
    graph = build_graph(root)

    if args.format == "mermaid":
        content = to_mermaid(graph)
    elif args.format == "dot":
        content = to_dot(graph)
    else:
        content = to_json(graph)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(content, encoding="utf-8")
    else:
        print(content, end="")


def cmd_diff(args: argparse.Namespace) -> None:
    """Map a git diff to the set of functions/methods whose bodies changed,
    and show the combined blast radius of those functions."""
    # 1. Path validation first
    clear_parse_failures()
    root = _validated_root(args.path)

    # 2. Git repository validation
    from .git_diff import find_changed_functions, _assert_git_repo
    _assert_git_repo(root)

    ref_old: str = args.ref_old
    ref_new: str = args.ref_new

    # 3. Find changed functions
    changed = find_changed_functions(root, ref_old, ref_new)

    failures = get_parse_failures()
    if not changed:
        print(
            f"No Python function changes detected between "
            f"'{ref_old}' and '{ref_new}'."
        )
        _print_parse_failures(failures)
        return

    # Print changed functions line (like matching symbol in impact)
    changed_fqns_str = ", ".join(sorted(fn.fqn for fn in changed))
    print(f"(changed functions: {changed_fqns_str})")

    # 4. Compute merged, deduplicated blast radius
    from .graph import build_graph, merged_blast_radius

    try:
        graph = build_graph(root)
    except SyntaxError as exc:
        print(f"\nWarning: could not build full graph — a file in '{root}' has a syntax error:")
        print(f"  {exc}")
        print("  Impact analysis skipped. Fix the syntax error and re-run.")
        return

    # Gather only the changed FQNs that actually exist in the graph.
    known_targets = [fn.fqn for fn in changed if fn.fqn in graph]
    skipped = [fn.fqn for fn in changed if fn.fqn not in graph]
    if skipped:
        for s in skipped:
            print(f"  (note: '{s}' not found in graph — may be newly added; skipped for impact)")

    all_affected = merged_blast_radius(graph, known_targets)

    # Exclude the changed functions themselves from the blast-radius listing.
    changed_fqns = {fn.fqn for fn in changed}
    display = sorted(all_affected - changed_fqns)

    changed_files = [str(root / fn.file) for fn in changed]

    if not display:
        print(f"No known dependents of changed functions between {ref_old} and {ref_new}. Safe to change in isolation.")
        _print_test_suggestions(changed_files)
        _print_parse_failures(failures)
        return

    print(f"Blast radius of changed functions between {ref_old} and {ref_new}:")
    for name in display:
        print(f"  - {name}")
    _print_test_suggestions(changed_files)
    _print_parse_failures(failures)


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

    p_export = sub.add_parser(
        "export",
        help="Serialize the current graph to Mermaid, DOT, or JSON for visualization.",
    )
    p_export.add_argument(
        "--format",
        choices=["mermaid", "dot", "json"],
        required=True,
        help="Output format for the graph export.",
    )
    p_export.add_argument("--path", default=".", help="Root of the package to scan.")
    p_export.add_argument("--out", default=None, help="Optional file path to write the export to.")
    p_export.set_defaults(func=cmd_export)

    p_diff = sub.add_parser(
        "diff",
        help="Map a git diff to changed functions and (optionally) their blast radius.",
    )
    p_diff.add_argument(
        "ref_old",
        nargs="?",
        default="HEAD~1",
        help="Older git ref to diff from (default: HEAD~1).",
    )
    p_diff.add_argument(
        "ref_new",
        nargs="?",
        default="HEAD",
        help="Newer git ref to diff to (default: HEAD).",
    )
    p_diff.add_argument(
        "--path",
        default=".",
        help="Root of the git repository / package to scan (default: current directory).",
    )
    p_diff.set_defaults(func=cmd_diff)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

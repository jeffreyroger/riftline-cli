"""
riftline: a CLI that shows the blast radius of a code change before you make it.

Built with Typer (Click under the hood) + Rich for output formatting. The
command surface (scan / hotspots / impact / export / diff) is unchanged from
the original argparse implementation -- this file is the only one touched by
that swap, per NFR-5/NFR-6: parser.py, resolver.py, and graph.py still import
nothing beyond networkx.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from . import __version__
from .graph import (
    build_graph,
    blast_radius,
    hotspots as compute_hotspots,
    find_symbol,
    find_python_files,
    merged_blast_radius,
    real_nodes,
)
from .parser import clear_parse_failures, get_parse_failures
from .export import to_dot, to_json, to_mermaid
from .testmapper import suggest_test_file

console = Console()

app = typer.Typer(
    add_completion=False,
    help="Know what breaks before you break it.",
)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"riftline {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed version and exit.",
    ),
) -> None:
    """Know what breaks before you break it."""


def _validated_root(path_str: str) -> Path:
    """Resolve a path and fail loudly if it's wrong, instead of silently
    scanning nothing. This is the fix for the confusing 'No functions
    found' with no explanation that used to happen on a bad path."""
    root = Path(path_str).resolve()
    if not root.exists():
        console.print(f"Error: path does not exist: {root}", markup=False, soft_wrap=True)
        console.print("Check for a typo, or run 'dir' (Windows) / 'ls' (Mac/Linux) to see what's actually there.")
        raise SystemExit(1)
    if not root.is_dir():
        console.print(f"Error: not a directory: {root}", markup=False, soft_wrap=True)
        raise SystemExit(1)
    py_files = find_python_files(root)
    if not py_files:
        console.print(f"Error: no .py files found under: {root}", markup=False, soft_wrap=True)
        console.print("Check the path points at the folder that actually contains the code "
                      "(e.g. the folder with __init__.py / .py files in it, not its parent).")
        raise SystemExit(1)
    return root


def _print_test_suggestions(file_paths: list) -> None:
    """Additive, clearly-labeled section -- never blended into the graph-edge
    output above it. suggest_test_file() is a naming-convention heuristic,
    not a resolved fact (SRS 1.4), so this always prints under its own
    explicit "unverified" heading, styled distinctly (dim + italic) so
    pretty formatting can never make a guess look like a verified result."""
    console.print()
    console.print(
        "Possible related tests (unverified, naming-convention only):",
        style="dim italic",
    )
    found_any = False
    for path in sorted(set(file_paths)):
        suggestion = suggest_test_file(path)
        if suggestion:
            console.print(Text(f"  - {path} -> {suggestion}", style="dim italic"), soft_wrap=True)
            found_any = True
    if not found_any:
        console.print(Text("  - no matching test file found", style="dim italic"))


def _print_parse_failures(failures: list) -> None:
    if not failures:
        return
    console.print(
        Text(f"{len(failures)} file(s) failed to parse:", style="bold yellow")
    )
    for failure in failures:
        location = f"{failure.path}"
        if failure.line is not None:
            location = f"{location}:{failure.line}"
        console.print(Text(f"  - {location}: {failure.message}", style="yellow"), soft_wrap=True)


def _resolve_symbol_or_exit(graph, query: str) -> str:
    matches = find_symbol(graph, query)
    if not matches:
        console.print(
            f"Error: no function matching '{query}' was found in the scanned code.",
            markup=False,
        )
        raise SystemExit(1)
    if len(matches) > 1:
        console.print(f"'{query}' is ambiguous -- {len(matches)} functions match:", markup=False)
        for m in sorted(matches):
            console.print(Text(f"  - {m}"), soft_wrap=True)
        console.print("Re-run with one of the full names above.")
        raise SystemExit(1)
    return matches[0]


@app.command(name="scan", help="Parse a package and print a graph summary.")
def cmd_scan(
    path: str = typer.Argument(".", help="Root of the package to scan."),
) -> None:
    clear_parse_failures()
    root = _validated_root(path)
    graph = build_graph(root)
    failures = get_parse_failures()
    resolved = sum(1 for _, _, d in graph.edges(data=True) if d.get("confidence") == "resolved")
    unresolved = sum(1 for _, _, d in graph.edges(data=True) if d.get("confidence") == "unresolved")
    console.print(f"Scanned: {root}", markup=False, soft_wrap=True)
    console.print(f"  functions found : {len(real_nodes(graph))}")
    console.print(f"  edges resolved  : [blue]{resolved}[/blue]")
    console.print(f"  edges unresolved: [red]{unresolved}[/red]  (flagged, not guessed)")
    _print_parse_failures(failures)


@app.command(
    name="hotspots",
    help="Rank every function by blast-radius size. No symbol name needed.",
)
def cmd_hotspots(
    path: str = typer.Argument(".", help="Root of the package to scan."),
    limit: int = typer.Option(15, "--limit", help="Show top N (default 15)."),
) -> None:
    if limit < 1:
        console.print(
            f"Error: --limit must be a positive integer, got {limit}.",
            markup=False,
        )
        raise SystemExit(1)
    clear_parse_failures()
    root = _validated_root(path)
    graph = build_graph(root)
    ranked = compute_hotspots(graph, limit=limit)

    failures = get_parse_failures()
    if not ranked:
        console.print("No functions found.")
        _print_parse_failures(failures)
        return

    table = Table(
        title=Text(f"Top {len(ranked)} riskiest functions in {root} (by blast-radius size)"),
    )
    # overflow="fold": wrap long function names onto extra lines instead of
    # truncating with an ellipsis. Truncation risks emitting a mangled
    # replacement character mid-identifier on platforms where the Unicode
    # ellipsis isn't valid in the console's active encoding (e.g. Windows
    # cp1252) -- folding never needs that character at all, so the full
    # name is always readable, just wrapped rather than cut short.
    table.add_column("Function", overflow="fold")
    table.add_column("Dependents", justify="right")
    shown = 0
    for name, count in ranked:
        if count == 0:
            continue
        table.add_row(Text(name), str(count))
        shown += 1
    if shown == 0:
        console.print("No functions with a nonzero blast radius found.")
    else:
        console.print(table)
    _print_parse_failures(failures)


@app.command(name="impact", help="Show what breaks if SYMBOL changes.")
def cmd_impact(
    symbol: str = typer.Argument(
        ...,
        help="Function name -- full dotted path, or just the short name "
        "(e.g. 'square' or 'mypkg.core.square'). Short names auto-resolve "
        "if unambiguous.",
    ),
    path: str = typer.Option(".", "--path", help="Root of the package to scan."),
) -> None:
    clear_parse_failures()
    root = _validated_root(path)
    graph = build_graph(root)
    failures = get_parse_failures()

    resolved_symbol = _resolve_symbol_or_exit(graph, symbol)
    if resolved_symbol != symbol:
        console.print(Text(f"(matched '{symbol}' -> {resolved_symbol})"), soft_wrap=True)

    affected = blast_radius(graph, resolved_symbol)
    # Not every graph node has file metadata -- e.g. a locally-defined class
    # used as a constructor gets a bare edge-target node with no attributes
    # at all (it was never passed through the function-node-creation path).
    # Skip the test-suggestion section rather than crashing or guessing a
    # file that doesn't exist.
    resolved_file = graph.nodes[resolved_symbol].get("file")

    if not affected:
        console.print(
            Text(
                f"No known dependents of {resolved_symbol}. Safe to change in isolation.",
                style="green",
            )
        )
        if resolved_file is not None:
            _print_test_suggestions([resolved_file])
        _print_parse_failures(failures)
        return

    table = Table(title=Text(f"Blast radius of {resolved_symbol}"))
    table.add_column("Dependent function", overflow="fold")
    for name in sorted(affected):
        table.add_row(Text(name))
    console.print(table)
    if resolved_file is not None:
        _print_test_suggestions([resolved_file])
    _print_parse_failures(failures)


class ExportFormat(str, Enum):
    mermaid = "mermaid"
    dot = "dot"
    json = "json"


@app.command(
    name="export",
    help="Serialize the current graph to Mermaid, DOT, or JSON for visualization.",
)
def cmd_export(
    format: ExportFormat = typer.Option(
        ..., "--format", help="Output format for the graph export."
    ),
    path: str = typer.Option(".", "--path", help="Root of the package to scan."),
    out: Optional[str] = typer.Option(
        None, "--out", help="Optional file path to write the export to."
    ),
) -> None:
    clear_parse_failures()
    root = _validated_root(path)
    graph = build_graph(root)

    if format == ExportFormat.mermaid:
        content = to_mermaid(graph)
    elif format == ExportFormat.dot:
        content = to_dot(graph)
    else:
        content = to_json(graph)

    if out:
        out_path = Path(out)
        try:
            out_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            console.print(
                f"Error: could not write to '{out_path}': {exc.strerror or exc}",
                markup=False,
                soft_wrap=True,
            )
            raise SystemExit(1)
    else:
        # Raw content -- meant for redirection/piping into other tools, so it
        # is never passed through Rich markup or styling.
        print(content, end="")


@app.command(
    name="diff",
    help="Map a git diff to changed functions and (optionally) their blast radius.",
)
def cmd_diff(
    ref_old: str = typer.Argument("HEAD~1", help="Older git ref to diff from (default: HEAD~1)."),
    ref_new: str = typer.Argument("HEAD", help="Newer git ref to diff to (default: HEAD)."),
    path: str = typer.Option(
        ".",
        "--path",
        help="Root of the git repository / package to scan (default: current directory).",
    ),
) -> None:
    """Map a git diff to the set of functions/methods whose bodies changed,
    and show the combined blast radius of those functions."""
    # 1. Path validation first
    clear_parse_failures()
    root = _validated_root(path)

    # 2. Git repository validation
    from .git_diff import find_changed_functions, _assert_git_repo
    _assert_git_repo(root)

    # 3. Find changed functions
    changed = find_changed_functions(root, ref_old, ref_new)

    failures = get_parse_failures()
    if not changed:
        console.print(
            f"No Python function changes detected between "
            f"'{ref_old}' and '{ref_new}'.",
            markup=False,
        )
        _print_parse_failures(failures)
        return

    # Print changed functions line (like matching symbol in impact)
    changed_fqns_str = ", ".join(sorted(fn.fqn for fn in changed))
    console.print(Text(f"(changed functions: {changed_fqns_str})"), soft_wrap=True)

    # 4. Compute merged, deduplicated blast radius
    try:
        graph = build_graph(root)
    except SyntaxError as exc:
        console.print(
            f"\nWarning: could not build full graph — a file in '{root}' has a syntax error:",
            markup=False,
        )
        console.print(f"  {exc}", markup=False)
        console.print("  Impact analysis skipped. Fix the syntax error and re-run.")
        return

    # Refresh: build_graph() just scanned the whole package and may have
    # found parse failures beyond what find_changed_functions() saw (which
    # only parses files touched by the diff itself). Without this, a broken
    # file elsewhere in the package would be silently omitted below.
    failures = get_parse_failures()

    # Gather only the changed FQNs that actually exist in the graph.
    known_targets = [fn.fqn for fn in changed if fn.fqn in graph]
    skipped = [fn.fqn for fn in changed if fn.fqn not in graph]
    if skipped:
        for s in skipped:
            console.print(
                f"  (note: '{s}' not found in graph — may be newly added; skipped for impact)",
                markup=False,
            )

    all_affected = merged_blast_radius(graph, known_targets)

    # Exclude the changed functions themselves from the blast-radius listing.
    changed_fqns = {fn.fqn for fn in changed}
    display = sorted(all_affected - changed_fqns)

    changed_files = [str(root / fn.file) for fn in changed]

    if not display:
        console.print(
            f"No known dependents of changed functions between {ref_old} and {ref_new}. "
            "Safe to change in isolation.",
            markup=False,
        )
        _print_test_suggestions(changed_files)
        _print_parse_failures(failures)
        return

    console.print(
        Text(f"Blast radius of changed functions between {ref_old} and {ref_new}:")
    )
    for name in display:
        console.print(Text(f"  - {name}"), soft_wrap=True)
    _print_test_suggestions(changed_files)
    _print_parse_failures(failures)


def main() -> None:
    app()


if __name__ == "__main__":
    main()

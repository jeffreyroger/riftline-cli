#!/usr/bin/env python
"""
NFR-7 benchmark script -- standalone, not part of the installed `riftline`
package. Run directly against any external codebase:

    python scripts/benchmark.py --path /path/to/some/repo

Times a full scan (via the same build_graph() the `riftline` CLI itself
uses) against a real, external codebase and reports wall-clock timing plus
resolved/unresolved edge counts. This script only calls graph.py's existing
public functions -- it does not modify parser.py, resolver.py, graph.py, or
cli.py.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from riftline.graph import build_graph, find_python_files, real_nodes


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark a riftline scan against a real codebase.")
    ap.add_argument("--path", required=True, help="Root directory to scan.")
    args = ap.parse_args()

    root = Path(args.path).resolve()
    files = find_python_files(root)

    start = time.perf_counter()
    graph = build_graph(root)
    elapsed = time.perf_counter() - start

    resolved = sum(1 for _, _, d in graph.edges(data=True) if d.get("confidence") == "resolved")
    unresolved = sum(1 for _, _, d in graph.edges(data=True) if d.get("confidence") == "unresolved")

    print(f"Path scanned    : {root}")
    print(f"Files scanned   : {len(files)}")
    print(f"Functions found : {len(real_nodes(graph))}")
    print(f"Edges resolved  : {resolved}")
    print(f"Edges unresolved: {unresolved}")
    print(f"Elapsed         : {elapsed:.3f}s (wall-clock, time.perf_counter)")


if __name__ == "__main__":
    main()

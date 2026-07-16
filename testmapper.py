"""
Test-file suggestion heuristic (FR-21).

This module never touches the dependency graph and is not part of the
resolution pipeline -- a suggested test file is not a graph node or edge,
and must never be queryable via blast_radius(). It is a pure,
filesystem-checking convenience layered on top of a resolved graph
result, kept in its own file so graph.py never needs to know output
formats or naming heuristics exist (mirrors the export.py separation for
NFR-5 layer independence).

Guiding principle (SRS 1.4): never present a guess as a fact. Every
caller of suggest_test_file() must label its result as an unverified,
naming-convention-only suggestion -- never print it in the same format
as a resolved graph edge.
"""
from __future__ import annotations

from pathlib import Path

# Naming conventions checked, in order of preference. Both are common
# in Python projects; the first to actually exist on disk wins.
_CONVENTIONS = ("test_{stem}.py", "{stem}_test.py")


def suggest_test_file(module_path: str | Path) -> str | None:
    """Suggest a likely test file for `module_path` by naming convention only.

    Looks for a `tests/` directory that is a *sibling* of the module's own
    directory (e.g. `mypkg/core.py` -> `mypkg/tests/test_core.py`), which
    is exactly how this project's own layout works (`parser.py` and
    `tests/test_parser.py` are siblings at the repo root).

    Checks, in order: `tests/test_<name>.py`, then `tests/<name>_test.py`.
    Returns the first candidate that actually exists on disk, as a string
    path. Returns None if neither exists -- this function never fabricates
    a filename that isn't really there.
    """
    path = Path(module_path)
    tests_dir = path.parent / "tests"
    for pattern in _CONVENTIONS:
        candidate = tests_dir / pattern.format(stem=path.stem)
        if candidate.is_file():
            return str(candidate)
    return None

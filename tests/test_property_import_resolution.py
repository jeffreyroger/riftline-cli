"""
Property-based tests (hypothesis) for import resolution.

These generate synthetic packages with varying nesting depth and relative-
import dot counts -- including deliberately out-of-range dot counts that
overshoot the package root -- and assert the one invariant that must never
break, no matter how deep the nesting or how many leading dots a call site
uses (NFR-3, FR-8): every call the resolver produces becomes a graph edge
tagged with a confidence of exactly "resolved" or "unresolved". Never a
third value, never missing, and never an unhandled exception escaping
build_graph().
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given, settings, strategies as st

from riftline.graph import build_graph

VALID_CONFIDENCE_VALUES = {"resolved", "unresolved"}


def _assert_confidence_invariant(graph) -> None:
    for _, _, data in graph.edges(data=True):
        assert "confidence" in data, "every edge must carry a confidence value"
        assert data["confidence"] in VALID_CONFIDENCE_VALUES, (
            f"confidence must be exactly 'resolved' or 'unresolved', got {data['confidence']!r}"
        )


def _build_nested_package(root: Path, depth: int) -> Path:
    """root/pkg/level_1/level_2/.../level_<depth>/ , each with __init__.py.

    pkg/__init__.py defines `origin()`, the target every generated caller
    tries to reach via a relative import.
    """
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("def origin():\n    return 1\n", encoding="utf-8")

    current = pkg
    for i in range(1, depth + 1):
        current = current / f"level_{i}"
        current.mkdir()
        (current / "__init__.py").write_text("", encoding="utf-8")

    return current  # deepest package directory


@given(
    depth=st.integers(min_value=1, max_value=4),
    dots_offset=st.integers(min_value=-1, max_value=3),
)
@settings(max_examples=50, deadline=None)
def test_generated_relative_import_depths_always_yield_valid_confidence(depth, dots_offset):
    """A caller at the bottom of an N-level package chain imports `origin`
    via a relative import whose dot count is `depth + 1 + dots_offset`.

    dots_offset == 0 lands exactly on `pkg` (a valid, resolvable import).
    dots_offset < 0 lands one level too shallow (misses `origin`, must be
    unresolved, not resolved-by-accident).
    dots_offset > 0 overshoots past the package root entirely (must not
    crash the resolver -- must still come back as a clean unresolved edge).
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        deepest = _build_nested_package(root, depth)

        dots = max(1, depth + 1 + dots_offset)
        (deepest / "caller.py").write_text(
            "from " + "." * dots + " import origin\n\n"
            "def use():\n    return origin()\n",
            encoding="utf-8",
        )

        graph = build_graph(root)
        _assert_confidence_invariant(graph)


@given(nesting_depth=st.integers(min_value=1, max_value=5))
@settings(max_examples=25, deadline=None)
def test_generated_module_nesting_always_yields_valid_confidence(nesting_depth):
    """A pure nesting-depth sweep: build a chain of N empty subpackages with
    a function at the very bottom, and a sibling caller at the same depth
    that calls it via a single-dot same-package relative import. Regardless
    of how deep the nesting goes, every resulting edge must still carry a
    valid confidence value.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")

        current = pkg
        for i in range(1, nesting_depth + 1):
            current = current / f"level_{i}"
            current.mkdir()
            (current / "__init__.py").write_text("", encoding="utf-8")

        (current / "leaf.py").write_text(
            "def target():\n    return 42\n", encoding="utf-8"
        )
        (current / "caller.py").write_text(
            "from .leaf import target\n\ndef use():\n    return target()\n",
            encoding="utf-8",
        )

        graph = build_graph(root)
        _assert_confidence_invariant(graph)

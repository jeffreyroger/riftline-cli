"""
Regression tests for the graph builder and blast-radius query.
"""
from pathlib import Path

import pytest

from riftline.graph import build_graph, blast_radius, hotspots, find_symbol, merged_blast_radius

FIXTURES = Path(__file__).parent.parent / "fixtures"
REEXPORT_FIXTURES = FIXTURES / "reexport_pkg"


@pytest.fixture(scope="module")
def graph():
    return build_graph(FIXTURES)


class TestGraph:
    def test_all_functions_found(self, graph):
        expected_nodes = {
            "mini_pkg.core.low_level",
            "mini_pkg.utils.helper",
            "mini_pkg.main.foo",
            "mini_pkg.app.run",
        }
        assert expected_nodes.issubset(set(graph.nodes))

    def test_resolved_edges_are_correct(self, graph):
        resolved = {
            (u, v) for u, v, d in graph.edges(data=True) if d["confidence"] == "resolved"
        }
        assert ("mini_pkg.utils.helper", "mini_pkg.core.low_level") in resolved
        assert ("mini_pkg.main.foo", "mini_pkg.utils.helper") in resolved
        assert ("mini_pkg.app.run", "mini_pkg.main.foo") in resolved

    def test_unresolved_call_is_flagged_not_dropped(self, graph):
        unresolved_targets = {
            v for _, v, d in graph.edges(data=True) if d["confidence"] == "unresolved"
        }
        assert "unknown:bar" in unresolved_targets

    def test_blast_radius_of_core_is_full_chain(self, graph):
        radius = blast_radius(graph, "mini_pkg.core.low_level")
        assert radius == {"mini_pkg.utils.helper", "mini_pkg.main.foo", "mini_pkg.app.run"}

    def test_blast_radius_of_helper_excludes_core(self, graph):
        radius = blast_radius(graph, "mini_pkg.utils.helper")
        assert radius == {"mini_pkg.main.foo", "mini_pkg.app.run"}
        assert "mini_pkg.core.low_level" not in radius

    def test_blast_radius_of_leaf_with_no_dependents(self, graph):
        radius = blast_radius(graph, "mini_pkg.app.run")
        assert radius == set()

    def test_unknown_symbol_raises_keyerror(self, graph):
        with pytest.raises(KeyError):
            blast_radius(graph, "mini_pkg.does_not.exist")

    def test_hotspots_ranks_core_highest(self, graph):
        ranked = hotspots(graph)
        hit = next(item for item in ranked if item[0] == "mini_pkg.core.low_level")
        assert hit[1] == 3
        # unknown:* stub nodes must never appear in the ranking
        assert all(not name.startswith("unknown:") for name, _ in ranked)

    def test_hotspots_respects_limit(self, graph):
        ranked = hotspots(graph, limit=1)
        assert len(ranked) == 1

    def test_find_symbol_exact_match(self, graph):
        matches = find_symbol(graph, "mini_pkg.core.low_level")
        assert matches == ["mini_pkg.core.low_level"]

    def test_find_symbol_short_name_unambiguous(self, graph):
        matches = find_symbol(graph, "low_level")
        assert matches == ["mini_pkg.core.low_level"]

    def test_find_symbol_no_match_returns_empty(self, graph):
        matches = find_symbol(graph, "does_not_exist_anywhere")
        assert matches == []

    def test_oop_self_call_resolves(self, graph):
        resolved = {
            (u, v) for u, v, d in graph.edges(data=True) if d["confidence"] == "resolved"
        }
        assert ("oop_pkg.derived.Dog.bark", "oop_pkg.derived.Dog.play") in resolved

    def test_oop_inherited_call_resolves(self, graph):
        resolved = {
            (u, v) for u, v, d in graph.edges(data=True) if d["confidence"] == "resolved"
        }
        assert ("oop_pkg.derived.Dog.play", "oop_pkg.base.Animal.eat") in resolved

    def test_oop_chained_call_is_unresolved(self, graph):
        unresolved = {
            (u, v, d["reason"]) for u, v, d in graph.edges(data=True)
            if d["confidence"] == "unresolved" and d.get("reason")
        }
        targets = [reason for u, v, reason in unresolved if u == "oop_pkg.derived.Dog.play" and "squeak" in v]
        assert len(targets) > 0, "No unresolved edges found for Dog.play with 'squeak' in target"
        assert any("dynamic attribute target" in target for target in targets), (
            f"Reason should mention 'dynamic attribute target', got: {targets}"
        )

    # ------------------------------------------------------------------
    # merged_blast_radius: multi-target deduplication
    # ------------------------------------------------------------------

    def test_merged_blast_radius_deduplicates_shared_caller(self, graph):
        """
        mini_pkg dependency chain:  core <- utils <- main <- app

        blast_radius(core)  = {utils, main, app}
        blast_radius(utils) = {main, app}

        If both core and utils are "changed functions", main and app each
        appear in BOTH individual radii.  merged_blast_radius must return
        them exactly once, not twice.
        """
        core = "mini_pkg.core.low_level"
        utils = "mini_pkg.utils.helper"
        merged = merged_blast_radius(graph, [core, utils])

        # Shared callers must appear exactly once (set semantics guarantee this)
        assert "mini_pkg.main.foo" in merged
        assert "mini_pkg.app.run" in merged

        # The merged result is a plain set — verify no duplicates by checking
        # that the count matches a manually constructed union.
        expected = blast_radius(graph, core) | blast_radius(graph, utils)
        assert merged == expected

    def test_merged_blast_radius_single_target_matches_blast_radius(self, graph):
        """merged_blast_radius with one target must equal blast_radius exactly."""
        target = "mini_pkg.core.low_level"
        assert merged_blast_radius(graph, [target]) == blast_radius(graph, target)

    def test_merged_blast_radius_empty_targets_returns_empty_set(self, graph):
        """No targets => empty set (nothing changed, nothing affected)."""
        assert merged_blast_radius(graph, []) == set()

    def test_merged_blast_radius_unknown_target_raises_keyerror(self, graph):
        """Any unknown target must raise KeyError, same as blast_radius."""
        with pytest.raises(KeyError):
            merged_blast_radius(graph, ["mini_pkg.does.not.exist"])


# ------------------------------------------------------------------
# Phase C — re-export resolution tests
# ------------------------------------------------------------------

@pytest.fixture(scope="module")
def reexport_graph():
    return build_graph(FIXTURES)


@pytest.fixture(scope="module")
def reexport_resolved_edges(reexport_graph):
    return {
        (u, v)
        for u, v, d in reexport_graph.edges(data=True)
        if d["confidence"] == "resolved"
    }


@pytest.fixture(scope="module")
def reexport_unresolved_targets(reexport_graph):
    return {
        v
        for _, v, d in reexport_graph.edges(data=True)
        if d["confidence"] == "unresolved"
    }


class TestReExportResolution:
    """Regression tests for __init__.py re-export chain resolution (Phase C).

    Fixture layout (fixtures/reexport_pkg/):
      __init__.py          from .core import compute          (single-level)
                           from .subpkg import helper         (two-level, 1st hop)
      core.py              def compute(x): ...               (real origin of compute)
      caller.py            from reexport_pkg import compute   -> use_compute()
                           from reexport_pkg import helper    -> use_helper()
      subpkg/
        __init__.py        from .utils import helper          (two-level, 2nd hop)
        utils.py           def helper(x): ...                (real origin of helper)
    """

    def test_reexport_fixture_functions_found(self, reexport_graph):
        """All four functions across the fixture must be in the graph."""
        expected = {
            "reexport_pkg.core.compute",
            "reexport_pkg.subpkg.utils.helper",
            "reexport_pkg.caller.use_compute",
            "reexport_pkg.caller.use_helper",
        }
        assert expected.issubset(set(reexport_graph.nodes)), (
            f"Missing nodes. Graph has: {sorted(reexport_graph.nodes)}"
        )

    def test_single_level_reexport_resolves_to_true_origin(self, reexport_resolved_edges):
        """use_compute() calls compute() imported via a single-level re-export.

        Without Phase C:  caller->unknown:compute   (unresolved)
        With    Phase C:  caller->reexport_pkg.core.compute  (resolved)
        """
        assert ("reexport_pkg.caller.use_compute", "reexport_pkg.core.compute") in reexport_resolved_edges, (
            "Single-level re-export did not resolve to the true origin module."
        )

    def test_two_level_reexport_resolves_to_true_origin(self, reexport_resolved_edges):
        """use_helper() calls helper() imported via a two-level re-export chain.

        Chain: reexport_pkg.__init__ -> subpkg.__init__ -> subpkg.utils
        Without Phase C:  caller->unknown:helper   (unresolved)
        With    Phase C:  caller->reexport_pkg.subpkg.utils.helper  (resolved)
        """
        assert ("reexport_pkg.caller.use_helper", "reexport_pkg.subpkg.utils.helper") in reexport_resolved_edges, (
            "Two-level re-export did not resolve to the true origin module."
        )

    def test_reexport_calls_not_flagged_unknown(self, reexport_unresolved_targets):
        """Neither compute nor helper should appear as unknown:* targets
        when the re-export chain is fully scanned and resolvable."""
        assert "unknown:compute" not in reexport_unresolved_targets, (
            "compute was flagged unknown despite a resolvable single-level re-export."
        )
        assert "unknown:helper" not in reexport_unresolved_targets, (
            "helper was flagged unknown despite a resolvable two-level re-export."
        )

    def test_compute_blast_radius_includes_use_compute(self, reexport_graph):
        """Changing compute() must surface use_compute() as a dependent."""
        radius = blast_radius(reexport_graph, "reexport_pkg.core.compute")
        assert "reexport_pkg.caller.use_compute" in radius

    def test_helper_blast_radius_includes_use_helper(self, reexport_graph):
        """Changing helper() must surface use_helper() as a dependent."""
        radius = blast_radius(reexport_graph, "reexport_pkg.subpkg.utils.helper")
        assert "reexport_pkg.caller.use_helper" in radius

    # ------------------------------------------------------------------
    # Frozen-fixture regression check (Phase C must not disturb A/B)
    # ------------------------------------------------------------------

    def test_prior_fixture_blast_radius_unchanged(self):
        """mini_pkg.core.low_level blast radius must equal the Phase-B result."""
        graph_all = build_graph(FIXTURES)
        radius = blast_radius(graph_all, "mini_pkg.core.low_level")
        assert radius == {"mini_pkg.utils.helper", "mini_pkg.main.foo", "mini_pkg.app.run"}

    # ------------------------------------------------------------------
    # Regression tests: multiple inheritance and root-level package scans
    # ------------------------------------------------------------------

    def test_multiple_inheritance_ambiguity_flagged_unresolved(self):
        """When a class inherits from multiple bases with the same method,
        the call should be flagged unresolved with 'ambiguous' reason,
        not silently resolved to the first base (violates core principle).

        Defect: previously _find_method_in_hierarchy silently returned the
        first matching base without checking for ambiguity.
        """
        mi_graph = build_graph(FIXTURES / "mi_pkg")

        # Duck.go calls self.move(), which is defined on both Flyer and Swimmer
        unresolved_edges_with_reasons = [
            (u, v, d.get("reason"))
            for u, v, d in mi_graph.edges(data=True)
            if d["confidence"] == "unresolved" and d.get("reason")
        ]

        # Find the edge from Duck.go to the ambiguous self.move()
        ambiguous_edges = [
            (u, v, reason)
            for u, v, reason in unresolved_edges_with_reasons
            if u == "mi_pkg.animals.Duck.go" and "move" in v
        ]

        assert len(ambiguous_edges) > 0, "Duck.go should have an unresolved edge to self.move()"

        # Verify that the reason mentions ambiguity
        reasons = [r for _, _, r in ambiguous_edges]
        assert any("ambiguous" in reason.lower() for reason in reasons), (
            f"Reason should mention 'ambiguous', got: {reasons}"
        )

    def test_package_as_own_root_relative_imports_work(self):
        """When a package is scanned as its own root (e.g., 'riftline scan mi_pkg'),
        relative imports in __init__.py should resolve correctly.

        Defect: previously, module_name_for_file returned '' for root-level __init__.py,
        causing resolve_relative_module to produce malformed module names like '.core'.

        This is the most common real-world invocation pattern ('riftline scan .')
        and must work without the user having to scan from a parent level.
        """
        mi_pkg_root = FIXTURES / "mi_pkg"

        # Build graph by scanning mi_pkg as its own root (not its parent)
        mi_graph = build_graph(mi_pkg_root)

        # Verify we found the functions
        assert "mi_pkg.animals.Flyer.move" in mi_graph.nodes
        assert "mi_pkg.animals.Swimmer.move" in mi_graph.nodes
        assert "mi_pkg.animals.Duck.go" in mi_graph.nodes

    def test_reexport_package_as_own_root_resolves(self):
        """Re-export resolution (Phase C) must work when scanning a package
        as its own root, not just when scanning from a parent level.

        Previously: scanning fixtures/reexport_pkg/ as its own root produced
        unresolved edges for re-exported names, even though scanning fixtures/
        would resolve them. This affected the tool's primary use case.

        Defect: root-level __init__.py had empty module name, breaking relative
        import resolution in re-export patterns.
        """
        reexport_root = FIXTURES / "reexport_pkg"

        # Build graph by scanning reexport_pkg as its own root
        reexport_graph_own_root = build_graph(reexport_root)

        resolved_edges = {
            (u, v)
            for u, v, d in reexport_graph_own_root.edges(data=True)
            if d["confidence"] == "resolved"
        }

        # The re-export chain should resolve: caller imports from top-level __init__
        # which re-exports from submodules
        assert ("reexport_pkg.caller.use_compute", "reexport_pkg.core.compute") in resolved_edges, (
            "Re-export should resolve to true origin even when package is scanned as root"
        )

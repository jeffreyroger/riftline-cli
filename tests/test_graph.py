"""
Regression tests for the graph builder and blast-radius query.

NOTE: written with stdlib `unittest` since this sandbox has no network
access to pip install pytest. These run under pytest unmodified once you
have it locally (`pip install pytest && pytest tests/`) -- pytest discovers
and runs TestCase classes just fine.
"""
from pathlib import Path
import unittest

from riftline.graph import build_graph, blast_radius, hotspots, find_symbol, merged_blast_radius

FIXTURES = Path(__file__).parent.parent / "fixtures"
REEXPORT_FIXTURES = FIXTURES / "reexport_pkg"


class TestGraph(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = build_graph(FIXTURES)

    def test_all_functions_found(self):
        expected_nodes = {
            "mini_pkg.core.low_level",
            "mini_pkg.utils.helper",
            "mini_pkg.main.foo",
            "mini_pkg.app.run",
        }
        self.assertTrue(expected_nodes.issubset(set(self.graph.nodes)))

    def test_resolved_edges_are_correct(self):
        resolved = {
            (u, v) for u, v, d in self.graph.edges(data=True) if d["confidence"] == "resolved"
        }
        self.assertIn(("mini_pkg.utils.helper", "mini_pkg.core.low_level"), resolved)
        self.assertIn(("mini_pkg.main.foo", "mini_pkg.utils.helper"), resolved)
        self.assertIn(("mini_pkg.app.run", "mini_pkg.main.foo"), resolved)

    def test_unresolved_call_is_flagged_not_dropped(self):
        unresolved_targets = {
            v for _, v, d in self.graph.edges(data=True) if d["confidence"] == "unresolved"
        }
        self.assertIn("unknown:bar", unresolved_targets)

    def test_blast_radius_of_core_is_full_chain(self):
        radius = blast_radius(self.graph, "mini_pkg.core.low_level")
        self.assertEqual(
            radius,
            {"mini_pkg.utils.helper", "mini_pkg.main.foo", "mini_pkg.app.run"},
        )

    def test_blast_radius_of_helper_excludes_core(self):
        radius = blast_radius(self.graph, "mini_pkg.utils.helper")
        self.assertEqual(radius, {"mini_pkg.main.foo", "mini_pkg.app.run"})
        self.assertNotIn("mini_pkg.core.low_level", radius)

    def test_blast_radius_of_leaf_with_no_dependents(self):
        radius = blast_radius(self.graph, "mini_pkg.app.run")
        self.assertEqual(radius, set())

    def test_unknown_symbol_raises_keyerror(self):
        with self.assertRaises(KeyError):
            blast_radius(self.graph, "mini_pkg.does_not.exist")

    def test_hotspots_ranks_core_highest(self):
        ranked = hotspots(self.graph)
        hit = next(item for item in ranked if item[0] == "mini_pkg.core.low_level")
        self.assertEqual(hit[1], 3)
        # unknown:* stub nodes must never appear in the ranking
        self.assertTrue(all(not name.startswith("unknown:") for name, _ in ranked))

    def test_hotspots_respects_limit(self):
        ranked = hotspots(self.graph, limit=1)
        self.assertEqual(len(ranked), 1)

    def test_find_symbol_exact_match(self):
        matches = find_symbol(self.graph, "mini_pkg.core.low_level")
        self.assertEqual(matches, ["mini_pkg.core.low_level"])

    def test_find_symbol_short_name_unambiguous(self):
        matches = find_symbol(self.graph, "low_level")
        self.assertEqual(matches, ["mini_pkg.core.low_level"])

    def test_find_symbol_no_match_returns_empty(self):
        matches = find_symbol(self.graph, "does_not_exist_anywhere")
        self.assertEqual(matches, [])

    def test_oop_self_call_resolves(self):
        resolved = {
            (u, v) for u, v, d in self.graph.edges(data=True) if d["confidence"] == "resolved"
        }
        self.assertIn(("oop_pkg.derived.Dog.bark", "oop_pkg.derived.Dog.play"), resolved)

    def test_oop_inherited_call_resolves(self):
        resolved = {
            (u, v) for u, v, d in self.graph.edges(data=True) if d["confidence"] == "resolved"
        }
        self.assertIn(("oop_pkg.derived.Dog.play", "oop_pkg.base.Animal.eat"), resolved)

    def test_oop_chained_call_is_unresolved(self):
        unresolved = {
            (u, v) for u, v, d in self.graph.edges(data=True) if d["confidence"] == "unresolved"
        }
        targets = [v for u, v in unresolved if u == "oop_pkg.derived.Dog.play" and "squeak" in v]
        self.assertTrue(len(targets) > 0)
        self.assertIn("dynamic attribute target, not statically resolvable", targets[0])


    # ------------------------------------------------------------------
    # merged_blast_radius: multi-target deduplication
    # ------------------------------------------------------------------

    def test_merged_blast_radius_deduplicates_shared_caller(self):
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
        merged = merged_blast_radius(self.graph, [core, utils])

        # Shared callers must appear exactly once (set semantics guarantee this)
        self.assertIn("mini_pkg.main.foo", merged)
        self.assertIn("mini_pkg.app.run", merged)

        # The merged result is a plain set — verify no duplicates by checking
        # that the count matches a manually constructed union.
        expected = (
            blast_radius(self.graph, core) | blast_radius(self.graph, utils)
        )
        self.assertEqual(merged, expected)

    def test_merged_blast_radius_single_target_matches_blast_radius(self):
        """merged_blast_radius with one target must equal blast_radius exactly."""
        target = "mini_pkg.core.low_level"
        self.assertEqual(
            merged_blast_radius(self.graph, [target]),
            blast_radius(self.graph, target),
        )

    def test_merged_blast_radius_empty_targets_returns_empty_set(self):
        """No targets => empty set (nothing changed, nothing affected)."""
        self.assertEqual(merged_blast_radius(self.graph, []), set())

    def test_merged_blast_radius_unknown_target_raises_keyerror(self):
        """Any unknown target must raise KeyError, same as blast_radius."""
        with self.assertRaises(KeyError):
            merged_blast_radius(self.graph, ["mini_pkg.does.not.exist"])


# ------------------------------------------------------------------
# Phase C — re-export resolution tests
# ------------------------------------------------------------------

class TestReExportResolution(unittest.TestCase):
    """Regression tests for __init__.py re-export chain resolution (Phase C).

    Fixture layout (fixtures/reexport_pkg/):
      __init__.py          from .core import compute          (single-level)
                           from .subpkg import helper         (two-level, 1st hop)
      core.py              def compute(x): ...               (real origin of compute)
      caller.py            from reexport_pkg import compute   → use_compute()
                           from reexport_pkg import helper    → use_helper()
      subpkg/
        __init__.py        from .utils import helper          (two-level, 2nd hop)
        utils.py           def helper(x): ...                (real origin of helper)
    """

    @classmethod
    def setUpClass(cls):
        cls.graph = build_graph(FIXTURES)
        cls.resolved_edges = {
            (u, v)
            for u, v, d in cls.graph.edges(data=True)
            if d["confidence"] == "resolved"
        }
        cls.unresolved_targets = {
            v
            for _, v, d in cls.graph.edges(data=True)
            if d["confidence"] == "unresolved"
        }

    def test_reexport_fixture_functions_found(self):
        """All four functions across the fixture must be in the graph."""
        expected = {
            "reexport_pkg.core.compute",
            "reexport_pkg.subpkg.utils.helper",
            "reexport_pkg.caller.use_compute",
            "reexport_pkg.caller.use_helper",
        }
        self.assertTrue(
            expected.issubset(set(self.graph.nodes)),
            msg=f"Missing nodes. Graph has: {sorted(self.graph.nodes)}",
        )

    def test_single_level_reexport_resolves_to_true_origin(self):
        """use_compute() calls compute() imported via a single-level re-export.

        Without Phase C:  caller→unknown:compute   (unresolved)
        With    Phase C:  caller→reexport_pkg.core.compute  (resolved)
        """
        self.assertIn(
            ("reexport_pkg.caller.use_compute", "reexport_pkg.core.compute"),
            self.resolved_edges,
            msg="Single-level re-export did not resolve to the true origin module.",
        )

    def test_two_level_reexport_resolves_to_true_origin(self):
        """use_helper() calls helper() imported via a two-level re-export chain.

        Chain: reexport_pkg.__init__ -> subpkg.__init__ -> subpkg.utils
        Without Phase C:  caller→unknown:helper   (unresolved)
        With    Phase C:  caller→reexport_pkg.subpkg.utils.helper  (resolved)
        """
        self.assertIn(
            ("reexport_pkg.caller.use_helper", "reexport_pkg.subpkg.utils.helper"),
            self.resolved_edges,
            msg="Two-level re-export did not resolve to the true origin module.",
        )

    def test_reexport_calls_not_flagged_unknown(self):
        """Neither compute nor helper should appear as unknown:* targets
        when the re-export chain is fully scanned and resolvable."""
        self.assertNotIn(
            "unknown:compute",
            self.unresolved_targets,
            msg="compute was flagged unknown despite a resolvable single-level re-export.",
        )
        self.assertNotIn(
            "unknown:helper",
            self.unresolved_targets,
            msg="helper was flagged unknown despite a resolvable two-level re-export.",
        )

    def test_compute_blast_radius_includes_use_compute(self):
        """Changing compute() must surface use_compute() as a dependent."""
        radius = blast_radius(self.graph, "reexport_pkg.core.compute")
        self.assertIn("reexport_pkg.caller.use_compute", radius)

    def test_helper_blast_radius_includes_use_helper(self):
        """Changing helper() must surface use_helper() as a dependent."""
        radius = blast_radius(self.graph, "reexport_pkg.subpkg.utils.helper")
        self.assertIn("reexport_pkg.caller.use_helper", radius)

    # ------------------------------------------------------------------
    # Frozen-fixture regression check (Phase C must not disturb A/B)
    # ------------------------------------------------------------------

    def test_prior_fixture_blast_radius_unchanged(self):
        """mini_pkg.core.low_level blast radius must equal the Phase-B result."""
        graph_all = build_graph(FIXTURES)
        radius = blast_radius(graph_all, "mini_pkg.core.low_level")
        self.assertEqual(
            radius,
            {"mini_pkg.utils.helper", "mini_pkg.main.foo", "mini_pkg.app.run"},
        )


if __name__ == "__main__":
    unittest.main()

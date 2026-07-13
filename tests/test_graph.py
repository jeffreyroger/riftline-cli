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
        top_name, top_count = ranked[0]
        self.assertEqual(top_name, "mini_pkg.core.low_level")
        self.assertEqual(top_count, 3)
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


if __name__ == "__main__":
    unittest.main()

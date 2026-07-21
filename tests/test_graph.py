"""
Regression tests for the graph builder and blast-radius query.
"""
import subprocess
import sys
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

    def test_cli_hotspots_rejects_zero_limit(self):
        """Regression test: `--limit 0` (or negative) must be a clean
        NFR-4-style error, not a misleading 'No functions found.' or a
        silently-wrong result from Python's negative-slice semantics."""
        from typer.testing import CliRunner
        from riftline.cli import app

        result = CliRunner().invoke(app, ["hotspots", str(FIXTURES / "mini_pkg"), "--limit", "0"])
        assert result.exit_code == 1
        assert "Error" in result.output
        assert "--limit" in result.output

    def test_cli_hotspots_rejects_negative_limit(self):
        from typer.testing import CliRunner
        from riftline.cli import app

        result = CliRunner().invoke(app, ["hotspots", str(FIXTURES / "synthetic_pkg"), "--limit", "-3"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_find_symbol_exact_match(self, graph):
        matches = find_symbol(graph, "mini_pkg.core.low_level")
        assert matches == ["mini_pkg.core.low_level"]

    def test_find_symbol_short_name_unambiguous(self, graph):
        matches = find_symbol(graph, "low_level")
        assert matches == ["mini_pkg.core.low_level"]

    def test_find_symbol_no_match_returns_empty(self, graph):
        matches = find_symbol(graph, "does_not_exist_anywhere")
        assert matches == []

    def test_find_symbol_empty_query_returns_empty_not_everything(self, graph):
        """Regression test: an empty query must never fall through to the
        substring-match fallback, which would otherwise "match" every
        function in the graph (every string contains the empty
        substring) -- a confusing 'ambiguous' result for what should be a
        clear 'no symbol given' case."""
        matches = find_symbol(graph, "")
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


# ------------------------------------------------------------------
# module.function() attribute-call resolution
# ------------------------------------------------------------------

class TestModuleAttributeCallResolution:
    """Regression tests: `module.function()` (as opposed to
    `from module import function`) must resolve when `module` is a
    fully-scanned local module, and must NOT be guessed when the imported
    name turns out to be a symbol (function/class) rather than a module.
    """

    def test_relative_import_of_submodule_resolves(self, tmp_path):
        """`from . import utils` then `utils.helper()` -- utils is a
        submodule of the current package, not a symbol defined in it."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "utils.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
        (pkg / "app.py").write_text(
            "from . import utils\n\ndef run():\n    return utils.helper()\n",
            encoding="utf-8",
        )

        graph = build_graph(pkg)
        resolved = {
            (u, v) for u, v, d in graph.edges(data=True) if d["confidence"] == "resolved"
        }
        assert ("pkg.app.run", "pkg.utils.helper") in resolved

    def test_absolute_aliased_submodule_import_resolves(self, tmp_path):
        """`import pkg.sub.deep as d` then `d.deep_helper()`."""
        pkg = tmp_path / "pkg"
        sub = pkg / "sub"
        sub.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (sub / "__init__.py").write_text("", encoding="utf-8")
        (sub / "deep.py").write_text("def deep_helper():\n    return 1\n", encoding="utf-8")
        (pkg / "app.py").write_text(
            "import pkg.sub.deep as d\n\ndef run():\n    return d.deep_helper()\n",
            encoding="utf-8",
        )

        graph = build_graph(pkg)
        resolved = {
            (u, v) for u, v, d in graph.edges(data=True) if d["confidence"] == "resolved"
        }
        assert ("pkg.app.run", "pkg.sub.deep.deep_helper") in resolved

    def test_imported_function_used_as_attribute_base_stays_unresolved(self, tmp_path):
        """`from .core import compute` then `compute.something()` --
        `compute` is a FUNCTION, not a module. Must never be guessed as
        if it were the module `pkg.core` just because that module exists."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "core.py").write_text("def compute(x):\n    return x\n", encoding="utf-8")
        (pkg / "app.py").write_text(
            "from .core import compute\n\ndef run():\n    return compute.something()\n",
            encoding="utf-8",
        )

        graph = build_graph(pkg)
        unresolved_targets = {
            v for _, v, d in graph.edges(data=True) if d["confidence"] == "unresolved"
        }
        assert "unknown:compute.something" in unresolved_targets


# ------------------------------------------------------------------
# `riftline impact` on a class-used-as-constructor node must not crash
# ------------------------------------------------------------------

class TestCliImpactOnClassNodeDoesNotCrash:
    """Regression test: a locally-defined class used as a constructor call
    (e.g. `Widget()`) resolves to a graph node that was never passed
    through the function-node-creation path, so it has no `file`/`lineno`
    attributes. `riftline impact <ClassFQN>` must handle that gracefully
    instead of crashing with an unhandled KeyError when it tries to look
    up a test-file suggestion for it.
    """

    def _run_impact(self, *extra_args: str) -> tuple[str, int]:
        from typer.testing import CliRunner
        from riftline.cli import app

        result = CliRunner().invoke(app, ["impact", *extra_args])
        return result.output, result.exit_code

    def test_impact_on_class_target_does_not_crash(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "widgets.py").write_text(
            "class Widget:\n    pass\n\n\ndef make_widget():\n    return Widget()\n",
            encoding="utf-8",
        )

        out, code = self._run_impact("pkg.widgets.Widget", "--path", str(pkg))

        assert code == 0
        assert "KeyError" not in out
        assert "Traceback" not in out
        assert "make_widget" in out


class TestHotspotsTableDoesNotCorruptLongNames:
    """
    Regression test: a function name long enough to overflow the
    "Function" table column must wrap onto extra lines, never get
    truncated with an ellipsis. Truncation is what previously risked a
    mangled replacement character mid-identifier on platforms where the
    console's active encoding can't represent Rich's Unicode ellipsis
    (verified on this project's own self-scan: `_assert_confidence_invariant`
    came back as `..._assert_confidence_inva<corrupted>`). This must be a
    real subprocess run -- the corruption is a byte-level encoding issue
    that a CliRunner-captured (already-decoded) string can't reproduce.
    """

    def test_long_function_name_is_never_truncated_or_corrupted(self, tmp_path):
        long_name = "a_very_long_function_name_that_will_not_fit_in_one_table_column_" * 2
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "core.py").write_text(
            f"def {long_name}():\n    return 1\n\n\ndef caller():\n    return {long_name}()\n",
            encoding="utf-8",
        )

        completed = subprocess.run(
            [sys.executable, "-m", "riftline.cli", "hotspots", str(pkg), "--limit", "5"],
            capture_output=True,
            text=False,  # raw bytes -- this is a byte-level encoding concern
            cwd=str(Path(__file__).parent.parent),
            check=False,
        )
        assert completed.returncode == 0

        raw = completed.stdout
        # No Unicode replacement character, in either its UTF-8 encoding or
        # as a literal '?' produced by a lossy encode -- the real signal is
        # that the full identifier is recoverable from the output at all.
        assert "�".encode("utf-8") not in raw

        decoded = raw.decode(sys.stdout.encoding or "utf-8", errors="strict")
        # Reconstitute the identifier from wrapped table-cell fragments:
        # a wrapped "Function" column produces one table row per fragment,
        # each of the form "| <fragment> | <dependents or blank> |". Take
        # only the first ("Function") cell of each data row (skipping the
        # header/divider lines) and concatenate those, in order -- this
        # must reproduce the full name exactly, proving nothing was
        # truncated, dropped, or corrupted.
        #
        # Rich's own ASCII-vs-Unicode fallback means the vertical separator
        # can be either "|" (this project's Windows/non-tty ASCII mode) or
        # "│" (Unicode box-drawing, used on e.g. Linux CI where stdout
        # is natively UTF-8) -- normalize both to "|" before splitting so
        # this test doesn't depend on which one Rich picked.
        normalized = decoded.replace("│", "|")
        fragments = []
        for line in normalized.splitlines():
            parts = line.split("|")
            if len(parts) == 4 and "Function" not in line and "---" not in line:
                fragments.append(parts[1].strip())
        reconstructed = "".join(fragments)
        assert long_name in reconstructed

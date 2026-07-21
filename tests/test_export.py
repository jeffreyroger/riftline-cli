import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from riftline.export import to_dot, to_json, to_mermaid
from riftline.graph import build_graph

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mini_pkg"
ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def graph():
    return build_graph(FIXTURES)


class TestExport:
    def test_to_json_is_valid_and_matches_fixture_counts(self, graph) -> None:
        payload = json.loads(to_json(graph))
        assert "nodes" in payload
        assert "edges" in payload
        assert len(payload["nodes"]) == graph.number_of_nodes()
        assert len(payload["edges"]) == graph.number_of_edges()

    def test_to_mermaid_has_expected_structure(self, graph) -> None:
        text = to_mermaid(graph)
        assert text.startswith("flowchart TD")
        assert "-->" in text
        assert "-.->" in text

    def test_to_dot_has_expected_structure(self, graph) -> None:
        text = to_dot(graph)
        assert text.startswith("digraph G {")
        assert "digraph" in text
        assert "->" in text

    def test_sanitized_node_ids_never_collide(self) -> None:
        """Regression test: two distinct FQNs that only differ in where a
        "." falls (e.g. "pkg.a_b" vs "pkg.a.b") must never sanitize to the
        same Mermaid/DOT node id -- that would silently merge two unrelated
        functions into one diagram node."""
        import networkx as nx
        from riftline.export import to_mermaid

        g = nx.DiGraph()
        g.add_node("pkg.a_b")
        g.add_node("pkg.a.b")
        text = to_mermaid(g)

        # Extract the node id each declaration line uses (the token before "[").
        node_ids = [
            line.split("[", 1)[0].strip()
            for line in text.splitlines()
            if "[" in line
        ]
        assert len(node_ids) == len(set(node_ids)), (
            f"sanitized node ids collided: {node_ids}"
        )

    def test_cli_export_writes_json_file(self, graph) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "export.json"
            completed = subprocess.run(
                [sys.executable, "-m", "riftline.cli", "export", "--format", "json", "--path", str(FIXTURES), "--out", str(out_path)],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
                check=False,
            )
            assert completed.returncode == 0, completed.stderr
            assert out_path.exists()
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            assert "nodes" in payload
            assert "edges" in payload

    def test_cli_export_out_in_nonexistent_dir_fails_cleanly(self) -> None:
        """Regression test: a bad --out path must produce a clear, specific
        error message and exit code 1 (NFR-4), never an unhandled traceback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_out = Path(tmpdir) / "no_such_subdir" / "out.json"
            completed = subprocess.run(
                [sys.executable, "-m", "riftline.cli", "export", "--format", "json", "--path", str(FIXTURES), "--out", str(bad_out)],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
                check=False,
            )
            assert completed.returncode == 1
            assert "Traceback" not in completed.stdout
            assert "Traceback" not in completed.stderr
            assert "Error" in completed.stdout
            assert not bad_out.exists()

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

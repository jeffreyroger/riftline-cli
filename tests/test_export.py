import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from riftline.export import to_dot, to_json, to_mermaid
from riftline.graph import build_graph

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mini_pkg"
ROOT = Path(__file__).parent.parent


class TestExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = build_graph(FIXTURES)

    def test_to_json_is_valid_and_matches_fixture_counts(self) -> None:
        payload = json.loads(to_json(self.graph))
        self.assertIn("nodes", payload)
        self.assertIn("edges", payload)
        self.assertEqual(len(payload["nodes"]), self.graph.number_of_nodes())
        self.assertEqual(len(payload["edges"]), self.graph.number_of_edges())

    def test_to_mermaid_has_expected_structure(self) -> None:
        text = to_mermaid(self.graph)
        self.assertTrue(text.startswith("flowchart TD"))
        self.assertIn("-->", text)
        self.assertIn("-.->", text)

    def test_to_dot_has_expected_structure(self) -> None:
        text = to_dot(self.graph)
        self.assertTrue(text.startswith("digraph G {"))
        self.assertIn("digraph", text)
        self.assertIn("->", text)

    def test_cli_export_writes_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "export.json"
            completed = subprocess.run(
                [sys.executable, "-m", "riftline.cli", "export", "--format", "json", "--path", str(FIXTURES), "--out", str(out_path)],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertTrue(out_path.exists())
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertIn("nodes", payload)
            self.assertIn("edges", payload)

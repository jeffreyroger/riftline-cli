from pathlib import Path
import subprocess
import sys
import unittest

from riftline.graph import build_graph
from riftline.parser import clear_parse_failures, get_parse_failures, parse

FIXTURES = Path(__file__).parent.parent / "fixtures" / "broken_syntax_pkg"
ROOT = Path(__file__).parent.parent


class TestSyntaxErrorResilience(unittest.TestCase):
    def setUp(self) -> None:
        clear_parse_failures()

    def test_parse_returns_structured_failure_for_syntax_error(self) -> None:
        parsed = parse(FIXTURES / "broken.py")

        self.assertIsNotNone(parsed.parse_error)
        self.assertEqual(parsed.parse_error.path, FIXTURES / "broken.py")
        self.assertIn("invalid syntax", parsed.parse_error.message.lower())
        self.assertEqual(parsed.functions, [])
        self.assertEqual(parsed.imports, {})

    def test_build_graph_skips_syntax_error_and_keeps_valid_functions(self) -> None:
        graph = build_graph(FIXTURES)

        self.assertIn("good_a.alpha", graph.nodes)
        self.assertIn("good_a.call_alpha", graph.nodes)
        self.assertIn("good_b.beta", graph.nodes)
        self.assertIn(
            ("good_b.beta", "good_a.call_alpha"),
            {(u, v) for u, v, d in graph.edges(data=True) if d["confidence"] == "resolved"},
        )

        failures = get_parse_failures()
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].path, FIXTURES / "broken.py")
        self.assertIn("invalid syntax", failures[0].message.lower())

    def test_cli_scan_reports_parse_failure_without_crashing(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "riftline.cli", "scan", str(FIXTURES)],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            check=False,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        self.assertIn("1 file(s) failed to parse:", completed.stdout)
        self.assertIn("broken.py", completed.stdout)
        self.assertIn("invalid syntax", completed.stdout.lower())

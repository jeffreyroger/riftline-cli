from pathlib import Path
import subprocess
import sys

import pytest

from riftline.graph import build_graph
from riftline.parser import clear_parse_failures, get_parse_failures, parse

FIXTURES = Path(__file__).parent.parent / "fixtures" / "broken_syntax_pkg"
ROOT = Path(__file__).parent.parent


class TestSyntaxErrorResilience:
    @pytest.fixture(autouse=True)
    def _clear_failures(self):
        clear_parse_failures()

    def test_parse_returns_structured_failure_for_syntax_error(self) -> None:
        parsed = parse(FIXTURES / "broken.py")

        assert parsed.parse_error is not None
        assert parsed.parse_error.path == FIXTURES / "broken.py"
        assert "invalid syntax" in parsed.parse_error.message.lower()
        assert parsed.functions == []
        assert parsed.imports == {}

    def test_build_graph_skips_syntax_error_and_keeps_valid_functions(self) -> None:
        graph = build_graph(FIXTURES)

        assert "good_a.alpha" in graph.nodes
        assert "good_a.call_alpha" in graph.nodes
        assert "good_b.beta" in graph.nodes
        assert ("good_b.beta", "good_a.call_alpha") in {
            (u, v) for u, v, d in graph.edges(data=True) if d["confidence"] == "resolved"
        }

        failures = get_parse_failures()
        assert len(failures) == 1
        assert failures[0].path == FIXTURES / "broken.py"
        assert "invalid syntax" in failures[0].message.lower()

    def test_cli_scan_reports_parse_failure_without_crashing(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "riftline.cli", "scan", str(FIXTURES)],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        assert "1 file(s) failed to parse:" in completed.stdout
        assert "broken.py" in completed.stdout
        assert "invalid syntax" in completed.stdout.lower()

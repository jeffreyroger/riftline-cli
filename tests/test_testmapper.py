import subprocess
import sys
import unittest
from pathlib import Path

from riftline.testmapper import suggest_test_file

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "fixtures" / "testmapped_pkg"


class TestSuggestTestFile(unittest.TestCase):
    def test_positive_case_finds_real_existing_file(self) -> None:
        result = suggest_test_file(FIXTURE / "core.py")
        expected = FIXTURE / "tests" / "test_core.py"
        self.assertEqual(result, str(expected))
        self.assertTrue(Path(result).is_file(), "suggested path must actually exist on disk")

    def test_negative_case_returns_none_when_nothing_matches(self) -> None:
        result = suggest_test_file(FIXTURE / "orphan.py")
        self.assertIsNone(result)

    def test_never_fabricates_a_nonexistent_path(self) -> None:
        result = suggest_test_file(FIXTURE / "does_not_exist_at_all.py")
        self.assertIsNone(result)


class TestCliWiring(unittest.TestCase):
    def _run_impact(self, symbol: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "riftline.cli", "impact", symbol, "--path", str(FIXTURE)],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            check=False,
        )

    def test_impact_shows_suggestion_for_function_with_matching_test(self) -> None:
        completed = self._run_impact("compute")
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        self.assertIn("Possible related tests (unverified, naming-convention only):", completed.stdout)
        self.assertIn("test_core.py", completed.stdout)

    def test_impact_shows_no_suggestion_for_orphan_function(self) -> None:
        completed = self._run_impact("lonely_function")
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        self.assertIn("Possible related tests (unverified, naming-convention only):", completed.stdout)
        self.assertIn("no matching test file found", completed.stdout)


if __name__ == "__main__":
    unittest.main()

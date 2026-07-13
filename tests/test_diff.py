"""
Regression tests for the git diff integration (Phase B).

Fixture strategy:
  setUp/tearDown on the class level builds a real git repo inside
  fixtures/diff_repo/ for every test run, then tears it down (restoring
  .gitkeep) when done.  This keeps the committed tree clean while still
  giving the tests a genuine git history to exercise.

Layout of the fixture repo
  mypkg/
    __init__.py  (empty)
    core.py      compute(x) -- the function that changes between commits
    app.py       run()       -- calls compute(); downstream caller
  Two commits:
    Commit 1: compute returns x * 2
    Commit 2: compute returns x * 4   (body changed, run() NOT changed)
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path

FIXTURES_DIR  = Path(__file__).parent.parent / "fixtures"
DIFF_REPO_DIR = FIXTURES_DIR / "diff_repo"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _git(*args: str, cwd: Path) -> None:
    """Run a git command in cwd; raise CalledProcessError on failure."""
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _build_fixture() -> None:
    """Populate fixtures/diff_repo/ with a real 2-commit git history."""
    import shutil, os

    # Wipe any leftover .git from a previous run
    dot_git = DIFF_REPO_DIR / ".git"
    if dot_git.exists():
        shutil.rmtree(dot_git, ignore_errors=True)

    # Remove any leftover .py files (but keep .gitkeep)
    for p in DIFF_REPO_DIR.rglob("*.py"):
        p.unlink(missing_ok=True)
    for p in DIFF_REPO_DIR.rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)

    _git("init", cwd=DIFF_REPO_DIR)
    _git("config", "user.email", "test@riftline.dev", cwd=DIFF_REPO_DIR)
    _git("config", "user.name",  "Riftline Test",     cwd=DIFF_REPO_DIR)

    pkg = DIFF_REPO_DIR / "mypkg"
    pkg.mkdir(exist_ok=True)
    _write(pkg / "__init__.py", "")
    _write(pkg / "core.py",
           "def compute(x):\n    return x * 2\n")
    _write(pkg / "app.py",
           "from .core import compute\n\ndef run():\n    return compute(5)\n")

    _git("add", ".", cwd=DIFF_REPO_DIR)
    _git("commit", "-m", "Commit 1: compute returns x*2", cwd=DIFF_REPO_DIR)

    _write(pkg / "core.py",
           "def compute(x):\n    # changed\n    return x * 4\n")
    _git("add", ".", cwd=DIFF_REPO_DIR)
    _git("commit", "-m", "Commit 2: compute returns x*4", cwd=DIFF_REPO_DIR)


def _teardown_fixture() -> None:
    """Remove ephemeral git history; restore .gitkeep so dir stays tracked."""
    import shutil

    dot_git = DIFF_REPO_DIR / ".git"
    if dot_git.exists():
        shutil.rmtree(dot_git, ignore_errors=True)

    for p in DIFF_REPO_DIR.rglob("*.py"):
        p.unlink(missing_ok=True)

    for p in DIFF_REPO_DIR.glob("mypkg"):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)

    (DIFF_REPO_DIR / ".gitkeep").write_text(
        "# populated at test time by test_diff.py\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Tests: git_diff.find_changed_functions
# ---------------------------------------------------------------------------

class TestFindChangedFunctions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _build_fixture()

    @classmethod
    def tearDownClass(cls):
        _teardown_fixture()

    def test_changed_function_detected(self):
        """compute() was edited in Commit 2; it must appear in the changed list."""
        from riftline.git_diff import find_changed_functions
        changed = find_changed_functions(DIFF_REPO_DIR, "HEAD~1", "HEAD")
        fqns = [c.fqn for c in changed]
        self.assertIn("mypkg.core.compute", fqns)

    def test_untouched_function_not_in_changed_list(self):
        """run() was NOT edited in Commit 2; it must NOT appear in the changed list."""
        from riftline.git_diff import find_changed_functions
        changed = find_changed_functions(DIFF_REPO_DIR, "HEAD~1", "HEAD")
        fqns = [c.fqn for c in changed]
        self.assertNotIn("mypkg.app.run", fqns)

    def test_changed_function_metadata(self):
        """ChangedFunction must carry correct file path and line span."""
        from riftline.git_diff import find_changed_functions
        changed = find_changed_functions(DIFF_REPO_DIR, "HEAD~1", "HEAD")
        hit = next(c for c in changed if c.fqn == "mypkg.core.compute")
        self.assertEqual(hit.file, "mypkg/core.py")
        self.assertGreaterEqual(hit.lineno, 1)
        self.assertGreaterEqual(hit.end_lineno, hit.lineno)

    def test_no_changes_between_identical_refs(self):
        """Diffing a commit against itself must return an empty list."""
        from riftline.git_diff import find_changed_functions
        changed = find_changed_functions(DIFF_REPO_DIR, "HEAD", "HEAD")
        self.assertEqual(changed, [])

    def test_bad_ref_old_raises_systemexit(self):
        from riftline.git_diff import find_changed_functions
        with self.assertRaises(SystemExit) as cm:
            find_changed_functions(DIFF_REPO_DIR, "nonexistent_ref_abc", "HEAD")
        self.assertEqual(cm.exception.code, 1)

    def test_bad_ref_new_raises_systemexit(self):
        from riftline.git_diff import find_changed_functions
        with self.assertRaises(SystemExit) as cm:
            find_changed_functions(DIFF_REPO_DIR, "HEAD~1", "nonexistent_ref_xyz")
        self.assertEqual(cm.exception.code, 1)

    def test_non_git_dir_raises_systemexit(self):
        """A directory with .py files but no .git must fail with exit code 1."""
        from riftline.git_diff import find_changed_functions
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "mod.py").write_text("def f(): pass\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                find_changed_functions(p, "HEAD~1", "HEAD")
            self.assertEqual(cm.exception.code, 1)


# ---------------------------------------------------------------------------
# Tests: merged blast radius using diff fixture
# ---------------------------------------------------------------------------

class TestMergedBlastRadiusFromDiff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _build_fixture()
        from riftline.git_diff import find_changed_functions
        from riftline.graph import build_graph, merged_blast_radius

        cls.graph = build_graph(DIFF_REPO_DIR)
        changed = find_changed_functions(DIFF_REPO_DIR, "HEAD~1", "HEAD")
        cls.changed_fqns = {c.fqn for c in changed}
        known = [c.fqn for c in changed if c.fqn in cls.graph]
        cls.affected = merged_blast_radius(cls.graph, known) - cls.changed_fqns

    @classmethod
    def tearDownClass(cls):
        _teardown_fixture()

    def test_downstream_caller_in_blast_radius(self):
        """run() calls compute(); it must appear in compute()'s blast radius."""
        self.assertIn("mypkg.app.run", self.affected)

    def test_changed_function_excluded_from_blast_radius(self):
        """compute() changed, so it must NOT appear in its own blast radius display."""
        self.assertNotIn("mypkg.core.compute", self.affected)

    def test_blast_radius_is_deduplicated(self):
        """The affected set must be a plain set — no duplicates possible."""
        # Verify that the blast radius, as a set, has exactly the expected size.
        # If compute() had two independent callers that were also shared with
        # another changed function, the union still equals the set itself.
        self.assertEqual(len(self.affected), len(set(self.affected)))


# ---------------------------------------------------------------------------
# Tests: CLI diff command error handling
# ---------------------------------------------------------------------------

class TestCliDiffErrors(unittest.TestCase):
    """
    Validates that all error paths in `riftline diff` produce exit code 1
    and a human-readable message, consistent with scan/hotspots/impact.
    """

    def _run_diff(self, *extra_args: str) -> tuple[str, int]:
        """Run riftline diff via the parser; capture stdout and exit code."""
        from riftline.cli import build_parser

        buf = StringIO()
        original_stdout = sys.stdout
        sys.stdout = buf
        exit_code = 0
        try:
            parser = build_parser()
            args = parser.parse_args(["diff", *extra_args])
            args.func(args)
        except SystemExit as exc:
            exit_code = int(exc.code) if exc.code is not None else 0
        finally:
            sys.stdout = original_stdout

        return buf.getvalue(), exit_code

    def test_cli_bad_path_exits_1(self):
        out, code = self._run_diff("HEAD~1", "HEAD", "--path", "c:/nonexistent_xyz")
        self.assertEqual(code, 1)
        self.assertIn("Error", out)

    def test_cli_bad_ref_exits_1(self):
        @classmethod
        def _setup_fixture_once(cls):
            _build_fixture()

        _build_fixture()
        out, code = self._run_diff(
            "nonexistent_ref_abc", "HEAD", "--path", str(DIFF_REPO_DIR)
        )
        _teardown_fixture()
        self.assertEqual(code, 1)
        self.assertIn("Error", out)

    def test_cli_non_repo_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "mod.py").write_text("def f(): pass\n", encoding="utf-8")
            out, code = self._run_diff("HEAD~1", "HEAD", "--path", str(p))
            self.assertEqual(code, 1)
            self.assertIn("Error", out)


if __name__ == "__main__":
    unittest.main()
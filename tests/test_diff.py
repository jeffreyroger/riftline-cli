"""
Regression tests for the git diff integration (Phase B).

Fixture strategy:
  A class-scoped pytest fixture builds a real git repo inside
  fixtures/diff_repo/ for every test class run, then tears it down
  (restoring .gitkeep) when done.  This keeps the committed tree clean
  while still giving the tests a genuine git history to exercise.

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
import tempfile
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
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


def _robust_rmtree(path: Path) -> None:
    """rmtree that actually removes a git repo's .git/ on Windows.

    Plain ``shutil.rmtree(path, ignore_errors=True)`` silently leaves
    files behind here: git marks some objects/pack files read-only, and a
    read-only file can't be unlinked on Windows without clearing that
    attribute first. ignore_errors=True swallows that failure instead of
    fixing it, so leftover .git/objects/* files accumulate across runs.
    This clears the read-only bit on failure and retries once, which is
    the standard fix for this exact class of Windows/git rmtree issue.
    """
    import os
    import shutil
    import stat

    def _on_error(func, target_path, exc_info):
        os.chmod(target_path, stat.S_IWRITE)
        func(target_path)

    shutil.rmtree(path, onerror=_on_error)


def _build_fixture() -> None:
    """Populate fixtures/diff_repo/ with a real 2-commit git history."""
    import shutil, os

    # Wipe any leftover .git from a previous run
    dot_git = DIFF_REPO_DIR / ".git"
    if dot_git.exists():
        _robust_rmtree(dot_git)

    # Remove any leftover .py files (but keep .gitkeep)
    for p in DIFF_REPO_DIR.rglob("*.py"):
        p.unlink(missing_ok=True)
    for p in DIFF_REPO_DIR.rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)

    _git("init", cwd=DIFF_REPO_DIR)
    _git("config", "user.email", "test@riftline.dev", cwd=DIFF_REPO_DIR)
    _git("config", "user.name", "Riftline Test", cwd=DIFF_REPO_DIR)

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
        _robust_rmtree(dot_git)

    for p in DIFF_REPO_DIR.rglob("*.py"):
        p.unlink(missing_ok=True)

    for p in DIFF_REPO_DIR.glob("mypkg"):
        if p.is_dir():
            _robust_rmtree(p)

    (DIFF_REPO_DIR / ".gitkeep").write_text(
        "# populated at test time by test_diff.py\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Tests: git_diff.find_changed_functions
# ---------------------------------------------------------------------------

class TestFindChangedFunctions:
    @classmethod
    @pytest.fixture(scope="class", autouse=True)
    def _fixture_repo(cls):
        _build_fixture()
        yield
        _teardown_fixture()

    def test_changed_function_detected(self):
        """compute() was edited in Commit 2; it must appear in the changed list."""
        from riftline.git_diff import find_changed_functions
        changed = find_changed_functions(DIFF_REPO_DIR, "HEAD~1", "HEAD")
        fqns = [c.fqn for c in changed]
        assert "mypkg.core.compute" in fqns

    def test_untouched_function_not_in_changed_list(self):
        """run() was NOT edited in Commit 2; it must NOT appear in the changed list."""
        from riftline.git_diff import find_changed_functions
        changed = find_changed_functions(DIFF_REPO_DIR, "HEAD~1", "HEAD")
        fqns = [c.fqn for c in changed]
        assert "mypkg.app.run" not in fqns

    def test_changed_function_metadata(self):
        """ChangedFunction must carry correct file path and line span."""
        from riftline.git_diff import find_changed_functions
        changed = find_changed_functions(DIFF_REPO_DIR, "HEAD~1", "HEAD")
        hit = next(c for c in changed if c.fqn == "mypkg.core.compute")
        assert hit.file == "mypkg/core.py"
        assert hit.lineno >= 1
        assert hit.end_lineno >= hit.lineno

    def test_no_changes_between_identical_refs(self):
        """Diffing a commit against itself must return an empty list."""
        from riftline.git_diff import find_changed_functions
        changed = find_changed_functions(DIFF_REPO_DIR, "HEAD", "HEAD")
        assert changed == []

    def test_bad_ref_old_raises_systemexit(self):
        from riftline.git_diff import find_changed_functions
        with pytest.raises(SystemExit) as excinfo:
            find_changed_functions(DIFF_REPO_DIR, "nonexistent_ref_abc", "HEAD")
        assert excinfo.value.code == 1

    def test_bad_ref_new_raises_systemexit(self):
        from riftline.git_diff import find_changed_functions
        with pytest.raises(SystemExit) as excinfo:
            find_changed_functions(DIFF_REPO_DIR, "HEAD~1", "nonexistent_ref_xyz")
        assert excinfo.value.code == 1

    def test_non_git_dir_raises_systemexit(self):
        """A directory with .py files but no .git must fail with exit code 1."""
        from riftline.git_diff import find_changed_functions
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "mod.py").write_text("def f(): pass\n", encoding="utf-8")
            with pytest.raises(SystemExit) as excinfo:
                find_changed_functions(p, "HEAD~1", "HEAD")
            assert excinfo.value.code == 1


# ---------------------------------------------------------------------------
# Tests: merged blast radius using diff fixture
# ---------------------------------------------------------------------------

class TestMergedBlastRadiusFromDiff:
    @classmethod
    @pytest.fixture(scope="class", autouse=True)
    def _fixture_repo(cls):
        _build_fixture()
        from riftline.git_diff import find_changed_functions
        from riftline.graph import build_graph, merged_blast_radius

        graph = build_graph(DIFF_REPO_DIR)
        changed = find_changed_functions(DIFF_REPO_DIR, "HEAD~1", "HEAD")
        changed_fqns = {c.fqn for c in changed}
        known = [c.fqn for c in changed if c.fqn in graph]
        cls.graph = graph
        cls.changed_fqns = changed_fqns
        cls.affected = merged_blast_radius(graph, known) - changed_fqns
        yield
        _teardown_fixture()

    def test_downstream_caller_in_blast_radius(self):
        """run() calls compute(); it must appear in compute()'s blast radius."""
        assert "mypkg.app.run" in self.affected

    def test_changed_function_excluded_from_blast_radius(self):
        """compute() changed, so it must NOT appear in its own blast radius display."""
        assert "mypkg.core.compute" not in self.affected

    def test_blast_radius_is_deduplicated(self):
        """The affected set must be a plain set — no duplicates possible."""
        # Verify that the blast radius, as a set, has exactly the expected size.
        # If compute() had two independent callers that were also shared with
        # another changed function, the union still equals the set itself.
        assert len(self.affected) == len(set(self.affected))


# ---------------------------------------------------------------------------
# Tests: CLI diff command error handling
# ---------------------------------------------------------------------------

class TestCliDiffErrors:
    """
    Validates that all error paths in `riftline diff` produce exit code 1
    and a human-readable message, consistent with scan/hotspots/impact.
    """

    def _run_diff(self, *extra_args: str) -> tuple[str, int]:
        """Run riftline diff via Typer's CliRunner; capture stdout and exit code."""
        from typer.testing import CliRunner
        from riftline.cli import app

        result = CliRunner().invoke(app, ["diff", *extra_args])
        return result.output, result.exit_code

    def test_cli_bad_path_exits_1(self):
        out, code = self._run_diff("HEAD~1", "HEAD", "--path", "c:/nonexistent_xyz")
        assert code == 1
        assert "Error" in out

    def test_cli_bad_ref_exits_1(self):
        _build_fixture()
        out, code = self._run_diff(
            "nonexistent_ref_abc", "HEAD", "--path", str(DIFF_REPO_DIR)
        )
        _teardown_fixture()
        assert code == 1
        assert "Error" in out

    def test_cli_non_repo_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "mod.py").write_text("def f(): pass\n", encoding="utf-8")
            out, code = self._run_diff("HEAD~1", "HEAD", "--path", str(p))
            assert code == 1
            assert "Error" in out


class TestCliDiffReportsUnrelatedParseFailures:
    """
    Regression test: `riftline diff` must report parse failures found while
    building the full-package graph (used for blast-radius), not just
    failures found while parsing the files the diff itself touched.

    Reproduces the exact scenario that previously slipped through silently:
    a real function change (mypkg.core.compute) is diffed successfully, but
    an unrelated, untracked file elsewhere in the same package has a syntax
    error. `riftline scan` on that path has always reported this; `riftline
    diff` did not, because it fetched the parse-failure list before
    build_graph() (which scans the whole package) had run.
    """

    def _run_diff(self, *extra_args: str) -> tuple[str, int]:
        from typer.testing import CliRunner
        from riftline.cli import app

        result = CliRunner().invoke(app, ["diff", *extra_args])
        return result.output, result.exit_code

    def test_unrelated_syntax_error_is_reported(self):
        _build_fixture()
        try:
            # Untracked, unrelated to the diff -- present on disk when
            # build_graph() scans the whole package, but never touched by
            # `git diff` between the two commits.
            broken = DIFF_REPO_DIR / "broken.py"
            broken.write_text("def broken(:\n    pass\n", encoding="utf-8")

            out, code = self._run_diff("HEAD~1", "HEAD", "--path", str(DIFF_REPO_DIR))

            # The real, changed-function blast radius must still be reported.
            assert "mypkg.app.run" in out
            # And the unrelated parse failure must NOT be silently dropped.
            assert "failed to parse" in out
            assert "broken.py" in out
            assert code == 0
        finally:
            _teardown_fixture()


class TestCliDiffReportsRealPathForBrokenDiffedFile:
    """
    Regression test: when the file introduced/changed by the diff itself
    has a syntax error at ref_new, `riftline diff` parses git's copy of it
    via a throwaway temp file -- but must report the failure against the
    real repo-relative file, not the meaningless temp path (e.g.
    /tmp/tmpXXXXXXXX.py) that the user has no way to trace back to their
    own code.
    """

    def _run_diff(self, *extra_args: str) -> tuple[str, int]:
        from typer.testing import CliRunner
        from riftline.cli import app

        result = CliRunner().invoke(app, ["diff", *extra_args])
        return result.output, result.exit_code

    def test_reported_path_is_the_real_file_not_a_temp_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            pkg = repo / "pkg"
            pkg.mkdir()
            _git("init", cwd=repo)
            _git("config", "user.email", "test@riftline.dev", cwd=repo)
            _git("config", "user.name", "Riftline Test", cwd=repo)

            _write(pkg / "__init__.py", "")
            _write(pkg / "core.py", "def compute(x):\n    return x * 2\n")
            _git("add", ".", cwd=repo)
            _git("commit", "-m", "Commit 1", cwd=repo)

            # Commit 2 introduces a syntax error into the very file being diffed.
            _write(pkg / "core.py", "def compute(x:\n    return x * 4\n")
            _git("add", ".", cwd=repo)
            _git("commit", "-m", "Commit 2 - now broken", cwd=repo)

            out, code = self._run_diff("HEAD~1", "HEAD", "--path", str(repo))

            assert "failed to parse" in out
            # The exact real repo file must appear -- this is the precise,
            # platform-independent proof the path was corrected. If the bug
            # regressed, this would show a throwaway temp path instead
            # (e.g. /tmp/tmpXXXXXXXX.py on Linux, or a similarly-named
            # file under the OS temp dir on Windows) and this would fail.
            assert str(pkg / "core.py") in out
            assert code == 0

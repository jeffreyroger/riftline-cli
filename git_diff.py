"""
Git diff integration for riftline.

Maps the unified diff between two git refs to the set of Python
function/method definitions whose bodies were touched (line-range overlap
between diff hunks and the function's lineno/end_lineno from parser.py).

Design constraints (matching the rest of riftline):
  - subprocess + git CLI only -- no GitPython or any new pip dependency.
  - Only imports from parser.py (for parse() and FunctionInfo).
    Does NOT import from resolver.py or graph.py so this module stays
    independent of graph-construction concerns.
  - Fails loudly on bad input (non-git directory, nonexistent refs) with a
    clear, actionable message -- never crashes with a raw exception or
    silently returns an empty list when the real cause is an error.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .parser import parse


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChangedFunction:
    """A function/method whose body overlapped with at least one diff hunk."""

    fqn: str        # fully-qualified name, e.g. "mypkg.core.MyClass.method"
    file: str       # repo-relative path,   e.g. "mypkg/core.py"
    lineno: int     # first line of the function in ref_new
    end_lineno: int # last  line of the function in ref_new


# ---------------------------------------------------------------------------
# Internal: git plumbing helpers
# ---------------------------------------------------------------------------

def _run_git(*args: str, cwd: Path) -> tuple[str, str, int]:
    """Run a git sub-command; return (stdout, stderr, returncode)."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout, result.stderr, result.returncode


def _assert_git_repo(path: Path) -> None:
    """Exit with a clear message if path is not inside a git repository."""
    _, stderr, code = _run_git("rev-parse", "--git-dir", cwd=path)
    if code != 0:
        print(f"Error: '{path}' is not inside a git repository.")
        print(
            "  Make sure the path points at a git-tracked project "
            "(look for a .git folder in the directory or its parents)."
        )
        if stderr.strip() and "not a git repository" not in stderr.lower():
            print(f"  git said: {stderr.strip()}")
        raise SystemExit(1)


def _assert_ref_exists(path: Path, ref: str) -> None:
    """Exit with a clear message if ref does not exist in the repo."""
    _, stderr, code = _run_git("rev-parse", "--verify", ref, cwd=path)
    if code != 0:
        print(f"Error: git ref '{ref}' does not exist in the repository at '{path}'.")
        print(
            "  Run 'git log --oneline' to see valid commits, "
            "or 'git branch -a' for branch names."
        )
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Internal: unified-diff parsing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Hunk:
    """One @@ entry, expressed in the NEW file's line coordinate system."""

    rel_path: str  # repo-relative path of the file this hunk belongs to
    start: int     # first line touched (1-indexed, inclusive) in the new file
    end: int       # last  line touched (1-indexed, inclusive) in the new file


# Matches:  +++ b/some/path.py
_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")

# Matches:  @@ -OLD_START[,OLD_COUNT] +NEW_START[,NEW_COUNT] @@
# The comma+count parts are optional (omitted when count == 1).
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _parse_diff_hunks(diff_text: str) -> list[_Hunk]:
    """
    Parse "git diff --unified=0" output into a flat list of _Hunk objects,
    each carrying the new-file line range [start, end] (both 1-indexed and
    inclusive).

    Handles all three kinds of hunks:
      - Normal change:  +N,C  => [N, N+C-1]
      - Pure insertion: +N,C  => [N, N+C-1]  (same formula)
      - Pure deletion:  +N,0  => [N, N]  (single-point anchor so overlap
                                          with the surrounding function fires)

    Only .py files are emitted; binary/non-Python files are skipped.
    """
    hunks: list[_Hunk] = []
    current_file: str | None = None  # None means "current file is not .py"

    for line in diff_text.splitlines():
        m = _FILE_RE.match(line)
        if m:
            rel = m.group(1)
            current_file = rel if rel.endswith(".py") else None
            continue

        if current_file is None:
            continue

        m = _HUNK_RE.match(line)
        if m:
            start = int(m.group(1))
            count_str = m.group(2)
            # No comma means count == 1; explicit ",0" means pure deletion.
            count = int(count_str) if count_str is not None else 1
            end = start if count == 0 else start + count - 1
            hunks.append(_Hunk(rel_path=current_file, start=start, end=end))

    return hunks


# ---------------------------------------------------------------------------
# Internal: overlap & module name helpers
# ---------------------------------------------------------------------------

def _overlaps(h: _Hunk, fn_start: int, fn_end: int) -> bool:
    """True if hunk [h.start, h.end] and function [fn_start, fn_end] overlap."""
    return h.start <= fn_end and h.end >= fn_start


def _module_name(root: Path, abs_path: Path) -> str:
    """
    Convert an absolute file path to a dotted module name relative to root.

    Intentionally re-implemented here (instead of importing from resolver.py)
    so git_diff.py stays isolated from graph-construction code, per the
    design constraint at the top of this file.
    """
    rel = abs_path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_changed_functions(
    root: Path,
    ref_old: str = "HEAD~1",
    ref_new: str = "HEAD",
) -> list[ChangedFunction]:
    """
    Return every function/method whose body overlaps with at least one diff
    hunk between ref_old and ref_new in the git repository at root.

    Algorithm:
      1. Validate: root is a git repo; both refs exist.
      2. "git diff --unified=0 ref_old ref_new -- *.py"
         (--unified=0 gives the tightest possible hunk ranges so that
         an edit to function A does not accidentally pull in function B.)
      3. Parse the unified diff to get (file, new_start, new_end) hunks.
      4. For each changed .py file, retrieve its content at ref_new via
         "git show ref_new:path", write to a temp file, parse with
         parser.parse() to get exact function line spans.
      5. Report every function whose [lineno, end_lineno] intersects a hunk.

    Fails with SystemExit(1) + a clear error message if:
      - root is not a git repository
      - ref_old or ref_new does not exist in the repo
      - git diff itself returns an unexpected exit code
    """
    root = root.resolve()
    _assert_git_repo(root)
    _assert_ref_exists(root, ref_old)
    _assert_ref_exists(root, ref_new)

    stdout, stderr, code = _run_git(
        "diff", "--unified=0", ref_old, ref_new, "--", "*.py",
        cwd=root,
    )
    # git diff exits 0 when there are no changes, 1 when there are changes.
    # Any other exit code is a real error.
    if code > 1:
        print(f"Error: 'git diff' failed (exit code {code}).")
        if stderr.strip():
            print(f"  git said: {stderr.strip()}")
        raise SystemExit(1)

    if not stdout.strip():
        return []  # no Python changes between the two refs

    hunks = _parse_diff_hunks(stdout)
    if not hunks:
        return []  # diff had output but none of it was .py files

    # Group hunks by the file they belong to.
    hunks_by_file: dict[str, list[_Hunk]] = {}
    for h in hunks:
        hunks_by_file.setdefault(h.rel_path, []).append(h)

    changed: list[ChangedFunction] = []

    for rel_path, file_hunks in sorted(hunks_by_file.items()):
        # Get the file content at ref_new so we analyse the NEW function spans.
        content, show_err, show_code = _run_git(
            "show", f"{ref_new}:{rel_path}", cwd=root
        )
        if show_code != 0:
            # File was deleted in ref_new -- nothing to parse in the new version.
            continue

        # Write to a temp file and parse with the existing parse() pipeline.
        # Strip UTF-8 BOM (\ufeff) that git show may emit when the original
        # file was saved with BOM (common on Windows editors / PowerShell
        # Out-File -Encoding utf8).
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(content.lstrip("\ufeff"))
                tmp_path = Path(tmp.name)

            parsed = parse(tmp_path)
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        abs_path = root / rel_path
        try:
            module = _module_name(root, abs_path)
        except ValueError:
            # abs_path is somehow not under root -- use the repo-relative path.
            module = Path(rel_path).with_suffix("").as_posix().replace("/", ".")

        # Emit each function at most once, even if multiple hunks overlap it.
        seen_fqns: set[str] = set()
        for fn in parsed.functions:
            fqn = f"{module}.{fn.name}"
            if fqn in seen_fqns:
                continue
            for h in file_hunks:
                if _overlaps(h, fn.lineno, fn.end_lineno):
                    changed.append(
                        ChangedFunction(
                            fqn=fqn,
                            file=rel_path,
                            lineno=fn.lineno,
                            end_lineno=fn.end_lineno,
                        )
                    )
                    seen_fqns.add(fqn)
                    break  # one hunk match is enough; move to next function

    return changed

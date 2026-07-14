# Riftline

Know what breaks before you break it.

Riftline parses a Python package into a function-level dependency graph and
lets you ask "if I change function X, what else breaks?" before you touch it —
either by name, by scanning for riskiest chokepoints, or by pointing it at a
git diff.

## Commands

```bash
pip install -e .

riftline scan    <path>                      # graph summary: resolved/unresolved edge counts
riftline hotspots <path> [--limit N]         # rank functions by blast-radius size
riftline impact  <symbol> [--path <path>]   # blast radius of a single function
riftline diff    <base-ref> <head-ref> [--path <path>]  # blast radius of a git diff
```

### `riftline scan`

```
riftline scan fixtures
```
```
Scanned: C:\riftline\fixtures
  functions found : 9
  edges resolved  : 7
  edges unresolved: 3  (flagged, not guessed)
```

### `riftline hotspots`

Ranks every function by blast-radius size — no symbol name needed.

```
riftline hotspots fixtures
```
```
Top 4 riskiest functions in fixtures (by blast-radius size):
  mini_pkg.core.low_level   3 dependent(s)
  mini_pkg.utils.helper     2 dependent(s)
  mini_pkg.main.foo         1 dependent(s)
```

`core.low_level` is 3 hops from `app.run` with no direct import — the graph
traces the full chain anyway.

### `riftline impact`

Blast radius of a single named function.  Short names auto-resolve if unambiguous.

```
riftline impact low_level --path fixtures
```
```
(matched 'low_level' -> mini_pkg.core.low_level)
Blast radius of mini_pkg.core.low_level:
  - mini_pkg.app.run
  - mini_pkg.main.foo
  - mini_pkg.utils.helper
```

If a short name matches more than one function, every match is listed and
the command exits with a non-zero code:

```
'transform' is ambiguous -- 2 functions match:
  - mypkg.extra.other.transform
  - mypkg.processing.transformers.transform
Re-run with one of the full names above.
```

### `riftline diff`

Maps a git diff to changed functions and their combined blast radius.
Takes two git refs (commit SHAs, branch names, `HEAD~N`, tags).

```
riftline diff HEAD~1 HEAD --path /path/to/repo
```

**Example** — a repo where `compute()` was edited and `run()` calls it:

```
(changed functions: mypkg.core.compute)
Blast radius of changed functions between HEAD~1 and HEAD:
  - mypkg.app.run
```

If no Python function bodies changed between the two refs:

```
No Python function changes detected between 'HEAD~1' and 'HEAD'.
```

If the changed functions have no callers anywhere in the scanned package:

```
(changed functions: mypkg.core.leaf)
No known dependents of changed functions between HEAD~1 and HEAD. Safe to change in isolation.
```

**Error handling** — clear, actionable messages for every bad-input case:

```
# Bad path
Error: path does not exist: /nonexistent
Check for a typo, or run 'dir' (Windows) / 'ls' (Mac/Linux) to see what's actually there.

# Non-git directory
Error: '/some/plain/dir' is not inside a git repository.
  Make sure the path points at a git-tracked project (look for a .git folder in the directory or its parents).

# Bad ref
Error: git ref 'mybranch' does not exist in the repository at '/path/to/repo'.
  Run 'git log --oneline' to see valid commits, or 'git branch -a' for branch names.
```

## Architecture

Four layers, each depending only on the output types of the layer below:

```
parser.py   →  resolver.py  →  graph.py  →  cli.py
                                              |
                               git_diff.py ──┘
```

| File | Responsibility |
|---|---|
| `parser.py` | AST walk: imports, function defs, bare-name calls, attribute/method calls |
| `resolver.py` | Cross-file import chaining → resolved edges or explicit `unknown:` nodes |
| `graph.py` | networkx DiGraph; `blast_radius`, `merged_blast_radius`, `hotspots`, `find_symbol` |
| `git_diff.py` | `git diff --unified=0` → changed-function list via line-span overlap |
| `cli.py` | `riftline` command: `scan / hotspots / impact / diff` |

## Test fixtures

| Fixture | Purpose |
|---|---|
| `fixtures/mini_pkg/` | 4-file chain (`app→main→utils→core`), one unresolved call — regression baseline, never modified |
| `fixtures/oop_pkg/` | OOP: `self.foo()` resolution, single-inheritance chains, dynamic-attribute unresolved cases |
| `fixtures/diff_repo/` | Ephemeral — built and torn down by `tests/test_diff.py`; committed tree contains only `.gitkeep` |

## Running the tests

```bash
python -m unittest discover -s tests -v
```

Current count: **39 tests, all passing**.

## Known limitations (by design)

- **Star imports in re-exports** — star imports (e.g. `from .submodule import *`) in `__init__.py` files are not resolved statically and are explicitly flagged `unresolved`, consistent with the guiding principle of never guessing.
- **Multiple inheritance** — `self.method()` resolution walks single-inheritance
  chains only.  Multiple inheritance is flagged `unresolved` with a clear reason,
  never guessed.
- **Dynamic attribute targets** — `self.attr.method()` and untyped-variable calls
  remain `unresolved` (correct per §1.4 of the SRS: *never present a guess as a fact*).
- **Python only** — `parser.py` uses stdlib `ast`; tree-sitter is the planned
  swap for multi-language support once package installation is confirmed.
- **Cross-package calls** — calls into third-party or installed packages always
  resolve as `unknown:<name>`, which is correct behavior, not a missing feature.

## Implementation substitutions

Three stdlib stand-ins are used pending confirmed package availability.
Each is scoped to exactly one file so they can be reversed without touching
the graph logic:

| Planned | Using instead | Scope |
|---|---|---|
| `tree-sitter` | `ast` (stdlib) | `parser.py` only |
| `typer` + `rich` | `argparse` + `print` | `cli.py` only |
| `pytest` | `unittest` | `tests/` only |
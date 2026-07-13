# Riftline

Know what breaks before you break it.

Riftline parses a Python package into a dependency graph — who calls whom,
resolved across files — so you can ask "if I change function X, what's the
full blast radius?" before you touch it.

## What's actually here (Week 1 deliverable)

- `riftline/parser.py` — parses each file, extracts its import table and
  every function's raw calls.
- `riftline/resolver.py` — chains a file's import table with every other
  file's symbol table to turn raw call names into resolved, fully-qualified
  edges. Anything it can't verify is flagged `unresolved`, never guessed.
- `riftline/graph.py` — scans a whole package, builds a `networkx.DiGraph`,
  and answers blast-radius queries via `nx.ancestors`.
- `riftline/cli.py` — the actual `riftline` command.
- `fixtures/mini_pkg/` — a 4-file chain (`app → main → utils → core`) plus
  one deliberately unresolved call, used by the tests and as a live demo.
- `tests/test_graph.py` — 7 regression tests, all passing.

## Quick start

```bash
pip install -e .
riftline scan fixtures
riftline hotspots fixtures
riftline impact low_level --path fixtures
```

`riftline impact` no longer requires the exact dotted path — `low_level`
auto-resolves to `mini_pkg.core.low_level` if it's unambiguous. If a short
name matches more than one function, it lists every match instead of
guessing:

```
'transform' is ambiguous -- 2 functions match:
  - mypkg.extra.other.transform
  - mypkg.processing.transformers.transform
Re-run with one of the full names above.
```

`riftline hotspots` is the "no symbol name needed" entry point — it ranks
every function by blast-radius size, so you can see your riskiest
chokepoints before you even know what to ask about:

```
Top 4 riskiest functions in fixtures (by blast-radius size):
  mini_pkg.core.low_level   3 dependent(s)
  mini_pkg.utils.helper     2 dependent(s)
  mini_pkg.main.foo         1 dependent(s)
```

`core.low_level` is 3 hops deep — `app.run` has no direct import of `core`
at all — but the graph traces the full chain anyway.

## Known substitutions (read before continuing the build)

This sandbox has no network access, so two dependencies from the original
plan were swapped for stdlib equivalents. Both are drop-in replacements
scoped to a single file each:

| Planned | Used instead | Swap scope |
|---|---|---|
| `tree-sitter` (multi-language AST) | `ast` (stdlib, Python-only) | `parser.py` only |
| `typer` + `rich` (CLI/output) | `argparse` + `print` (stdlib) | `cli.py` only |
| `pytest` | `unittest` (stdlib) | `tests/test_graph.py` only |

Nothing about `resolver.py` or `graph.py` — the actual hard part — depends
on any of these. Once you have network access, `pip install tree-sitter
tree-sitter-python typer rich pytest` and swap those three files; the
graph/resolution logic doesn't change.

## Known limitations (by design, not oversight)

- **Attribute/method-call resolution limits.** Method-call resolution is supported for `self` calls and single inheritance chains. Multiple inheritance and dynamic attribute targets (e.g. `self.attr.method()`, or variables with untyped sources) remain unresolved-by-design, appearing in the graph as unresolved edges with clear reason annotations.
- **No git diff integration yet.** `riftline diff` is a stub. `graph.py`
  already has `function_at_line()` ready for it — git diff gives you
  changed line numbers, and every function's line span was already
  extracted in `parser.py`, so this is mostly wiring, not new design.
- **Single-package scope.** Cross-package resolution (calls into installed
  third-party libraries) is intentionally out of scope — those always
  resolve as `unknown:<name>`, which is correct behavior, not a bug.

## What's next (Week 2+, per the implementation plan)

1. Class/method call resolution (`self.foo()`, `instance.method()`)
2. `git diff` → changed lines → affected functions (wire up
   `function_at_line`)
3. Test-file mapping (affected function → likely test file via naming
   convention)
4. Mermaid/Graphviz export of the dependency graph
5. Confidence-rate benchmark on a real multi-hundred-file repo

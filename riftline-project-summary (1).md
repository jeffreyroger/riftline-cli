# Riftline — Project Context & Summary

*For anyone (human or AI agent) picking this project up without the
original conversation history.*

---

## What this is

Riftline is a command-line tool that answers one question: **"if I change
this function, what else in my codebase depends on it?"** It is a static
analyzer for Python that builds a cross-file, function-level call graph
and lets you query the transitive "blast radius" of any function — either
by name or via a general risk-ranking scan that needs no name at all.

The working repo/package name is **`riftline-cli`**.

## Why it exists

It was conceived as a portfolio project with genuine engineering depth:
full cross-file symbol resolution, graph algorithms, and CLI design, while
also solving a practical developer problem — the fear of "I don't know
what this change will break."

## The core design philosophy — read this before changing anything

**Never present a guess as a fact.** Every design decision in this tool
traces back to that rule. When Riftline cannot verify that a call resolves
to a real function it has scanned, it says so explicitly as an `unresolved`
edge rather than guessing based on naming similarity or other heuristics.

## Architecture, in one paragraph

Four layers, each depending only on the layer below's *output types*, not
its implementation:
`parser.py` (walks one file's AST and extracts imports/functions/calls) →
`resolver.py` (chains each file's import table against every other file's
symbol table to turn raw names into resolved-or-flagged edges) →
`graph.py` (builds a `networkx.DiGraph` and answers blast-radius/hotspots/
fuzzy-search queries) → `cli.py` (the `riftline` command, built on Typer +
Rich). `git_diff.py` sits beside `cli.py` as a second consumer of
`graph.py`, mapping a `git diff` to the set of changed functions.

## Current state: this is a shipped v1, not a work in progress

All planned work (Weeks 1 through 4) is complete:

- Full cross-file symbol resolution: bare-name calls, `self.<method>()`
  and inherited-method calls, package re-export chains (single- and
  multi-hop), and `module.function()` attribute calls where `module` is a
  locally-scanned submodule.
- `riftline scan <path>` — resolved/unresolved edge counts (the
  "functions found" count excludes synthetic `unknown:*` stub nodes, so it
  reflects real functions only).
- `riftline hotspots <path> [--limit N]` — rank functions by blast-radius
  size.
- `riftline impact <symbol> [--path P]` — fuzzy short-name matching with
  explicit disambiguation.
- `riftline diff <base-ref> <head-ref> --path <dir>` — merged,
  deduplicated blast radius of every function a git diff touched.
- `riftline export --format {mermaid,dot,json}` — graph serialization,
  with resolved/unresolved edges visually distinguished, and
  collision-proof node IDs for mermaid/dot.
- SyntaxError resilience (FR-14): a single unparseable file is reported
  and skipped, never aborts the whole scan.
- Test-file suggestion heuristic, always printed under an explicit
  "unverified, naming-convention only" heading — never presented as a
  verified fact.
- Packaging: `pip install .` works, with a `riftline` console entry point
  and a `riftline --version` command wired from package metadata.
- CI: GitHub Actions runs the full test suite on Python 3.10/3.11/3.12 on
  every push/PR, plus a dogfooding smoke check (`riftline scan .` and a
  JSON export/parse round-trip against Riftline's own source).
- The regression suite is green at **67 tests** (pytest, with
  `hypothesis` property-based tests for import-resolution edge cases),
  covering method resolution, git diff behavior, re-export chains, and
  CLI error handling.
- A real path-validation bug was fixed early on: invalid paths no longer
  silently report a zero-result scan with success exit status.

**All three originally-planned stdlib substitutions have been reversed**
back to the real dependencies once network access was available:
`typer` + `rich` replaced `argparse` + `print` (confined to `cli.py`), and
`pytest` (+ `hypothesis`) replaced `unittest` (confined to `tests/` and a
`dev` extra). The one substitution that is **not** scheduled for reversal
is `ast` instead of `tree-sitter` in `parser.py` — that's a deliberate v1
design decision (multi-language parsing is out of scope for v1, and
`tree-sitter` would violate the offline-buildable-core constraint), not a
temporary workaround. See the SRS §6.2 for the full rationale.

## Known, disclosed gaps (not silently hidden)

Two real gaps surfaced by a real-world benchmark against
[scrapy/scrapy](https://github.com/scrapy/scrapy) remain open by design
(reported, not fixed, since fixing them wasn't in scope for that
measurement task) — see `docs/benchmark-results.md`:

- Constructor-inferred `instance.method()` calls don't resolve when the
  class was imported from another file (only works same-file).
- Resolved edges to locally-defined classes (used as constructors)
  produce graph nodes with no `file`/`lineno` metadata, since they never
  go through the function-node-creation path.

A running audit of further bugs found during self-review — some already
fixed, all documented with repro steps — is tracked in
`docs/bug-audit.md`.

## The full requirements spec

See the companion document, **[`riftline-SRS (1).md`](riftline-SRS%20(1).md)**,
for the formal, numbered functional/non-functional requirements, current
implementation status per requirement, and a traceability summary at the
end telling you exactly what's solid and what (if anything) is still
open.

## Verifying the current state

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

Then:

```bash
riftline scan fixtures/oop_pkg
riftline diff HEAD~1 HEAD --path fixtures/diff_repo
```

If the suite passes (67 tests) and those commands run without error, the
environment matches the state described here.

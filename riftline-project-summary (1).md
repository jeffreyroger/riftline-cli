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
fuzzy-search queries) → `cli.py` (the `riftline` command).

## Current state: what's real and tested right now

- Week 2 scope is complete and independently verified.
- Attribute and method calls are now tracked as graph edges, resolved or
  explicitly unresolved, rather than being silently dropped.
- `riftline scan <path>` reports resolved and unresolved edge counts.
- `riftline hotspots <path>` ranks functions by blast-radius size.
- `riftline impact <symbol> [--path P]` supports fuzzy short-name matching
  with explicit disambiguation when needed.
- `riftline diff <base-ref> <head-ref> --path <dir>` is now a real command
  backed by the git CLI and a merged, deduplicated blast-radius workflow.
- Package re-export resolution is implemented for single- and multi-hop
  chains in `__init__.py` files; broken chains remain unresolved rather
  than guessed.
- The regression suite is green at 42 tests, with dedicated fixtures for
  method resolution, git diff behavior, and re-export chains.
- A real path-validation bug was fixed: invalid paths no longer silently
  report a zero-result scan with success exit status.

The initial build happened in a sandboxed environment with no network
access, so `pip install` for three planned dependencies wasn't possible.
Each was swapped for a stdlib equivalent, and — this is the important
part — **each swap is contained to exactly one file**:

| Was going to use | Using instead | Only affects |
|---|---|---|
| `tree-sitter` (for eventual multi-language support) | Python's built-in `ast` module | `parser.py` |
| `typer` + `rich` (nicer CLI framework) | `argparse` + plain `print` | `cli.py` |
| `pytest` | `unittest` | `tests/test_graph.py` |

None of this touched `resolver.py` or `graph.py` — the actual resolution
algorithm and graph logic are exactly what was designed, not a simplified
stand-in. When there's network access again, these three files can be
swapped back without redesigning anything.

## Known limitations

- FR-14 remains open: a single file with a `SyntaxError` still aborts the
  whole scan rather than being reported and skipped.
- Python-only support remains in place for the current implementation.
- Graph export, test-file suggestion, and a real-world benchmark are still
  pending Week 3 work.

## The full requirements spec

See the companion document, **`riftline-SRS.md`**, for the formal,
numbered functional/non-functional requirements, current implementation
status per requirement, and a traceability summary at the end telling you
exactly what's solid, what's next, and in what order.

## Roadmap, short version

1. **Week 3** — harden robustness around syntax errors, add graph export
   (Mermaid/Graphviz/JSON), add test-file suggestion heuristics, and
   benchmark against a real repository.
2. **Week 4** — swap the three stdlib substitutions back to their
   originally-planned libraries, set up the actual GitHub repo under
   `riftline-cli`, add CI, and write a publish-ready README.

Run the test suite (`python3 -m unittest discover -s tests -v` from the
repo root). Then run:

```bash
riftline scan fixtures/oop_pkg
riftline diff HEAD~1 HEAD --path fixtures/diff_repo
```

If the suite passes and those commands run without error, the environment
matches the Week 2 state described here.

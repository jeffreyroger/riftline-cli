# Riftline — Project Context & Summary

*For anyone (human or AI agent) picking this project up without the
original conversation history.*

---

## What this is

Riftline is a command-line tool that answers one question: **"if I change
this function, what else in my codebase depends on it?"** It's a static
analyzer for Python that builds a cross-file, function-level call graph
and lets you query the transitive "blast radius" of any function — either
by name, or via a general risk-ranking scan that needs no name at all.

The working repo/package name is **`riftline-cli`**.

## Why it exists

It was conceived as a resume-worthy solo-developer portfolio project: a
tool with genuine engineering depth (cross-file symbol resolution, graph
algorithms, CLI design) that also solves a problem developers actually
have — the fear of "I don't know what this change will break" that leads
to either over-cautious never-refactoring or under-cautious breaking
changes.

## The core design philosophy — read this before changing anything

**Never present a guess as a fact.** Every single design decision in this
tool traces back to this one rule. When Riftline can't verify that a call
resolves to a real function it has scanned, it says so explicitly (an
`unresolved` edge to a synthetic `unknown:<name>` node) rather than
guessing based on naming similarity, popularity, or any other heuristic.
This is what separates it from "a script that makes a pretty graph" — the
graph's confidence labels are the actual product.

Every future feature should be evaluated against this rule first:
*does this feature ever produce a confident-looking answer it hasn't
actually verified?* If yes, redesign it so the uncertain case is visibly
flagged instead.

## Architecture, in one paragraph

Four layers, each depending only on the layer below's *output types*, not
its implementation:
`parser.py` (walks one file's AST, extracts imports/functions/calls) →
`resolver.py` (chains each file's import table against every other file's
symbol table to turn raw call names into resolved-or-flagged edges) →
`graph.py` (builds a `networkx.DiGraph`, answers blast-radius/hotspots/
fuzzy-search queries) → `cli.py` (the `riftline` command). This
layering is intentional and load-bearing: it's why three stdlib
substitutions (below) could be made without touching the two files that
actually contain the hard logic.

## Current state: what's real and tested right now

- Full cross-file call resolution, including relative imports at
  arbitrary nesting depth (`.`, `..`, verified at 2 levels deep in a
  nested-subpackage test case).
- `riftline scan <path>` — resolved/unresolved edge summary.
- `riftline hotspots <path>` — ranks every function by blast-radius size.
  This is the "I don't know what to ask about yet" entry point.
- `riftline impact <name> --path <path>` — full blast-radius query, with
  fuzzy short-name matching (type `square` instead of the full dotted
  path) and explicit disambiguation when a short name is ambiguous
  (it lists every match rather than picking one).
- `riftline diff` — currently a stub; this is the next major milestone
  (see Roadmap).
- 12 passing regression tests, plus two independently-verified fixture
  packages: a simple flat 4-file chain, and a deeper nested-package
  scenario with a fan-in point (three separate functions all calling the
  same low-level utility) and two intentionally unresolved calls.
- A real bug was found and fixed via actual user testing: bad paths used
  to silently report "0 functions found" with a success exit code; the
  CLI now validates the path up front and fails with a specific,
  actionable message.

## A note on why three components aren't what the original plan called for

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

## Known limitation that needs attention before the next big feature

Right now, **method and attribute calls are invisible, not
unresolved.** `foo(x)` is correctly tracked (resolved or flagged
unresolved); `self.foo()` or `obj.method()` currently isn't tracked as a
call *at all* — it's dropped during parsing rather than surfacing as an
`unresolved` edge. This is worse than it sounds: it means a function that
actually has real dependents via method calls can currently show up with
a *false* zero blast radius. This should be fixed (make attribute calls
surface as `unresolved` edges) before building real method-call
resolution on top of it, or the new feature will be built on a silent
data-loss bug.

## The full requirements spec

See the companion document, **`riftline-SRS.md`**, for the formal,
numbered functional/non-functional requirements, current implementation
status per requirement, and a traceability summary at the end telling you
exactly what's solid, what's next, and in what order.

## Roadmap, short version

1. **Week 2** — fix the attribute-call blind spot above, then build real
   method-call resolution (`self.foo()`), then wire up `riftline diff`
   (git diff → changed lines → affected functions). The diff workflow is
   the tool's actual intended primary use case — everything else supports
   it, so it shouldn't slip too far.
2. **Week 3** — benchmark against a real multi-hundred-file open-source
   repo (not just the two hand-built fixtures), add graph export
   (Mermaid/Graphviz/JSON), add test-file suggestion heuristics.
3. **Week 4** — swap the three stdlib substitutions back to their
   originally-planned libraries, set up the actual GitHub repo under
   `riftline-cli`, add CI, write a publish-ready README.

## How to verify you've picked this up correctly

Run the test suite (`python3 -m unittest discover -s tests -v` from the
repo root) — 12 tests should pass. Then run:
```
riftline hotspots fixtures
riftline impact low_level --path fixtures
```
If the ranked hotspots list puts `mini_pkg.core.low_level` at the top
with 3 dependents, and the fuzzy-matched impact query returns
`mini_pkg.app.run` and `mini_pkg.main.foo`, the environment and code are
in the expected working state described in this document.

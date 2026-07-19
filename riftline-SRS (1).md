# Software Requirements Specification (SRS)
## Riftline (package/repo name: `riftline-cli`)

**Version:** 1.0
**Date:** July 13, 2026
**Status key used throughout this document:**
`[Implemented]` — built, tested, working today
`[Planned]` — specified, not yet built
`[Defect]` — implemented but behaving inconsistently with its own spec, needs a fix

---

## 1. Introduction

### 1.1 Purpose
This document specifies the functional and non-functional requirements for
Riftline, a static-analysis command-line tool that computes the **blast
radius** of a proposed code change in a Python codebase — i.e., every
function that transitively depends on a given function, computed from a
resolved cross-file call graph.

### 1.2 Scope
Riftline analyzes a directory of Python source files, builds a
directed dependency graph of function-level call relationships resolved
across file boundaries, and answers queries against that graph: "what
breaks if I change this function?" The tool is read-only and static —
it does not execute the analyzed code, and it does not modify it.

### 1.3 Definitions
- **Blast radius**: the full set of functions that transitively call a
  given function, directly or indirectly (graph ancestors).
- **Resolved edge**: a call where Riftline has verified, via import-table
  chaining, that the callee is an actual function defined in the scanned
  code.
- **Unresolved edge**: a call Riftline could not verify — the target
  wasn't found in any scanned file's symbol table. Represented as an edge
  to a synthetic node named `unknown:<raw_call_name>`.
- **Confidence**: the `resolved` / `unresolved` tag attached to every edge.
  This is the tool's central integrity mechanism — see NFR-1.
- **FQN**: fully-qualified name, e.g. `mypkg.core.math_ops.square`.

### 1.4 Guiding principle (non-negotiable across all requirements)
**Never present a guess as a fact.** Where the tool cannot verify a call
target with certainty, it must say so explicitly rather than silently
assuming, dropping, or best-guessing a resolution. Every requirement below
is written to preserve this property; if a future feature can't preserve
it, it should fail loudly rather than degrade silently.

---

## 2. Overall Description

### 2.1 Product perspective
Riftline is a standalone CLI tool, installable via `pip install -e .`,
exposing a `riftline` executable. It has no server component, no network
dependency for its core function, and no IDE integration (yet — out of
scope for v1, see §7).

### 2.2 Intended users
Solo developers and small teams working in a single Python codebase who
want to know the downstream impact of a change before making it — a
pre-commit or pre-refactor safety check.

### 2.3 Operating constraints
- Python ≥ 3.10 (uses `from __future__ import annotations` and `X | None`
  union syntax throughout).
- Must run fully offline — core dependency graph construction cannot
  require network access or an installed third-party parser. (This
  constraint produced the current implementation substitutions in §6.2;
  it should be treated as a permanent target, not just a current-sandbox
  workaround, since users may run this tool in restricted/offline CI
  environments.)

### 2.4 Assumptions
- A `SyntaxError` on an individual scanned file no longer aborts the whole
  scan — it is caught, reported (which file, why), and the remaining files
  are still scanned (see FR-14, now `[Implemented]`).
- The scanned directory is a single logical package or set of packages
  under one root; cross-repo / cross-package-boundary resolution is out
  of scope (§7).

---

## 3. System Architecture (informative)

```
 source .py files
        │
        ▼
  ┌───────────┐   ImportBinding, FunctionInfo,
  │ parser.py │ → ParsedFile  (per file)
  └───────────┘
        │
        ▼
  ┌─────────────┐  raw call name + import table
  │ resolver.py │ → ResolvedCall (caller, callee, confidence)
  └─────────────┘
        │
        ▼
  ┌───────────┐   networkx.DiGraph
  │ graph.py  │ → blast_radius() / hotspots() / find_symbol()
  └───────────┘
        │
        ▼
  ┌─────────┐
  │ cli.py  │ → scan / hotspots / impact / diff
  └─────────┘
```

Each layer depends only on the dataclasses/return types of the layer
below it, not on its implementation — this is what makes the
implementation substitutions in §6.2 swappable without touching downstream
code.

---

## 4. Functional Requirements

### 4.1 Parsing (`parser.py`)

**FR-1** `[Implemented]` The system shall parse a single Python file and
extract every `import` and `from ... import ...` statement into an
`ImportBinding` record containing: `local_name`, `module`, `imported_name`,
and `level` (count of leading dots; 0 = absolute import).
*Acceptance:* `from ..shared.constants import get_limit` two packages deep
produces `ImportBinding(local_name="get_limit", module="shared.constants",
imported_name="get_limit", level=2)`.

**FR-2** `[Implemented]` The system shall extract every top-level and
nested function/method definition into a `FunctionInfo` record containing
a qualified name (dotted through enclosing classes, e.g. `Widget.render`),
`lineno`, `end_lineno`, and the list of raw names it calls.

**FR-3** `[Implemented]` The system shall record, per file, the set of
top-level symbol names it defines (`extract_symbols`), used downstream to
verify whether an imported name actually exists at its claimed origin.

**FR-4** `[Implemented]` Call extraction shall recognize bare-name calls
(`foo(x)`) only.

**FR-5** `[Implemented]` Attribute/method calls (`obj.method()`,
`self.foo()`) are surfaced as graph edges, resolved or explicitly
unresolved, rather than being silently dropped during extraction. This
preserves the guiding principle in §1.4: an invisible call is never treated
as if it did not exist, and the resolver can later upgrade a subset of
these edges to `resolved` when static inference is possible. It was fixed
as part of Phase A / Task A1.

### 4.2 Resolution (`resolver.py`)

**FR-6** `[Implemented]` For every raw call name in every function, the
system shall attempt resolution in this order and shall stop at the first
match:
  1. The name is a local import — resolve the import's target module
     (handling relative-import levels per FR-7) and check whether the
     target module's own symbol table (FR-3) actually contains the
     expected symbol. If yes → `resolved`; if the target module wasn't
     scanned or doesn't define it → `unresolved`.
  2. The name is defined in the same file → `resolved`.
  3. Otherwise → `unresolved`, represented as an edge to `unknown:<name>`.
No other resolution path is permitted; specifically, the system shall
**never** infer a resolution from naming similarity, partial matches, or
majority-vote heuristics across the codebase. (Fuzzy matching, FR-11, is a
*query-time* convenience over already-resolved node names — it must not be
used to influence graph construction itself.)

**FR-7** `[Implemented]` The system shall resolve relative imports at
arbitrary nesting depth by computing `current_module_parts[:len(parts) -
level] + module.split('.')`. This must be independently correct at level 1
(same package) and level ≥ 2 (parent packages), not just level 1 — this
was a specific regression risk validated against a nested-subpackage test
case, see §6.3.

**FR-8** `[Implemented]` Every `ResolvedCall` shall carry an explicit
`confidence` field with only two legal values: `"resolved"` or
`"unresolved"`. No third state (e.g. "probably", "likely") is permitted.

**FR-9** `[Implemented]` The system shall resolve `self.<method>()`
calls within a class to that class's own method definitions, and
`instance.<method>()` calls where `instance` is a parameter/local whose
type can be statically inferred from a type-annotated signature or a
direct constructor call in the same function. Where the type cannot be
inferred, the call remains `unresolved` (per §1.4) rather than being
best-guessed. It was built across Phase A / Tasks A2-A6, including the
explicit scope decision that multiple inheritance and dynamic attribute
targets remain unresolved by design.

**FR-9a** `[Implemented]` The system shall resolve a call to a symbol
that is imported into a target module only via re-export from an
`__init__.py` file, including multi-level re-export chains, and shall keep
the edge `unresolved` rather than guessing if the chain cannot be fully
followed. This capability was implemented in Phase C / Tasks C1-C3.

**FR-10** `[Implemented]` Given a `git diff` (or a list of changed
file+line-range pairs), the system maps each changed range to the
enclosing function via the already-implemented `function_at_line()`, then
computes the union of blast radii for all directly-changed functions. This
is the tool's primary intended workflow — a developer can run it against
their working tree before committing. It was implemented in Phase B /
Tasks B1-B4.

### 4.3 Graph construction & queries (`graph.py`)

**FR-11** `[Implemented]` The system shall build one `networkx.DiGraph`
per scan, with one node per function (attributes: `file`, `lineno`,
`end_lineno`) plus synthetic `unknown:*` nodes for unresolved targets, and
one directed edge per call (`caller → callee`, attribute `confidence`).

**FR-12** `[Implemented]` `blast_radius(graph, target)` shall return the
full set of graph ancestors of `target` (i.e., `networkx.ancestors`), and
shall raise `KeyError` with a clear message if `target` is not a node in
the graph — it must never return an empty set to mean "not found" (that
would be indistinguishable from "found, but has zero dependents").

**FR-13** `[Implemented]` `hotspots(graph, limit=None)` shall rank every
*real* function node (excluding `unknown:*` stubs — FR-13a) by the size of
its blast radius, descending, and support an optional result-count limit.
This is the tool's "no symbol name required" general-purpose entry point.

**FR-13a** `[Implemented]` `unknown:*` synthetic nodes shall never appear
in `hotspots()` output or be queryable via `blast_radius()` as a target —
they exist only as edge endpoints, not as first-class functions.

**FR-14** `[Implemented]` The system shall catch `SyntaxError` on individual
files during a scan, report which file failed and why, and continue
scanning the remaining files rather than aborting the entire scan. It was
implemented in Task D1, backed by `fixtures/broken_syntax_pkg/` (one
unparseable file alongside two valid, cross-file-dependent files).

### 4.4 CLI (`cli.py`)

**FR-15** `[Implemented]` `riftline scan <path>` shall print the resolved
and unresolved edge counts for the given path.

**FR-16** `[Implemented]` `riftline hotspots <path> [--limit N]` shall
print the top-N functions ranked by blast-radius size (default N=15).

**FR-17** `[Implemented]` `riftline impact <symbol> [--path P]` shall
accept either a full FQN or a short name. Short-name resolution
(`find_symbol`) shall:
  - match exactly if the given string is already a full FQN;
  - else match any node whose FQN ends with `.<symbol>`;
  - else fall back to substring match anywhere in the FQN;
  - print all candidates and exit with a non-zero status if more than one
    match is found at whichever tier produced results — the system shall
    **never** silently pick one candidate among several.

**FR-18** `[Implemented]` Before any scan, the CLI shall validate that the
given path exists, is a directory, and contains at least one `.py` file.
On failure it shall print a specific, actionable error message (which
condition failed) and exit with status 1. A scan must never report "0
functions found" with exit code 0 when the real cause is an invalid path —
this was a real defect found and fixed during initial testing (see §6.4).

**FR-19** `[Implemented]` `riftline diff <base-ref> <head-ref> --path <dir>`
implements FR-10's workflow via the CLI, returning a merged blast radius
for all changed functions detected from the git diff. It was implemented
in Phase B / Tasks B1-B4.

**FR-20** `[Implemented]` `riftline export --format {mermaid,dot,json}`
shall serialize the current graph to the requested format for external
visualization. It was implemented in Task D2 (`export.py`, kept separate
from `graph.py` per NFR-5), with resolved/unresolved edges visually
distinguished in every format.

**FR-21** `[Implemented]` Given an affected function, the system
shall suggest a likely test file via naming convention (e.g.
`mypkg/core.py` → `tests/test_core.py`), presented as a suggestion, not a
verified fact — it must be visually distinguishable from a `resolved`
graph edge. It was implemented in Task D3 (`testmapper.py`), wired into
`impact`/`diff` output under an explicit "unverified, naming-convention
only" heading, and never added as a graph node or edge.

### 4.5 Packaging & CI (Week 4)

**FR-22** `[Implemented]` The system shall be installable via
`pip install .` from a `pyproject.toml`, exposing a `riftline` console
entry point, with declared dependencies and a `Python >= 3.10` constraint.

**FR-23** `[Implemented]` CI shall run the full test suite on every
push/PR, and shall additionally run Riftline against its own source
(dogfooding) as a smoke check. See `.github/workflows/ci.yml` — matrix
over Python 3.10/3.11/3.12, `pytest tests/ -v`, a `riftline scan .`
dogfood step, and a `riftline export --format json` smoke test that
validates the output parses as JSON.

---

## 5. Non-Functional Requirements

**NFR-1 (Correctness over completeness).** The system shall favor
reporting a true call as `unresolved` over reporting it as `resolved`
incorrectly. A false "resolved" is a worse failure mode than a false
"unresolved," because it produces silent, unverified confidence in a
safety tool.

**NFR-2 (Determinism).** Given identical input files, the system shall
produce an identical graph and identical query results on every run — no
randomized traversal order affecting output, no dependence on filesystem
iteration order for anything user-visible (`sorted()` on any printed node
list).

**NFR-3 (Confidence transparency).** Every edge in the graph must carry an
explicit confidence value; there is no code path that is permitted to add
an edge without one. (FR-5 is a known violation of the adjacent principle
that *every call must become an edge at all* — tracked as a defect, not a
non-functional requirement violation, since the edges that do exist are
correctly tagged.)

**NFR-4 (Fail loudly on bad input).** Any invalid path, ambiguous query,
or unresolvable target must produce a clear, specific, non-zero-exit-code
error — never a silent empty/zero result (FR-18, FR-17's disambiguation
behavior, FR-12's `KeyError`).

**NFR-5 (Extensibility / layer independence).** `resolver.py` and
`graph.py` must never import from `cli.py`, and must depend on `parser.py`
only through its exported dataclasses (`ImportBinding`, `FunctionInfo`,
`ParsedFile`), not its internal implementation. This is what allows §6.2's
substitutions to be reversed by editing a single file each.

**NFR-6 (Offline-buildable core).** Core graph construction
(`parser.py` → `resolver.py` → `graph.py`) must have zero required
third-party dependencies beyond `networkx`. CLI ergonomics (`typer`,
`rich`) are a permitted enhancement confined to `cli.py`. Multi-language
parsing (`tree-sitter`) is explicitly **not** an enhancement to add in v1
— see §6.2 ("Deliberate v1 design decisions") and §7.

**Testable invariant:** after the Week 4 `typer`/`rich` swap lands (§6.2,
FR-22/FR-23 timeframe), `parser.py`, `resolver.py`, and `graph.py` shall
still import zero third-party packages other than `networkx`. This is
checkable by inspecting each file's `import`/`from` statements: every
non-stdlib name referenced must be `networkx`, or the file fails this
requirement. `typer`/`rich` imports are permitted in `cli.py` only — their
presence in `parser.py`, `resolver.py`, or `graph.py` is a regression
against this requirement, not an acceptable side effect of the CLI swap.

**NFR-7 (Performance target).** `[Implemented]` The system should complete
a full scan of a several-hundred-file repository in under a few seconds on
a typical developer machine. Benchmarked in Task D4 against a real, external
codebase (scrapy/scrapy, 446 files): ~1.0-1.1s wall-clock, well under target.
See [docs/benchmark-results.md](docs/benchmark-results.md) for the full
methodology, hand-checked sample results, and two findings surfaced (not
fixed) during that benchmark.

---

## 6. Implementation Notes (as of this version)

### 6.1 Current CLI framework
`argparse` + `print` (stdlib), not `typer`/`rich` as originally envisioned
— see §6.2 for why and how to reverse it.

### 6.2 Documented substitutions
The initial build environment had no network access to install
third-party packages. Three substitutions were made, each scoped to
exactly one file, satisfying NFR-5/NFR-6. They are not all equally
reversible — see the two groups below.

**Deliberate v1 design decisions (do not reverse):**

| Requirement originally called for | Currently implemented with | File scope |
|---|---|---|
| `tree-sitter` (multi-language AST parsing) | Python stdlib `ast` (Python-only) | `parser.py` |

*Why this one stays:* reversing it would add a compiled third-party parser
to the core path, contradicting NFR-6 (offline-buildable core, zero
third-party dependencies beyond `networkx`) and §2.3 (must run fully
offline) — in service of multi-language support that §7 already places
out of scope for v1. This is a permanent v1 decision, not a
current-sandbox workaround: revisit only if multi-language parsing is
explicitly scoped for v2.

**Reversed (Week 4):**

| Requirement originally called for | Status |
|---|---|
| `typer` + `rich` (CLI framework/output) | **Reversed.** `cli.py` now uses both; `parser.py`/`resolver.py`/`graph.py` still import nothing beyond `networkx` (NFR-6 verified). |
| `pytest` | **Reversed.** Test suite migrated from stdlib `unittest` to `pytest`, behavior-preserving (same scenarios, same assertions). `pytest` + `hypothesis` are a `dev` extra in `pyproject.toml` (`pip install .[dev]`), not a core dependency. |

Neither substitution ever affected `resolver.py` or `graph.py`, which
contain the actual resolution logic. Both reversals were mechanical,
single-file(-group) changes once package installation was available (see
FR-22, FR-23, and NFR-6's testable invariant). The `tree-sitter`
substitution above is explicitly not scheduled for reversal.

### 6.3 Validated test scenarios
- `fixtures/mini_pkg` — flat 4-file chain (`app → main → utils → core`),
  used by the automated `pytest` suite (56 passing tests, including two
  `hypothesis` property-based tests over generated relative-import depths
  and package-nesting depths).
- `synthetic_pkg` — nested subpackages exercising level-2 relative
  imports, a fan-in point (3 independent callers of the same function),
  and 2 deliberately unresolved calls. Verified against the actual
  installed CLI, not just unit tests.

### 6.4 Defect log (fixed)
- Path validation (FR-18) was originally absent: any bad or nonexistent
  path silently produced "No functions found" with exit code 0. Found via
  real user testing (a typo'd directory name), fixed by adding explicit
  existence/directory/file-count checks before graph construction.

### 6.5 Defect log (open)
- FR-5: attribute/method calls are dropped during extraction rather than
  surfaced as `unresolved` edges. Should be fixed as part of, or just
  before, FR-9.

---

## 7. Out of Scope (v1)

- Cross-repository / cross-installed-package resolution (calls into
  third-party libraries always resolve as `unknown:`, by design).
- Any code execution, dynamic analysis, or runtime instrumentation —
  Riftline is purely static.
- IDE/editor integration.
- Languages other than Python. This is not merely a tooling gap awaiting
  the tree-sitter swap — per NFR-6 and §2.3, the core must remain
  offline-buildable with zero third-party dependencies beyond `networkx`,
  and adding `tree-sitter` for multi-language parsing would violate that
  constraint in service of a feature v1 doesn't need. See §6.2 ("Deliberate
  v1 design decisions") for the full rationale. Revisit only if
  multi-language support is explicitly scoped for v2.

---

## 8. Traceability Summary (for whoever picks this up next)

If you only read one section, read this one:

- **Solid and tested today:** FR-1 through FR-21 and NFR-1 through NFR-7 are
  all `[Implemented]`. Week 3 (Tasks D0-D4) closed out FR-14 (SyntaxError
  resilience), FR-20 (graph export), FR-21 (test-file suggestion), and
  NFR-7 (real-world benchmark, see docs/benchmark-results.md).
- **Known open items (not blocking, not fabricated):** the NFR-7 benchmark
  surfaced two real findings that remain unfixed by design (out of scope
  for a measurement task) — see docs/benchmark-results.md Finding 1
  (cross-file constructor type-inference doesn't fire for FR-9) and
  Finding 2 (resolved edges to locally-defined classes produce graph nodes
  missing `file`/`lineno` metadata, per FR-11).
- **Implemented bonus:** package re-export resolution is now covered by
  FR-9a and verified as part of the Week 2 scope.
- **Week 4 (done):** FR-22 (packaging — `pip install .`, `riftline` console
  entry point, declared deps, `Python >= 3.10`) and FR-23 (CI running the
  test suite plus a dogfooding smoke check) are both `[Implemented]`. Both
  substitution reversals scheduled in §6.2 are also done: `typer`/`rich`
  replaced `argparse`/`print` in `cli.py` (NFR-6 verified — fenced to
  `cli.py` only), and `pytest` (+ `hypothesis` for property-based tests)
  replaced `unittest` in the test suite, behavior-preserving. The
  `ast`-instead-of-`tree-sitter` substitution remains **not** scheduled for
  reversal — see §6.2's "Deliberate v1 design decisions" table, NFR-6, and
  §7.

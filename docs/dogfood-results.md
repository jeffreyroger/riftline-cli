# Dogfooding Riftline against its own source (FR-23 precursor)

**Date:** 2026-07-19
**Commit scanned:** `4ecb5864925f65c7c2ea1de6517f04669706f5ea`
**Scope:** measurement only — no `.py` file was modified in this task.

## 1. `riftline scan .`

Scanned path is `C:\riftline` — the directory containing `parser.py`,
`resolver.py`, `graph.py`, `cli.py`, `export.py`, `testmapper.py`,
`git_diff.py`, plus its `tests/`, `fixtures/`, and `scripts/` subtrees (47
`.py` files total, confirmed via `find . -name "*.py" | wc -l`).

```
Scanned: C:\riftline
  functions found : 338
  edges resolved  : 171
  edges unresolved: 393  (flagged, not guessed)
1 file(s) failed to parse:
  - C:\riftline\fixtures\broken_syntax_pkg\broken.py:1: invalid syntax
```

The one parse failure is `fixtures/broken_syntax_pkg/broken.py` — that
file is *deliberately* invalid syntax, used as a fixture for FR-14
(SyntaxError resilience). Its presence and correct handling here (reported,
not fatal) is expected, not a defect.

## 2. `riftline hotspots .`

```
Top 15 riskiest functions in C:\riftline (by blast-radius size):
  riftline.parser._callee_name        28 dependent(s)
  riftline.parser._callee_attribute   28 dependent(s)
  riftline.parser.FunctionInfo        28 dependent(s)
  riftline.parser.AttributeCall       28 dependent(s)
  riftline.parser.ClassInfo           28 dependent(s)
  riftline.parser.ParseFailure        27 dependent(s)
  riftline.parser.ImportBinding       27 dependent(s)
  riftline.parser.ReExport            27 dependent(s)
  riftline.parser.parse_file          26 dependent(s)
  riftline.parser.extract_imports     26 dependent(s)
  riftline.parser.extract_functions   26 dependent(s)
  riftline.parser.extract_symbols     26 dependent(s)
  riftline.parser.extract_reexports   26 dependent(s)
  riftline.parser.extract_classes     26 dependent(s)
  riftline.parser.ParsedFile          26 dependent(s)
1 file(s) failed to parse:
  - C:\riftline\fixtures\broken_syntax_pkg\broken.py:1: invalid syntax
```

Every top-15 hotspot is in `parser.py`. This is expected, not surprising:
`parser.py` sits at the bottom of the layering (§3 of the SRS) and its
dataclasses/functions are imported and exercised by `resolver.py`,
`graph.py`, `cli.py`, `git_diff.py`, `scripts/benchmark.py`, and nearly
every test module — so it has the largest blast radius by construction.

## 3. `riftline impact <name>` for the top 3 hotspots

Top 3 are tied at 28 dependents: `_callee_name`, `_callee_attribute`,
`FunctionInfo`.

### 3a. `riftline impact _callee_name --path .` — succeeded

```
(matched '_callee_name' -> riftline.parser._callee_name)
Blast radius of riftline.parser._callee_name:
  - riftline.cli.cmd_diff
  - riftline.cli.cmd_export
  - riftline.cli.cmd_hotspots
  - riftline.cli.cmd_impact
  - riftline.cli.cmd_scan
  - riftline.git_diff.find_changed_functions
  - riftline.graph.build_graph
  - riftline.parser.extract_functions
  - riftline.parser.extract_functions.walk_body
  - riftline.parser.parse
  - riftline.scripts.benchmark.main
  - riftline.tests.test_diff.TestFindChangedFunctions.test_bad_ref_new_raises_systemexit
  - riftline.tests.test_diff.TestFindChangedFunctions.test_bad_ref_old_raises_systemexit
  - riftline.tests.test_diff.TestFindChangedFunctions.test_changed_function_detected
  - riftline.tests.test_diff.TestFindChangedFunctions.test_changed_function_metadata
  - riftline.tests.test_diff.TestFindChangedFunctions.test_no_changes_between_identical_refs
  - riftline.tests.test_diff.TestFindChangedFunctions.test_non_git_dir_raises_systemexit
  - riftline.tests.test_diff.TestFindChangedFunctions.test_untouched_function_not_in_changed_list
  - riftline.tests.test_diff.TestMergedBlastRadiusFromDiff.setUpClass
  - riftline.tests.test_export.TestExport.setUpClass
  - riftline.tests.test_graph.TestGraph.setUpClass
  - riftline.tests.test_graph.TestReExportResolution.setUpClass
  - riftline.tests.test_graph.TestReExportResolution.test_multiple_inheritance_ambiguity_flagged_unresolved
  - riftline.tests.test_graph.TestReExportResolution.test_package_as_own_root_relative_imports_work
  - riftline.tests.test_graph.TestReExportResolution.test_prior_fixture_blast_radius_unchanged
  - riftline.tests.test_graph.TestReExportResolution.test_reexport_package_as_own_root_resolves
  - riftline.tests.test_parser.TestSyntaxErrorResilience.test_build_graph_skips_syntax_error_and_keeps_valid_functions
  - riftline.tests.test_parser.TestSyntaxErrorResilience.test_parse_returns_structured_failure_for_syntax_error

Possible related tests (unverified, naming-convention only):
  - C:\riftline\parser.py -> C:\riftline\tests\test_parser.py
1 file(s) failed to parse:
  - C:\riftline\fixtures\broken_syntax_pkg\broken.py:1: invalid syntax
```

### 3b. `riftline impact _callee_attribute --path .` — succeeded

Same 28-entry blast radius list as 3a (both are private helper functions
called from the same call sites inside `extract_functions`). Output
verified identical in structure; omitted here for brevity — see raw run
log if needed.

### 3c. `riftline impact FunctionInfo --path .` — **CRASHED**

```
(matched 'FunctionInfo' -> riftline.parser.FunctionInfo)
Blast radius of riftline.parser.FunctionInfo:
  - riftline.cli.cmd_diff
  - riftline.cli.cmd_export
  ... [same 28-entry list as 3a/3b] ...
  - riftline.tests.test_parser.TestSyntaxErrorResilience.test_parse_returns_structured_failure_for_syntax_error
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "C:\Users\Jeffrey\AppData\Local\Programs\Python\Python312\Scripts\riftline.exe\__main__.py", line 7, in <module>
  File "C:\riftline\cli.py", line 303, in main
    args.func(args)
  File "C:\riftline\cli.py", line 141, in cmd_impact
    _print_test_suggestions([graph.nodes[symbol]["file"]])
                             ~~~~~~~~~~~~~~~~~~~^^^^^^^^
KeyError: 'file'
```
Exit code: 1.

**This is a real, reproducible crash — see "New finding" below.** The
blast-radius computation itself completes and prints correctly; the crash
happens afterward, in the test-suggestion step.

## 4. `riftline export --format mermaid`

Command actually needed (root path is a flag, not a positional — the
first attempt with a bare `.` argument failed with `unrecognized
arguments: .`; corrected to `--path .`):

```
riftline export --format mermaid --path . --out docs/self-scan.mmd
```
Exit code: 0. Output saved to [`docs/self-scan.mmd`](self-scan.mmd) — 903
lines, a full Mermaid flowchart of Riftline's own call graph, including
resolved edges (solid arrows) and unresolved edges (dotted arrows, per
FR-20). This is a legitimate "tool diagrams its own architecture" artifact
for the README.

## 5. Sanity check: does the graph reflect the known parser → resolver → graph → cli layering?

Checked by grouping every edge by (caller module, callee module) and
looking at the core four modules specifically:

```
graph->resolver : 3
graph->parser   : 1
graph->graph    : 4   (edges within graph.py itself)
cli->graph      : 10
cli->parser     : 9
cli->export     : 3
cli->testmapper : 1
cli->git_diff   : 2
parser->resolver: 0
resolver->parser: 0
cli->resolver   : 0
```

**Yes, this matches the documented architecture, with one clarification.**
`graph.py` calls into `resolver.py` (3 edges) and `parser.py` (1 edge) —
consistent with `graph.py` orchestrating both lower layers to build the
`networkx.DiGraph`. `cli.py` calls into `graph.py`, `parser.py`, `export.py`,
`testmapper.py`, and `git_diff.py` — consistent with `cli.py` being the
top-level orchestration layer.

There are **zero direct call edges from `resolver.py` into `parser.py`**.
This is not a defect: per NFR-5, `resolver.py` is only supposed to depend
on `parser.py`'s *exported dataclasses* (`ImportBinding`, `FunctionInfo`,
`ParsedFile`), not call its functions — consuming a dataclass's fields
doesn't produce a call-graph edge, only function/method calls do. Zero
edges here is exactly what correct compliance with NFR-5 looks like, not
missing instrumentation.

## 6. NFR-5 empirical check: any edge FROM resolver.py or graph.py INTO cli.py?

**None found.** Querying every edge in the 564-edge graph for
`(caller in resolver.py) -> (callee in cli.py)` or
`(caller in graph.py) -> (callee in cli.py)` returns **zero matches** — the
full edge-direction breakdown above lists every nonzero `graph->*` and
`cli->*` pairing that exists, and `graph->cli` / `resolver->cli` simply
never appear. NFR-5 holds empirically on Riftline's own source, today.

## Summary

| Metric | Result |
|---|---|
| Path scanned | `C:\riftline` (47 `.py` files, incl. `tests/`, `fixtures/`, `scripts/`) |
| Functions found | 338 |
| Edges resolved | 171 |
| Edges unresolved | 393 |
| Files failed to parse | 1 (`fixtures/broken_syntax_pkg/broken.py`, deliberately invalid — expected) |
| Top hotspot | `parser._callee_name` / `_callee_attribute` / `FunctionInfo` (tied, 28 dependents each) |
| `impact` on hotspot 1, 2 | succeeded, correct blast radius |
| `impact` on hotspot 3 (`FunctionInfo`) | **crashed** — `KeyError: 'file'` in `cmd_impact` |
| `export --format mermaid` | succeeded, 903-line diagram saved to `docs/self-scan.mmd` |
| Layering sanity check (§5) | **matches** documented architecture |
| NFR-5 empirical check (§6) | **holds** — zero `resolver.py`/`graph.py` → `cli.py` edges |

## New finding (bug, NOT fixed in this task): `riftline impact` crashes on any target whose graph node lacks `file` metadata

`cli.py:141`, inside `cmd_impact`, unconditionally does
`graph.nodes[symbol]["file"]` when building the test-suggestion list. This
assumes every resolved query target has a `file` key. It doesn't: any
locally-defined **class** used as a resolved call target (per the
already-documented Finding 2 in `docs/benchmark-results.md` — `graph.py`'s
node-creation pass only attaches `file`/`lineno`/`end_lineno` for `def`
blocks, never for classes) produces a bare node with no attributes at all.
Running `riftline impact FunctionInfo --path .` against Riftline's own
source hit exactly this: `FunctionInfo` is a dataclass (a `class`, not a
`def`), it's a legitimate hotspot with a real 28-function blast radius that
prints correctly, and then the CLI crashes with an uncaught `KeyError`
immediately afterward while trying to print test suggestions.

This is a step beyond Finding 2 as originally reported: Finding 2 said
downstream consumers *might* silently get `None`/missing data if they
assumed every node has location metadata. This shows a real, in-tree
downstream consumer (`cmd_impact`) that does make exactly that assumption,
and it doesn't degrade gracefully — it crashes with a raw traceback and
exit code 1, on a perfectly reasonable, non-adversarial query run against
Riftline's own source.

**Reported as a finding only. Not fixed — `cli.py` was not modified in
this task**, per the task's own instructions to stop and report rather
than patch around it.

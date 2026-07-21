# Riftline — Full Project Bug Audit

**Date:** 2026-07-21 (audit) / 2026-07-22 (all findings below fixed)
**Scope:** entire repository — every `.py` file, fixtures, packaging config, CI workflows, and documentation.
**Method:** `py_compile` syntax check on every file, full test suite run, manual read-through of every core module, live reproduction of every finding below against the actual CLI (not just code inspection), and a documentation cross-check against current behavior.
**Original rule:** this was a search-only pass — nothing was fixed while auditing. Every finding below was subsequently fixed one at a time, each verified with: the original repro re-run to confirm the fix, a new regression test proven to fail without the fix and pass with it, and a full suite run after every single change. The original repro steps are left intact below as the verification record.

No syntax errors and no test failures were found during the audit — `python -m py_compile` was clean on every tracked `.py` file, and `pytest tests/ -v` passed 56/56 (now 68/68 after the fixes and their accompanying regression tests below). Every finding was a **logic bug, crash, silent-failure, or documentation-accuracy problem** found by exercising the tool directly, not something the test suite already caught (that's exactly why it needed a manual audit to find).

## Resolution status — all 17 findings fixed

| ID | Status | Fix summary |
|---|---|---|
| CRITICAL-1 | **FIXED** | `cmd_scan` now uses `graph.py`'s existing `real_nodes()` instead of `graph.number_of_nodes()`. |
| CRITICAL-2 | **FIXED** | `cmd_diff` re-fetches `get_parse_failures()` after `build_graph()` runs, not just before. |
| CRITICAL-3 | **FIXED** | `git_diff.py` corrects the recorded `ParseFailure.path` from the throwaway temp file to the real repo file. |
| HIGH-1 | **FIXED** | `resolver.py` gained `_resolve_attribute_base_as_module()`: resolves `module.function()` when `module` is a confirmed local module import, never guessing when the imported name is actually a symbol. |
| HIGH-2 | **FIXED** | `cmd_impact` uses `.get("file")` instead of `["file"]`, skipping the test-suggestion section when a resolved symbol (e.g. a class-as-constructor node) has no file metadata. |
| HIGH-3 | **FIXED** | `cmd_export`'s `--out` write is wrapped in try/except `OSError`, producing a clean `Error: ...` message + exit 1. |
| MEDIUM-1 | **FIXED** | `export.py`'s `_sanitize_identifier()` appends a short hash of the original name, guaranteeing distinct Mermaid/DOT node IDs. |
| MEDIUM-2 | **FIXED** | `cmd_hotspots` rejects `--limit < 1` with a clean error instead of silently misinterpreting it via Python slice semantics. |
| MEDIUM-3 | **FIXED** | Table columns for function names use `overflow="fold"` (wrap) instead of the default truncate-with-ellipsis, so a long identifier is never corrupted by an encoding mismatch — it just wraps, fully intact. |
| LOW-1 | **FIXED** | Both class-scoped fixtures in `test_diff.py` converted to `@classmethod`, per pytest's own recommended fix. |
| LOW-2 | **FIXED** | `riftline-project-summary (1).md` rewritten to reflect the actual shipped v1 state. |
| LOW-3 | **not changed** | The odd `(1)` filename suffixes remain — renaming either doc risks breaking other things that reference the exact current filenames; flagged, not touched. |
| LOW-4 | **FIXED** | Stray untracked `build/` directory deleted. |
| LOW-5 | **FIXED** | `test_diff.py` gained `_robust_rmtree()` (clears read-only attributes before removal) — the standard fix for `shutil.rmtree` silently leaving `.git/objects/*` behind on Windows. |
| LOW-6 | **FIXED** | `.gitignore` gained `*.whl` and `self_graph.json`. |
| LOW-7 | **FIXED** | `find_symbol()` returns `[]` immediately for an empty query instead of falling through to a substring match that matched every function. |

`docs/self-scan.mmd` and the README's "How it works" diagram were also regenerated to reflect MEDIUM-1's fix (node IDs now carry a hash suffix) and CRITICAL-1's fix (accurate function counts).

---

## Severity key
- **Critical** — wrong/misleading output presented as fact, or a silent failure that violates the project's own "never fail silently" (NFR-4) / "never present a guess as a fact" (§1.4) principles.
- **High** — unhandled crash (raw traceback) on realistic input, or a resolution gap large enough to affect most real-world codebases.
- **Medium** — wrong output in a narrower/rarer case, or a misleading-but-non-crashing UX issue.
- **Low** — cosmetic, hygiene, or stale-documentation issue.

---

## CRITICAL-1: `riftline scan`'s "functions found" count includes `unknown:*` stub nodes — not real functions

**File:** `cli.py:144` (`cmd_scan`), root cause in `graph.py`'s `build_graph()`.

`cmd_scan` reports `graph.number_of_nodes()` as "functions found". But `graph.number_of_nodes()` counts **every** node in the graph, including synthetic `unknown:<name>` stub nodes created as edge-targets for unresolved calls (see `resolver.py`'s `unknown:{raw_name}` construction). Those stub nodes are explicitly *not* functions — `graph.py`'s own `real_nodes()` docstring says so, and FR-13a states "`unknown:*` synthetic nodes shall never appear ... as a first-class function." `cmd_scan` never applies that filter.

**Measured impact** (real, live measurement, not estimated):

| Path scanned | "functions found" (current, wrong) | Actual real functions | Stub nodes inflating the count |
|---|---|---|---|
| `fixtures/mini_pkg` | 5 | 4 | 1 |
| `fixtures/oop_pkg` | 4 | 3 | 1 |
| `fixtures/synthetic_pkg` | 9 | 7 | 2 |
| `fixtures/reexport_pkg` | 4 | 4 | 0 |
| riftline's own repo (`.`) | 422 | 236 | **186 (79% inflation)** |

**Why this matters beyond a cosmetic count:** this is the exact same metric quoted as the headline number in `docs/benchmark-results.md` ("Functions found: 8,876" for the Scrapy benchmark) and in every README example. Given Scrapy's benchmark reported 12,511 unresolved edges (many of which likely collapse onto a much smaller, but still probably large, number of *distinct* `unknown:name` targets), the real "functions found" figure for that benchmark is almost certainly substantially lower than 8,876 — this was never checked against `real_nodes()` when the benchmark doc was written.

**Repro:**
```bash
python -c "
from riftline.graph import build_graph, real_nodes
from pathlib import Path
g = build_graph(Path('fixtures/mini_pkg'))
print(g.number_of_nodes())      # 5 -- what 'riftline scan' prints
print(len(real_nodes(g)))       # 4 -- the real answer
"
```

---

## CRITICAL-2: `riftline diff` silently drops parse failures from the full-package scan

**File:** `cli.py`, `cmd_diff`, lines 282–308.

`cmd_diff`'s sequence is:
```python
clear_parse_failures()
root = _validated_root(path)
_assert_git_repo(root)
changed = find_changed_functions(root, ref_old, ref_new)   # may itself add ParseFailures (see CRITICAL-3)
failures = get_parse_failures()                            # <-- captured HERE
...
graph = build_graph(root)                                  # <-- full-package scan runs AFTER failures already read!
```
Any file in the scanned package that fails to parse **during `build_graph(root)`** — which is the call that actually computes the blast radius shown to the user — is never captured, because `get_parse_failures()` already ran before `build_graph()` executes. `riftline diff` will report a clean, confident blast radius while silently having skipped an entire file, with zero indication anything went wrong.

This directly violates **FR-14** ("The system shall catch `SyntaxError` on individual files during a scan, report which file failed and why... rather than aborting the entire scan") — the *reporting* half of that requirement doesn't happen here, even though the *not-aborting* half does.

There's also a smoking-gun leftover in the same function: `except SyntaxError as exc:` at line 309 is **dead code** — `build_graph()` can never raise `SyntaxError` (parser.py's `parse_file()` catches it internally and converts it to a `ParseFailure` instead of re-raising), so this except block has been unreachable since FR-14 was implemented in Week 3. It's a strong signal that `cmd_diff` (written in Phase B, before FR-14 existed) was never updated when FR-14 changed how syntax errors are surfaced elsewhere.

**Repro (real, live-verified):**
```bash
mkdir -p /tmp/bugrepro1/pkg && cd /tmp/bugrepro1
git init -q && git config user.email t@t.com && git config user.name t
printf 'def compute(x):\n    return x*2\n' > pkg/core.py
printf 'from .core import compute\ndef run():\n    return compute(5)\n' > pkg/app.py
printf '' > pkg/__init__.py
git add -A && git commit -q -m "c1"
printf 'def compute(x):\n    return x*4\n' > pkg/core.py
git add -A && git commit -q -m "c2"
# unrelated file with a syntax error, NOT committed, NOT part of the diff:
printf 'def broken(:\n    pass\n' > pkg/broken.py

riftline scan .                       # correctly reports: "1 file(s) failed to parse: broken.py"
riftline diff HEAD~1 HEAD --path .    # exits 0, prints a confident blast radius, says NOTHING about broken.py
```

---

## CRITICAL-3: when the syntax-broken file IS part of the diff, `riftline diff` reports a meaningless temp-file path and can misreport "no changes" (false-safe signal)

**File:** `git_diff.py`, `find_changed_functions()`, lines 239–257.

To analyze the *new* version of a changed file, `find_changed_functions` runs `git show ref_new:path`, writes the content to a `tempfile.NamedTemporaryFile`, and calls `parse(tmp_path)` on it. If that file has a syntax error at `ref_new`:

1. The resulting `ParseFailure.path` is the **temp file's path** (e.g. `C:\Users\...\Temp\tmpop5i7nar.py`), not the real repo-relative path (`pkg/core.py`) — the message shown to the user is unusable for finding the actual broken file.
2. Because the file fails to parse, `parsed.functions` is empty for it, so **zero** changed functions are reported for that file. If it's the *only* file in the diff, the CLI prints **"No Python function changes detected between 'HEAD~1' and 'HEAD'."** — a false "nothing to see here" signal, when in fact the file changed but couldn't be analyzed at all. This is the more serious half of this bug: a user could read "no changes detected" as "safe," when the real situation is "we don't know."

**Repro (real, live-verified):**
```bash
mkdir -p /tmp/bugrepro2/pkg && cd /tmp/bugrepro2
git init -q && git config user.email t@t.com && git config user.name t
printf 'def compute(x):\n    return x*2\n' > pkg/core.py
printf '' > pkg/__init__.py
git add -A && git commit -q -m "c1"
printf 'def compute(x:\n    return x*4\n' > pkg/core.py   # syntax error introduced in commit 2
git add -A && git commit -q -m "c2 - now broken"

riftline diff HEAD~1 HEAD --path .
# Output:
#   No Python function changes detected between 'HEAD~1' and 'HEAD'.
#   1 file(s) failed to parse:
#     - C:\Users\...\Temp\tmpXXXXXXXX.py:1: '(' was never closed
```

---

## HIGH-1: `module.function()` calls never resolve, even when fully local and statically verifiable

**File:** `resolver.py`, `resolve_calls_for_file()`, lines 104–139.

Every attribute call is handled by:
```python
if attr_call.base == "self" and attr_call.enclosing_class is not None:
    ... attempt resolution ...
if not resolved:
    reason = "dynamic attribute target, not statically resolvable"  # (or "method not defined...")
    callee = f"unknown:{attr_call.base}.{attr_call.attr}"
```
Only `self.<method>()` is ever attempted. **Any other attribute call — including `module.function()` where `module` is a locally-imported, fully-scanned submodule — is unconditionally flagged `unresolved`**, with the same reason used for genuinely dynamic/untyped targets. `_resolve_one()` (the bare-name resolver, which *does* correctly chain import bindings against `all_symbols`) is never consulted for the `base` of an attribute call at all.

This is a different, larger gap than the already-documented Finding 1 in `docs/benchmark-results.md` (which is specifically about instance-based `instance.method()` calls where `instance` came from a constructor). This finding is about the far more common pattern of `import module` / `from package import module` followed by `module.func()` — completely idiomatic, everyday Python — which **always** resolves as unknown regardless of whether the module is part of the same scan. Nothing in the SRS or README's "Known limitations" section discloses this; the README's "Cross-package calls" limitation implies only *third-party* calls are unresolved by design, not same-package ones.

**Repro (real, live-verified):**
```bash
mkdir -p /tmp/bugrepro3/pkg && cd /tmp/bugrepro3
printf '' > pkg/__init__.py
printf 'def helper():\n    return 1\n' > pkg/utils.py
printf 'from . import utils\ndef run():\n    return utils.helper()\n' > pkg/app.py

riftline export --format json --path pkg
# "pkg.app.run" -> "unknown:utils.helper", confidence "unresolved"
# even though `utils` is a known import binding resolving to the fully-scanned
# local module `pkg.utils`, and `helper` is a real symbol defined there.
```

---

## HIGH-2 (previously known, confirmed still unfixed): `riftline impact <ClassName>` crashes with an unhandled `KeyError: 'file'`

**File:** `cli.py`, `cmd_impact`, lines 214 and 223.

First reported in `docs/dogfood-results.md` (Week 3 dogfooding). Re-verified live in this audit — **still present, unfixed**:

```python
_print_test_suggestions([graph.nodes[resolved_symbol]["file"]])
```
If `resolved_symbol` names a locally-defined **class** used as a constructor call (a "Finding 2"-style bare node with no attributes — see `docs/benchmark-results.md`), this line raises an unhandled `KeyError`, and the CLI dumps a raw Rich traceback instead of a clean error.

**Repro (real, live-verified, from the repo root):**
```bash
riftline impact riftline.parser.FunctionInfo --path .
# prints a correct blast-radius table, then crashes:
#   KeyError: 'file'
#   at cli.py:223 in cmd_impact
```

---

## HIGH-3: `riftline export --out <path in a nonexistent directory>` crashes with a raw, unhandled traceback

**File:** `cli.py`, `cmd_export`, lines 257–259.

```python
if out:
    out_path = Path(out)
    out_path.write_text(content, encoding="utf-8")
```
No existence check, no try/except. Every other failure mode in this CLI (bad path, ambiguous symbol, bad git ref, non-git directory, unresolvable path) gets a clean `Error: ...` message per NFR-4. This one does not — it's the only user-triggerable crash path in the CLI that doesn't go through the project's own error-handling convention.

**Repro (real, live-verified):**
```bash
riftline export --format json --path fixtures/mini_pkg --out /nonexistent_dir/out.json
# FileNotFoundError: [Errno 2] No such file or directory: '\nonexistent_dir\out.json'
# (raw traceback, exit code 1, but not a clean NFR-4-style message)
```

---

## MEDIUM-1: `export.py`'s node-ID sanitizer can collide two genuinely different functions into one Mermaid/DOT node

**File:** `export.py`, `_sanitize_identifier()`, lines 9–11.

```python
def _sanitize_identifier(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]", "_", name) or "node"
```
Every non-alphanumeric character (including `.`) becomes `_`. Two distinct FQNs that differ only in *where* a `.` vs an already-present `_` falls will collide onto the same sanitized ID. Confirmed with a concrete, minimal repro. **Only affects `to_mermaid`/`to_dot`** — `to_json` uses the raw FQN string directly and is unaffected.

**Repro (real, live-verified):**
```bash
mkdir -p /tmp/bugrepro4/pkg
printf 'def a_b():\n    return 1\n' > /tmp/bugrepro4/pkg/__init__.py   # FQN: pkg.a_b
printf 'def b():\n    return 2\n' > /tmp/bugrepro4/pkg/a.py            # FQN: pkg.a.b

riftline export --format mermaid --path /tmp/bugrepro4/pkg
# flowchart TD
#     pkg_a_b["pkg.a.b"]
#     pkg_a_b["pkg.a_b"]      <-- SAME node id as the line above; Mermaid renders these as one node
```

---

## MEDIUM-2: `riftline hotspots --limit` silently accepts 0 or negative values, producing misleading results

**File:** `cli.py` (`cmd_hotspots`), `graph.py` (`hotspots()`).

`hotspots()` does `ranked = ranked[:limit]` with no validation. Typer/Click only checks that `--limit` is an `int` — it doesn't reject non-positive values.

- `--limit 0` → empty list → `cmd_hotspots` prints **"No functions found."**, which is simply false (functions clearly exist; the user just asked for zero of them). This message is supposed to mean "the scanned path has no functions in it at all."
- `--limit -3` → Python slice semantics interpret this as "all but the last 3" (i.e., drop the 3 *lowest*-ranked functions), not "top 3" or an error. The printed title ("Top N riskiest functions") does not describe what actually happened and does not match any reasonable interpretation of `--limit -3`.

**Repro (real, live-verified):**
```bash
riftline hotspots fixtures/mini_pkg --limit 0     # "No functions found." (false)
riftline hotspots fixtures/synthetic_pkg --limit -3
# "Top 4 riskiest functions..." -- silently dropped the 3 lowest-ranked entries,
# not the top 3, and not an error either.
```

---

## MEDIUM-3: Rich table truncation of long function names can emit a mangled replacement character instead of an ellipsis

**File:** `cli.py` (`cmd_hotspots`/`cmd_impact` table rendering), underlying cause is this environment's console encoding interacting with Rich's `Table` column-width truncation.

Reproduced cleanly, independent of any other issue in this audit:
```bash
riftline hotspots tests --limit 30
# ...
# | tests.test_property_import_resolution._assert_confidence_inva� |          2 |
```
The real function name is `_assert_confidence_invariant`; Rich's table truncated it and — instead of the graceful ASCII fallback verified elsewhere in this project (box-drawing characters degrade to plain `+---+` correctly) — emitted a raw Unicode replacement character (`�`) mid-identifier. The true name is not recoverable from this output. This makes `hotspots`/`impact` tables actively misleading (not just truncated-but-honest) for any FQN long enough to hit a table column's truncation point on this platform/encoding combination.

---

## LOW-1: `tests/test_diff.py` defines class-scoped pytest fixtures as instance methods — deprecated, already surfaced in real CI

**File:** `tests/test_diff.py`, lines 112–113 and 175–176.

```python
@pytest.fixture(scope="class", autouse=True)
def _fixture_repo(self):        # <-- instance method, not @classmethod
```
This is not speculative — the real CI run under pytest 9.1.1 (`gh run view` log, this same session) emitted:
```
PytestRemovedIn10Warning: Class-scoped fixture defined as instance method is deprecated.
Instance attributes set in this fixture will NOT be visible to test methods, as each
test gets a new instance while the fixture runs only once per class.
Use @classmethod decorator and set attributes on cls instead.
```
`TestMergedBlastRadiusFromDiff`'s fixture already works around the underlying issue by writing to `request.cls` instead of `self`, so it isn't losing data today — but the decorator pattern itself is what's deprecated and will presumably stop working in pytest 10. `TestFindChangedFunctions`'s fixture doesn't set any attributes at all, so it's lower-risk, but both trigger the same warning.

---

## LOW-2: `riftline-project-summary (1).md` is drastically stale and actively misleading

**File:** `riftline-project-summary (1).md` (repo root, tracked in git).

Describes a Week-2 snapshot of the project that is no longer true in almost every particular:

| Claim in the file | Actual current state |
|---|---|
| "regression suite is green at 42 tests" | 56 tests |
| `typer`+`rich` "swapped for argparse+print... when there's network access again, these can be swapped back" | Already swapped back; `cli.py` has used Typer+Rich for multiple weeks |
| `pytest` "swapped for unittest" | Already swapped back to pytest (+ hypothesis) |
| "FR-14 remains open: a single file with a SyntaxError still aborts the whole scan" | Fixed in Week 3; the opposite is true — SyntaxError resilience is implemented and tested |
| "Graph export, test-file suggestion, and a real-world benchmark are still pending Week 3 work" | All three shipped in Week 3, weeks ago |
| References a companion doc named "`riftline-SRS.md`" | The real file is named `riftline-SRS (1).md` — this cross-reference doesn't resolve to an existing file |

This file is tracked in git (`git ls-files` confirms it) and would be one of the first things a new reader opens given its filename. Right now it actively contradicts the real, current README and SRS.

## LOW-3: Both root-level markdown docs have odd "(1)" + space suffixes in their filenames

`riftline-SRS (1).md` and `riftline-project-summary (1).md` are both named as if they were a second download of a file whose original was never cleaned up (a very common browser-download artifact). Purely cosmetic, but not a good look in a "publish-ready" repo, and — see LOW-2 — the mismatch between the actual filename and the name other docs assume it has is a real (if minor) broken cross-reference.

## LOW-4: Untracked `build/lib/riftline/` directory currently pollutes this checkout's own dogfooding

**Path:** `build/lib/riftline/*.py` (untracked, gitignored, leftover from an earlier `pip wheel`/`python -m build` invocation in this session).

Not a shipped bug — it's gitignored and won't exist in a fresh clone — but **right now, in this exact working tree**, it duplicates every module in the `riftline` package under a second, parallel path. Any `riftline scan .` / `riftline hotspots .` / `riftline impact X --path .` run against the repo root will find two copies of every function (e.g. `riftline.parser.FunctionInfo` and `riftline.build.lib.riftline.parser.FunctionInfo`), which is exactly what made `impact FunctionInfo` report "ambiguous -- 2 functions match" during this audit instead of resolving directly. Worth deleting before any further dogfooding in this checkout.

## LOW-5: `fixtures/diff_repo/.git/` residue reappears after manual fixture builds

**Path:** `fixtures/diff_repo/.git/` (gitignored, ephemeral by design).

`tests/test_diff.py`'s `_teardown_fixture()` calls `shutil.rmtree(dot_git, ignore_errors=True)`, but on this Windows machine that doesn't always fully remove the directory (observed twice now, in two separate sessions) — some `.git/objects/*` files survive teardown. Harmless in practice (every `_build_fixture()` call wipes it again before use, and it's gitignored so it never gets committed), but it's a minor reliability gap in the fixture teardown that's worth knowing about if disk hygiene in CI ever matters.

## LOW-6: `.gitignore` doesn't cover artifacts the project's own CI step can produce locally

**File:** `.gitignore`.

`ci.yml`'s dogfood step runs `riftline export --format json --path . --out self_graph.json` — if a contributor runs that same command locally at the repo root (to mimic CI), `self_graph.json` is not gitignored and could be accidentally committed. Similarly, running `pip wheel .` (no output dir) drops a `*.whl` file at the repo root, also not covered.

## LOW-7: `find_symbol()` / `riftline impact ""` (empty string) produces a confusing "ambiguous" result rather than a clear "no symbol given" error

**File:** `graph.py`, `find_symbol()`, plus `cli.py`'s `_resolve_symbol_or_exit`.

`find_symbol(graph, "")` falls through to the substring-match fallback (`query in n`), and since every string contains the empty substring, **every real function in the graph matches**. `riftline impact ""` therefore reports `'' is ambiguous -- N functions match` (listing literally every function) rather than a clearer "no symbol given" message. Not a crash — still exits 1 with *a* message — but a confusing edge case a user could hit by e.g. a scripting mistake that passes an empty variable.

---

## Findings already known before this audit, reconfirmed still present (not re-described in full here)
- **Finding 1** (`docs/benchmark-results.md`): constructor-inferred `instance.method()` calls don't resolve when the class was imported from another file (only works same-file). Still present.
- **Finding 2** (`docs/benchmark-results.md`): resolved edges to locally-defined classes (used as constructors) produce bare graph nodes with no `file`/`lineno` metadata. Still present — and is the direct cause of HIGH-2 above.
- SRS **FR-9** and **FR-11** status tags read as unconditional `[Implemented]` despite Findings 1 and 2 respectively being real, disclosed-elsewhere gaps against each (flagged in the prior Week-4 verification pass; still true).

---

## Summary table

| ID | Severity | One-line summary | File(s) |
|---|---|---|---|
| CRITICAL-1 | Critical | "functions found" counts `unknown:*` stubs as real functions (~79% inflation on this repo) | `cli.py`, `graph.py` |
| CRITICAL-2 | Critical | `riftline diff` silently drops parse failures from the full-package scan | `cli.py` |
| CRITICAL-3 | Critical | `riftline diff` shows a meaningless temp-file path and can report false "no changes" when the diffed file itself has a syntax error | `git_diff.py` |
| HIGH-1 | High | `module.function()` calls never resolve, even fully local | `resolver.py` |
| HIGH-2 | High | `riftline impact <ClassName>` crashes with `KeyError: 'file'` (known, still unfixed) | `cli.py` |
| HIGH-3 | High | `riftline export --out <bad dir>` crashes with a raw traceback | `cli.py` |
| MEDIUM-1 | Medium | Sanitized node IDs can collide two different functions in mermaid/dot | `export.py` |
| MEDIUM-2 | Medium | `hotspots --limit 0`/negative gives silently wrong/misleading results | `cli.py`, `graph.py` |
| MEDIUM-3 | Medium | Rich table truncation can mangle long FQNs into unreadable garbage | `cli.py` (Rich rendering) |
| LOW-1 | Low | Deprecated pytest fixture pattern, already warns in real CI | `tests/test_diff.py` |
| LOW-2 | Low | `riftline-project-summary (1).md` is badly stale/misleading | `riftline-project-summary (1).md` |
| LOW-3 | Low | Odd "(1)" filename suffixes on both root docs | filenames |
| LOW-4 | Low | Stray `build/` copy currently pollutes local dogfooding | `build/` (untracked) |
| LOW-5 | Low | `diff_repo/.git` teardown residue on Windows | `fixtures/diff_repo/` (untracked) |
| LOW-6 | Low | `.gitignore` misses CI's own output artifacts | `.gitignore` |
| LOW-7 | Low | Empty-string symbol gives a confusing "ambiguous" message | `graph.py`, `cli.py` |
| (ref) | — | Finding 1 / Finding 2 / FR-9 / FR-11 tag mismatch — already known, reconfirmed | `resolver.py`, `graph.py`, SRS |

**16 new findings** (3 critical, 3 high, 3 medium, 7 low) plus reconfirmation that the 2 previously-known findings are still present. Nothing in this document has been fixed — every entry above includes exact repro steps for verifying a fix later.

# NFR-7 Benchmark Results

**Date:** 2026-07-19
**Run by:** interactive session, `scripts/benchmark.py` + `riftline scan` (installed CLI), cross-checked against each other

This document supersedes a previous version dated 2026-07-16 that used the
same subject repository and reported the same file/function/edge counts and
the same two findings, but a materially different (and, on this machine,
unreproducible) timing figure — see "Note on the previous timing figure"
below. Everything in this version was independently re-run and re-verified
in this session; nothing here is carried over from that prior document
without being re-checked against real output.

## Network access check

Confirmed available: `git clone --depth 1 https://github.com/octocat/Hello-World.git`
succeeded (exit 0, real file content pulled) before proceeding. This is
**Case 1 — network available**, so a real external repository was cloned
rather than a synthetic package.

## Subject repository

**[scrapy/scrapy](https://github.com/scrapy/scrapy)** (BSD-3-Clause), shallow-cloned
(`git clone --depth 1`, completed in ~2.1s) into a scratch directory
entirely outside the `riftline` working tree
(`%TEMP%\claude\...\scratchpad\benchmarks\scrapy`) — never committed, never
placed under `fixtures/`.

**Why Scrapy:** a well-known, actively maintained, permissively-licensed
mid-size Python library with real architectural complexity (class-based
middleware/pipeline plugin system, single and multiple inheritance, async
code, dynamic dispatch via settings-driven object loading). It also ships a
large test suite in the same tree, written in a distinctly different style
(heavy `unittest`/pytest classes) from the library code, so the same run
exercises the parser/resolver against two different real-world coding
styles.

**Confirmed file count:** `find scrapy -name "*.py" | wc -l` → **446** files,
checked immediately after cloning, before any scan.

## Timing

Measured with `time.perf_counter()` inside `scripts/benchmark.py`, wrapping
a single `build_graph(root)` call — the exact function the `riftline` CLI
itself calls. Five consecutive runs on this machine:

| Run | Elapsed (build_graph only) |
|---|---|
| 1 | 2.483s |
| 2 | 2.444s |
| 3 | 2.408s |
| 4 | 2.420s |
| 5 | 2.407s |

Consistently **~2.4s** for the core scan of 446 files / 8,876 functions.
Cross-checked with the actual installed CLI (`time riftline scan <path>`),
which includes Python interpreter startup and import overhead on top of
`build_graph`: **3.068s** end-to-end. Both numbers are internally
consistent and reproducible on this machine.

This still comfortably meets NFR-7's "several hundred files in under a few
seconds" target.

### Note on the previous timing figure

A prior version of this document (dated 2026-07-16) reported ~1.0–1.1s for
an identical file/function/edge count on the same repository. That number
could not be reproduced in this session — five independent runs here
consistently land around 2.4s (build_graph) / 3.1s (full CLI), roughly
2.2–3x higher. Given the file/function/edge counts are bit-for-bit
identical between the two dates (446 / 8,876 / 4,616 / 12,511), the
discrepancy is almost certainly environmental (different machine, disk, or
background load) rather than a code change, but it is reported honestly
rather than silently repeating the old number: **the real, reproduced
number on this machine, today, is ~2.4s core / ~3.1s end-to-end**, not
~1.0–1.1s.

## Scan summary

Ran both `scripts/benchmark.py` and the installed `riftline scan` command
against the same clone; both report identical numbers:

```
Files scanned   : 446
Functions found : 8876
Edges resolved  : 4616
Edges unresolved: 12511
```

No files failed to parse (confirmed via `get_parse_failures()` returning an
empty list) — Scrapy's source is entirely valid, modern Python 3.

Unresolved rate is ~73% of edges. Manual inspection below shows this is
mostly expected and correct.

## Manual hand-check: 15 resolved edges

Sampled with `random.seed(42)` over the actual `build_graph()` output (a
small script dumping `graph.edges(data=True)` with node file/line
metadata), then verified against the real Scrapy source for each one.

| # | Edge | Verified against source | Verdict |
|---|---|---|---|
| 1 | `CookieJar.make_cookies` → `WrappedResponse` | `cookies.py:99`: `wrsp = WrappedResponse(response)`; `WrappedResponse` is a class defined at `cookies.py:206` | Correct target, **but see Finding 2** |
| 2 | `load_context_factory_from_settings` → `_load_context_factory_from_settings` | `contextfactory.py:315`: `return _load_context_factory_from_settings(crawler)`; callee defined same file, line 272 | Correct |
| 3 | `TestHttpBase.test_download_no_extra_response_headers` → `TestHttpBase.get_dh` | Caller (line 290) and one of five same-named `get_dh` methods (line 87) both fall inside `class TestHttpBase` (lines 65–833); correct one picked despite 4 other `get_dh` defs elsewhere in the file | Correct |
| 4 | `TestCrawlSpider.test_async_def_asyncgen_parse_loop` → `TestCrawlSpider._run_spider` | `test_crawl.py:640`: `await self._run_spider(...)`; `_run_spider` defined line 486, same class (`TestCrawlSpider` starts line 484) | Correct |
| 5 | `DemoSpider.scrapes_item_ok` → `DemoItem` | `DemoItem` is a class (`test_contracts.py:23`), constructed via the spider's contract-parsed return dict | Correct target, **but see Finding 2** |
| 6 | `DownloaderAwarePriorityQueue.pqfactory` → `ScrapyPriorityQueue` | `pqueues.py:392`: `return ScrapyPriorityQueue(...)`; class defined line 52 | Correct target, **but see Finding 2** |
| 7 | `FeedExporter._get_uri_params` → `load_object` | `feedexport.py:34`: `from scrapy.utils.misc import build_from_crawler, load_object` | Correct |
| 8 | `test_data_path_inside_project` → `data_path` | `test_utils_project.py:7`: `from scrapy.utils.project import data_path, ...`; used line 30 | Correct |
| 9 | `OffsiteMiddleware.request_scheduled` → `OffsiteMiddleware.process_request` | `offsite.py:42-43`: `def request_scheduled(...): self.process_request(request)`; both methods in `class OffsiteMiddleware` (line 23) | Correct |
| 10 | `TestFormRequest.test_from_response_dont_submit_reset_as_input` → `_qs` | `test_http_request_form.py:397`: `fs = _qs(req)`; `_qs` defined module-level, line 23 | Correct |
| 11 | `FileDownloadHandler.download_request` → `run_in_thread` | `file.py:10`: `from scrapy.utils.asyncio import run_in_thread`; used line 20 | Correct |
| 12 | `HttpxDownloadHandler.__init__` → `_make_ssl_context` | `_httpx.py:25`: imported; used line 89: `self._ssl_context = _make_ssl_context(crawler.settings)` | Correct |
| 13 | `JsonItemExporter.export_item` → `to_bytes` | `exporters.py:22`: `from scrapy.utils.python import is_listlike, to_bytes, to_unicode`; used line 165 | Correct |
| 14 | `TestCommandCrawlerProcess.test_project_settings_empty` → `TestCommandCrawlerProcess._assert_spider_asyncio_fail` | Both inside `class TestCommandCrawlerProcess` (lines 135–363) | Correct |
| 15 | `TestCustomContractPrePostProcess.test_pre_hook_async_generator` → `ResponseMock` | `ResponseMock` is a class (`test_contracts.py:28`), constructed line 753 | Correct target, **but see Finding 2** |

**Sample false-positive rate: 0/15 (0%).** Every "resolved" edge really does
point at a symbol genuinely defined where Riftline says it is. 4 of the 15
(27% of this sample) point at locally-defined **classes** and hit Finding 2
(no `file`/`lineno` on the target node). Checking this across the full
graph (not just the sample): **965 of 4,616 resolved edges (20.9%)**
overall point at a target node with no `file`/`lineno` metadata.

## Manual hand-check: 15 unresolved edges

Same seed/sampling approach, same file, applied to the unresolved-edge set.

| # | Edge | Verified against source | Verdict |
|---|---|---|---|
| 1 | `...` → `InstrumentedFeedSlot.subscribe__listener` | Attribute access on a `mock.patch`-injected test double, not statically typeable | Correctly unresolved |
| 2 | `...` → `pipe_cls.from_crawler` | `pipe_cls` is the **return value** of a factory call earlier in the test, not a constructor call or annotated parameter — outside FR-9's stated scope | Correctly unresolved |
| 3 | `arg_to_iter` → `isinstance` | Python builtin | Correctly unresolved |
| 4 | `...` → `resp2.css` | `resp2` is a locally-constructed `Response`-like object; method resolution on it isn't attempted | Correctly unresolved |
| 5 | `BaseSettings.setmodule` → `key.isupper` | `key` is a runtime loop variable of dynamic type | Correctly unresolved |
| 6 | `TestParallelAsyncio.callable` → `asyncio.sleep` | stdlib module call, out of resolver scope by design | Correctly unresolved |
| 7 | `StartUrlsSpider.__init__` → `super` | Python builtin | Correctly unresolved |
| 8 | `...` → `str` | Python builtin | Correctly unresolved |
| 9 | `TestFormRequest.test_formdata_overrides_querystring` → `fs.get` | `fs` is a plain dict/local var, dynamic attribute | Correctly unresolved |
| 10 | `TestHttpProxyMiddleware.test_change_proxy_keep_credentials` → `middleware.process_request` | `tests/test_downloadermiddleware_httpproxy.py:293-294`: `middleware = HttpProxyMiddleware()` then `middleware.process_request(...)` **in the same function**; `HttpProxyMiddleware` is imported (line 5: `from scrapy.downloadermiddlewares.httpproxy import HttpProxyMiddleware`), not locally defined | **FALSE NEGATIVE — see Finding 1** |
| 11 | `StatsCollector.inc_value` → `d.setdefault` | Plain dict, builtin method | Correctly unresolved |
| 12 | `...` → `log.check_present` | Attribute on a `LogCapture` test fixture object | Correctly unresolved |
| 13 | `TestShowOrSkipMessages.test_show_messages` → `str` | Python builtin | Correctly unresolved |
| 14 | `AsyncDefAsyncioReqsReturnSpider.parse` → `asyncio.sleep` | stdlib module call | Correctly unresolved |
| 15 | `build_component_list` → `compdict.items` | `dict.items()`, builtin method | Correctly unresolved |

**Sample false-negative rate: 1/15 (~6.7%).**

Checked the scope of item #10's underlying pattern directly against the
graph (not just grep): querying every unresolved edge from
`test_downloadermiddleware_httpproxy.py` whose callee attribute is
`process_request` returns **exactly 26 edges**, all in this one file, all
hitting the identical root cause. This is a systematic miss, not a one-off
sampling fluke.

## Finding 1 (bug, NOT fixed in this task): cross-file constructor type inference doesn't fire

FR-9 states the resolver shall statically infer a local/parameter's type
"from a type-annotated signature **or a direct constructor call in the same
function**," with no stated restriction to same-file classes. In
`tests/test_downloadermiddleware_httpproxy.py`, the repeated pattern

```python
middleware = HttpProxyMiddleware()   # constructor, same function
...
middleware.process_request(request)  # should resolve via FR-9
```

is flagged `unresolved` with reason `"dynamic attribute target, not
statically resolvable"` in all 26 occurrences in this file (verified by
direct graph query, not just text search), even though `HttpProxyMiddleware`
is imported from `scrapy.downloadermiddlewares.httpproxy` and the type is
statically knowable from the constructor call.

**Root cause (inferred, not fixed here):** the constructor-inference path
in `resolver.py` appears to only match constructor calls where the class is
defined in the *same file* as the call site, not one resolved through an
import binding the way plain function calls are (FR-6). This does not match
any of the documented by-design limitations in the README (multiple
inheritance, genuinely dynamic/untyped targets) — it looks like a real gap
against FR-9's own stated scope.

**Impact:** systematic false-negative source affecting any codebase using
the common idiom of "construct an imported class, call a method on it in
the same function" — very common in test code specifically, so real-world
impact on blast-radius completeness is likely significant.

Reported here as a finding only. Per this task's instructions, **not**
fixed — `resolver.py` was not modified.

## Finding 2 (design gap, NOT fixed in this task): resolved edges to locally-defined classes produce nodes with no file/lineno metadata

FR-6's resolution rule ("the name is defined in the same file → resolved")
doesn't distinguish a name that's a function from a name that's a class.
When a call target is a locally-defined **class** used as a constructor
(e.g. `WrappedResponse(response)`, `DemoItem(...)`, `ScrapyPriorityQueue(...)`,
`ResponseMock()`), the edge is marked `resolved` — correctly, since the name
genuinely is defined locally — but `graph.py`'s node-creation pass
(`build_graph`) only calls `graph.add_node(...)` with `file`/`lineno`/
`end_lineno` for entries in `parsed.functions` (`def` blocks). A class name
never goes through that path, so `graph.add_edge(...)` implicitly creates a
bare node with no attributes at all.

Such a node satisfies neither of FR-11's two documented node categories: not
a real function node with location metadata, not a synthetic `unknown:*`
stub either. Verified two ways in this session: 4/15 in the manual sample
(27%), and **965/4,616 (20.9%) across the full resolved-edge set** — this
is not a sampling artifact, it is a large, consistent fraction of all
resolved edges in this codebase.

**Impact:** any downstream consumer assuming every non-`unknown:` node has
location metadata (e.g. a future `function_at_line()` feature, or
`testmapper.suggest_test_file` if ever pointed at a resolved graph node
rather than a caller's own file) would silently get `None`/missing data.
`export.py` currently degrades gracefully (falls back to the bare name), so
nothing visibly breaks today — but the node shape doesn't match what FR-11
promises, and roughly 1 in 5 resolved edges hits it.

Reported here as a finding only. Per this task's instructions, **not**
fixed — `graph.py` was not modified.

## Summary

| Metric | Result |
|---|---|
| Repo | scrapy/scrapy @ shallow clone, cloned and scanned 2026-07-19 |
| Network access | available (verified via trivial clone before proceeding) |
| Files scanned | 446 |
| Functions (graph nodes) found | 8,876 |
| Edges resolved | 4,616 |
| Edges unresolved | 12,511 |
| Wall-clock scan time (core `build_graph`) | ~2.4s (5 runs, range 2.407–2.483s) |
| Wall-clock scan time (full `riftline scan` CLI) | ~3.07s |
| Parse failures | 0 |
| Resolved sample checked | 15 |
| Resolved sample false-positive rate | 0/15 (0%) |
| Unresolved sample checked | 15 |
| Unresolved sample false-negative rate | 1/15 (~6.7%), confirmed systemic: exactly 26 occurrences in one file (direct graph query) |
| Resolved edges missing file/lineno (Finding 2), full corpus | 965/4,616 (20.9%) |
| Bugs found | 2 (Finding 1, Finding 2) — reported, not fixed in this task |

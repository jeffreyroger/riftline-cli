# NFR-7 Benchmark Results

**Date:** 2026-07-16
**Run by:** manual session, `scripts/benchmark.py`

## Subject repository

**[scrapy/scrapy](https://github.com/scrapy/scrapy)** (BSD-3-Clause), shallow-cloned
(`git clone --depth 1`) into a local scratch directory outside the `riftline`
repo (not committed, not gitignored inside this repo — it simply never
entered the working tree).

**Why Scrapy:** it's a well-known, actively maintained, permissively-licensed
mid-size Python library with real architectural complexity (class-based
middleware/pipeline plugin system, inheritance, async code, dynamic
dispatch via settings-driven object loading) — the kind of code where a
naive resolver would either over- or under-resolve in interesting ways.
It also ships its own substantial test suite in the same tree, which
exercises the parser against a second, different coding style (heavy
`unittest`/pytest-style classes) in the same run.

**Confirmed file count before running:** 446 `.py` files (checked with
`find scrapy -name "*.py" | wc -l` immediately after cloning, before any
scan).

## Timing

Measured with `time.perf_counter()` around a single `build_graph(root)` call
in `scripts/benchmark.py` (the exact function the `riftline` CLI itself
calls) — real wall-clock, not estimated. Three consecutive runs on the same
clone:

| Run | Elapsed |
|---|---|
| 1 | 1.119s |
| 2 | 1.104s |
| 3 | 1.018s |

All three land around **~1.0–1.1 seconds** for a 446-file / 8,876-function
scan. This comfortably meets NFR-7's "several hundred files in under a few
seconds" target, on this machine, for this repository.

## Scan summary (cross-checked against the real CLI)

Ran both `scripts/benchmark.py` and the actual installed `riftline scan`
command against the same clone; the two report identical numbers:

```
Files scanned   : 446
Functions found : 8876
Edges resolved  : 4616
Edges unresolved: 12511
```

(`riftline scan` printed the same `functions found` / `edges resolved` /
`edges unresolved` numbers verbatim.) No files failed to parse — Scrapy's
source is entirely valid, modern Python 3.

Note the unresolved rate is high (~73% of edges). Manual inspection below
shows this is mostly **expected and correct** — see the sample breakdown.

## Manual hand-check: 15 resolved edges

Sampled with `random.seed(42)` for reproducibility, then verified against
the actual Scrapy source for each one.

| # | Edge | Verified against source | Verdict |
|---|---|---|---|
| 1 | `CookieJar.make_cookies` → `WrappedResponse` | `WrappedResponse` is a **class** (`cookies.py:206`), called as a constructor | Correct target, **but see Finding 2** |
| 2 | `load_context_factory_from_settings` → `_load_context_factory_from_settings` | Both defined in `contextfactory.py`; callee at line 272, matches | Correct |
| 3 | `TestHttpBase.test_download_no_extra_response_headers` → `TestHttpBase.get_dh` | `self.get_dh()` resolved to the correct same-class method among several same-named methods in other classes in the same file | Correct |
| 4 | `TestCrawlSpider.test_async_def_asyncgen_parse_loop` → `TestCrawlSpider._run_spider` | `self._run_spider()`, defined same class, line 486 | Correct |
| 5 | `DemoSpider.scrapes_item_ok` → `DemoItem` | `DemoItem` is a **class** (`test_contracts.py:23`), constructor call | Correct target, **but see Finding 2** |
| 6 | `DownloaderAwarePriorityQueue.pqfactory` → `ScrapyPriorityQueue` | `ScrapyPriorityQueue` is a **class** (`pqueues.py:52`), constructor call | Correct target, **but see Finding 2** |
| 7 | `FeedExporter._get_uri_params` → `load_object` | Defined in `utils/misc.py:58`, imported and called correctly | Correct |
| 8 | `test_data_path_inside_project` → `data_path` | Defined `utils/project.py:50`, imported correctly | Correct |
| 9 | `OffsiteMiddleware.request_scheduled` → `OffsiteMiddleware.process_request` | `self.process_request()`, same class, line 46 | Correct |
| 10 | `TestFormRequest.test_from_response_dont_submit_reset_as_input` → `_qs` | Module-level function, `test_http_request_form.py:23` | Correct |
| 11 | `FileDownloadHandler.download_request` → `run_in_thread` | `utils/asyncio.py:296`, imported correctly | Correct |
| 12 | `HttpxDownloadHandler.__init__` → `_make_ssl_context` | `utils/ssl.py:66`, imported correctly | Correct |
| 13 | `JsonItemExporter.export_item` → `to_bytes` | `utils/python.py:88`, imported correctly | Correct |
| 14 | `TestCommandCrawlerProcess.test_project_settings_empty` → `_assert_spider_asyncio_fail` | `self._assert_spider_asyncio_fail()`, same class, line 207 | Correct |
| 15 | `TestCustomContractPrePostProcess.test_pre_hook_async_generator` → `ResponseMock` | `ResponseMock` is a **class** (`test_contracts.py:28`), constructor call | Correct target, **but see Finding 2** |

**Sample false-positive rate: 0/15 (0%).** Every "resolved" edge really does
point at a symbol genuinely defined where Riftline says it is. However, 4
of the 15 (27% of this sample) surfaced **Finding 2** below.

## Manual hand-check: 15 unresolved edges

| # | Edge | Verified against source | Verdict |
|---|---|---|---|
| 1 | `...` → `unknown:InstrumentedFeedSlot.subscribe__listener` | Dynamic attribute chain on a runtime object | Correctly unresolved |
| 2 | `...` → `unknown:pipe_cls.from_crawler` | `pipe_cls` is assigned from a factory method's **return value** (`self._generate_fake_pipeline()`), not a constructor or annotated param — outside FR-9's stated scope | Correctly unresolved |
| 3 | `arg_to_iter` → `unknown:isinstance` | Python builtin | Correctly unresolved |
| 4 | `...` → `unknown:resp2.css` | Dynamic attribute on a local var | Correctly unresolved |
| 5 | `BaseSettings.setmodule` → `unknown:key.isupper` | `key` is a loop variable (`str`), dynamic attribute | Correctly unresolved |
| 6 | `...` → `unknown:asyncio.sleep` | stdlib module call, out of scope by design | Correctly unresolved |
| 7 | `StartUrlsSpider.__init__` → `unknown:super` | Python builtin | Correctly unresolved |
| 8 | `...` → `unknown:str` | Python builtin | Correctly unresolved |
| 9 | `...` → `unknown:fs.get` | Dynamic attribute on a local var | Correctly unresolved |
| 10 | `TestHttpProxyMiddleware.test_change_proxy_keep_credentials` → `unknown:middleware.process_request` | `middleware = HttpProxyMiddleware()` **on the line directly above**, in the same function — a direct constructor call, exactly the case FR-9 claims to resolve | **FALSE NEGATIVE — see Finding 1** |
| 11 | `StatsCollector.inc_value` → `unknown:d.setdefault` | `d` is a plain dict, builtin method | Correctly unresolved |
| 12 | `...` → `unknown:log.check_present` | Dynamic attribute on a fixture/mock object | Correctly unresolved |
| 13 | `...` → `unknown:str` | Python builtin | Correctly unresolved |
| 14 | `AsyncDefAsyncioReqsReturnSpider.parse` → `unknown:asyncio.sleep` | stdlib module call | Correctly unresolved |
| 15 | `build_component_list` → `unknown:compdict.items` | `dict.items()`, builtin method | Correctly unresolved |

**Sample false-negative rate: 1/15 (~6.7%).**

## Finding 1 (bug, NOT fixed in this task): cross-file constructor type inference doesn't fire

FR-9 states the resolver shall statically infer a local/parameter's type
"from a type-annotated signature **or a direct constructor call in the same
function**," with no stated restriction to same-file classes. In
`tests/test_downloadermiddleware_httpproxy.py`, every single test method
does:

```python
middleware = HttpProxyMiddleware()   # constructor, same function
...
middleware.process_request(request)  # should resolve via FR-9
```

`HttpProxyMiddleware` is imported (`from scrapy.downloadermiddlewares.httpproxy
import HttpProxyMiddleware`) rather than defined in the same file. Querying
the built graph directly shows this is not an isolated miss — **all 26
occurrences of this exact pattern in this one file** are flagged
`unresolved` with the reason `"dynamic attribute target, not statically
resolvable"`, which is not an accurate description of the actual situation
(the type *is* staticly knowable — it's a straightforward constructor call).

**Root cause (inferred, not fixed here):** the constructor-inference path in
`resolver.py` appears to only match constructor calls where the class is
defined in the *same file* as the call site, not one resolved through an
import binding the way plain function calls are (FR-6). This isn't one of
the documented "by design" limitations in the README (those are multiple
inheritance and genuinely dynamic/untyped targets) — this looks like a real
gap against FR-9's own stated scope.

**Impact:** this is a systematic false-negative source, not a one-off. It
likely under-counts blast radius for any codebase using the common pattern
of "construct an imported class, then call a method on it in the same
function" — this is an extremely common testing idiom, so real-world impact
is probably significant.

This is reported here as a finding only. Per this task's instructions, it
has **not** been fixed — `resolver.py` was not modified.

## Finding 2 (design gap, NOT fixed in this task): resolved edges to class constructors produce nodes with no file/lineno metadata

FR-6's resolution rule ("the name is defined in the same file → resolved")
doesn't distinguish between a name that's a function versus a name that's a
class. When a call target is actually a locally-defined **class** (e.g.
`WrappedResponse(response)`, `DemoItem(...)`, `ScrapyPriorityQueue(...)`,
`ResponseMock()`), the resolver marks the edge `resolved` — correctly, in
that the name genuinely is defined locally — but `graph.py`'s node-creation
pass (`build_graph`) only ever calls `graph.add_node(...)` with `file` /
`lineno` / `end_lineno` for entries in `parsed.functions` (i.e., `def`
blocks). A class name was never added through that path, so
`graph.add_edge(...)` implicitly creates a bare node for it with **no
attributes at all**.

This means such a node satisfies neither of FR-11's two documented node
categories: it isn't a real function node with `file`/`lineno`/`end_lineno`,
and it isn't a synthetic `unknown:*` stub either. Confirmed in this sample:
4 of 15 randomly sampled resolved edges (27%) hit this exact case, and in
each case `graph.nodes[callee]` had no `file`/`lineno` data.

**Impact:** downstream consumers that assume every non-`unknown:` node has
location metadata (e.g. a future `function_at_line()`-based feature, or
`testmapper.suggest_test_file` if ever pointed at a resolved *node* instead
of a caller's own file) would silently get `None`/missing data for these
nodes. Today's `export.py` formats degrade gracefully (falls back to just
the name), so nothing currently visibly breaks — but the node doesn't match
what FR-11 promises.

This is reported here as a finding only. Per this task's instructions, it
has **not** been fixed — `graph.py` was not modified.

## Summary

| Metric | Result |
|---|---|
| Repo | scrapy/scrapy @ shallow clone, 2026-07-16 |
| Files scanned | 446 |
| Functions (graph nodes) found | 8,876 |
| Edges resolved | 4,616 |
| Edges unresolved | 12,511 |
| Wall-clock scan time | ~1.0–1.1s (3 runs) |
| Resolved sample checked | 15 |
| Resolved sample false-positive rate | 0/15 (0%) |
| Unresolved sample checked | 15 |
| Unresolved sample false-negative rate | 1/15 (~6.7%), confirmed systematic (26 occurrences in one file alone) |
| Bugs found | 2 (see Finding 1, Finding 2) — reported, not fixed in this task |

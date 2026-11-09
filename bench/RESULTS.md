# Benchmark results (2026-11-09)

## v0.6.0: one call per answer

v0.6.0 opens a file named in the message before the model starts and tells the model the table and columns, so the model answers with one `grimoire_query` call through Hermes's `tool_call` bridge.
Before, an answer took 4 API calls (load the tool, attach, query, answer), and every call resends about 12,000 tokens of system prompt and tool list.
The data itself was never the cost: query results are a few hundred characters.

Same 8 questions and model, 24 answers with Grimoire v0.6.0 (raw records: `bench/results-v0.6.0.jsonl`), against the 40 plain answers below:

| | Plain Hermes | Grimoire v0.4.0 | Grimoire v0.6.0 |
|---|---|---|---|
| API calls per answer (median) | 5 | 4 | 2 |
| Input tokens (median, with cached) | 61,051 | 47,619 | 23,300 (62% fewer than plain) |
| Output tokens (median) | 858 | 378 | 301 |
| Time per answer (median) | 30 s | 19 s | 12 s (60% faster) |
| Cost per answer (median)* | $0.0504 | $0.0319 | $0.0239 (53% cheaper) |
| Correct | 39 of 40 | 40 of 40 | 23 of 24 |

The one wrong v0.6.0 answer is the reason the number check exists.
The query returned 1,091 units; the model wrote "10,911 units".
Grimoire flagged it: "0 of 1 numbers trace to query results. No source query for: 10,911".

## v0.4.0 against plain Hermes

Same 8 questions, same model, two Hermes profiles that differ only in Grimoire (v0.4.0).
Model: `meituan/longcat-2.5:free` on Nous Portal.
Files: `bench/make_data.py` sales data with messy regions, about 4% empty amounts and 2% empty dates.
One fresh session per answer; 80 answers in total.
True answers come from Python's `csv` module, not DuckDB.
Raw records: `bench/results.jsonl`.

## Summary (all 40 answers per setup, medians)

| | Plain Hermes | With Grimoire | Difference |
|---|---|---|---|
| Correct answers | 39 of 40 | 40 of 40 | |
| Input tokens (with cached input) | 61,051 | 47,619 | 22% fewer |
| Output tokens | 858 | 378 | 56% fewer |
| Time per answer | 30 s | 19 s | 36% faster |
| Cost per answer* | $0.0504 | $0.0319 | 37% cheaper |

## By file size

| File | Setup | Runs | Correct | Input tokens (median) | Output tokens | Time (median) | Cost per answer* | Tool calls |
|---|---|---|---|---|---|---|---|---|
| 1k rows | plain | 8 | 8/8 (100%) | 65,324 | 712 | 32 s | $0.0488 | 4 |
| 1k rows | grimoire | 8 | 8/8 (100%) | 47,782 | 368 | 20 s | $0.0311 | 3 |
| 50k rows | plain | 24 | 23/24 (96%) | 60,017 | 847 | 28 s | $0.0504 | 4 |
| 50k rows | grimoire | 24 | 24/24 (100%) | 47,599 | 378 | 17 s | $0.0321 | 3 |
| 1M rows | plain | 8 | 8/8 (100%) | 66,192 | 1,031 | 33 s | $0.0463 | 4 |
| 1M rows | grimoire | 8 | 8/8 (100%) | 47,686 | 448 | 20 s | $0.0334 | 3 |

*The model is free, so tokens are priced per million at $3.00 input, $0.30 cached input and $15.00 output.

## What this shows, and what it does not

- The plain agent did not read the files raw in this run; it wrote Python and awk. Grimoire still used fewer tokens and less time, because one SQL call replaces a write-run-check loop.
- In an earlier single session (2026-11-08) a plain agent read the 50k file raw first and used 488,501 input tokens for one answer. This benchmark did not reproduce that, so we do not claim it as typical.
- Cost per answer stays flat as files grow, for both setups: the model never sees the rows.
- The one wrong plain answer (50k, revenue per region) merged 'north ' into North but did not list the merged total the question asked for.
- One model and one run per file size for 1k and 1M rows. Treat differences of a few percent as noise.
- Grimoire keeps a catalog between sessions, so later questions on the same file skip some setup. That is a real feature, and it is part of these numbers.

## Number check (go/no-go)

All 40 Grimoire answers were correct, so every "No source query" flag on them is a false alarm or a rounding.

| Version | Answers with a flag |
|---|---|
| v0.4.0 (live) | 19 of 39 (49%) |
| v0.5.1 (replayed with the saved query results) | 3 of 40 (8%) |

Of the 3 left, one is a real rounding ("2,000" for 1,996).
The other two used a number from a query the answer did not cite, or two steps of arithmetic (paise to rupees to crore).
v0.5.1 adds a "derived" class for unit changes, sums, differences, ratios and column totals; small whole numbers may only be a sum or difference of numbers the reply shows, so an invented count is still flagged.

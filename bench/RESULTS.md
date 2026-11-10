# Benchmark results

## v0.25: Claude Haiku, Sonnet and Opus 5.5, up to 100 million rows (2026-11-10)

Same questions, same model on both sides, one run each.
Plain Hermes is a profile with Grimoire turned off; it can still run Python and install packages.
Sales files: 8 questions each (`bench/questions.py`), true answers computed by streaming the file.
NYC taxi data: 6 questions on 20.3M real trips, January to June 2024 (`bench/nyc.py`).
Raw results: `results-claude.jsonl`.
Input tokens include cached tokens (cache reads and writes); medians per file.

### Claude Haiku 5.5

| File | Setup | Correct | Input tokens | Output tokens | Time | Model calls |
|---|---|---|---|---|---|---|
| Sales CSV, 1M rows | Plain Hermes | 8/8 | 51,708 | 578 | 9 s | 3 |
| Sales CSV, 1M rows | Hermes with Grimoire | 8/8 | 35,524 | 320 | 6 s | 2 |
| Sales CSV, 10M rows | Plain Hermes | 8/8 | 51,853 | 652 | 20 s | 3 |
| Sales CSV, 10M rows | Hermes with Grimoire | 8/8 | 35,412 | 283 | 6 s | 2 |
| Sales CSV, 100M rows (5 GB) | Plain Hermes | 8/8 | 61,874 | 1,071 | 76 s | 4 |
| Sales CSV, 100M rows (5 GB) | Hermes with Grimoire | 8/8 | 35,506 | 394 | 12 s | 2 |
| Sales Parquet, 100M rows (1.6 GB) | Plain Hermes | 8/8 | 81,408 | 1,107 | 14 s | 4 |
| Sales Parquet, 100M rows (1.6 GB) | Hermes with Grimoire | 8/8 | 35,500 | 328 | 6 s | 2 |
| NYC taxi Parquet, 20.3M rows | Plain Hermes | 6/6 | 52,566 | 862 | 11 s | 3 |
| NYC taxi Parquet, 20.3M rows | Hermes with Grimoire | 6/6 | 35,961 | 275 | 5 s | 2 |
| NYC taxi CSV, 20.3M rows (2 GB) | Plain Hermes | 6/6 | 34,536 | 446 | 49 s | 2 |
| NYC taxi CSV, 20.3M rows (2 GB) | Hermes with Grimoire | 6/6 | 35,920 | 338 | 7 s | 2 |

### Claude Sonnet 5.5

| File | Setup | Correct | Input tokens | Output tokens | Time | Model calls |
|---|---|---|---|---|---|---|
| Sales CSV, 1M rows | Plain Hermes | 8/8 | 42,867 | 411 | 8 s | 2 |
| Sales CSV, 1M rows | Hermes with Grimoire | 8/8 | 35,516 | 291 | 6 s | 2 |
| Sales CSV, 10M rows | Plain Hermes | 8/8 | 51,515 | 440 | 20 s | 3 |
| Sales CSV, 10M rows | Hermes with Grimoire | 8/8 | 35,468 | 264 | 5 s | 2 |
| Sales CSV, 100M rows (5 GB) | Plain Hermes | 8/8 | 51,728 | 535 | 170 s | 3 |
| Sales CSV, 100M rows (5 GB) | Hermes with Grimoire | 8/8 | 35,454 | 258 | 9 s | 2 |
| Sales Parquet, 100M rows (1.6 GB) | Plain Hermes | 8/8 | 51,675 | 374 | 8 s | 3 |
| Sales Parquet, 100M rows (1.6 GB) | Hermes with Grimoire | 8/8 | 35,478 | 276 | 5 s | 2 |
| NYC taxi Parquet, 20.3M rows | Plain Hermes | 6/6 | 34,138 | 272 | 6 s | 2 |
| NYC taxi Parquet, 20.3M rows | Hermes with Grimoire | 6/6 | 35,958 | 246 | 5 s | 2 |
| NYC taxi CSV, 20.3M rows (2 GB) | Plain Hermes | 6/6 | 34,311 | 263 | 43 s | 2 |
| NYC taxi CSV, 20.3M rows (2 GB) | Hermes with Grimoire | 6/6 | 35,935 | 278 | 7 s | 2 |

### Claude Opus 5.5

| File | Setup | Correct | Input tokens | Output tokens | Time | Model calls |
|---|---|---|---|---|---|---|
| Sales CSV, 1M rows | Plain Hermes | 8/8 | 51,518 | 504 | 12 s | 3 |
| Sales CSV, 1M rows | Hermes with Grimoire | 8/8 | 35,547 | 324 | 10 s | 2 |
| Sales CSV, 10M rows | Plain Hermes | 8/8 | 51,930 | 676 | 22 s | 3 |
| Sales CSV, 10M rows | Hermes with Grimoire | 8/8 | 35,460 | 308 | 9 s | 2 |
| Sales CSV, 100M rows (5 GB) | Plain Hermes | 8/8 | 69,865 | 906 | 114 s | 4 |
| Sales CSV, 100M rows (5 GB) | Hermes with Grimoire | 8/8 | 35,466 | 314 | 12 s | 2 |
| Sales Parquet, 100M rows (1.6 GB) | Plain Hermes | 7/8 | 71,787 | 932 | 22 s | 4 |
| Sales Parquet, 100M rows (1.6 GB) | Hermes with Grimoire | 8/8 | 35,483 | 327 | 9 s | 2 |
| NYC taxi Parquet, 20.3M rows | Plain Hermes | 6/6 | 72,652 | 748 | 17 s | 4 |
| NYC taxi Parquet, 20.3M rows | Hermes with Grimoire | 6/6 | 36,008 | 309 | 7 s | 2 |
| NYC taxi CSV, 20.3M rows (2 GB) | Plain Hermes | 6/6 | 43,141 | 468 | 50 s | 2 |
| NYC taxi CSV, 20.3M rows (2 GB) | Hermes with Grimoire | 6/6 | 35,928 | 328 | 9 s | 2 |

### What this shows

- **Correct answers:** Grimoire 132 of 132, plain Hermes 131 of 132.
  The miss: plain Opus divided cents by 100 twice on the 100M-row Parquet file, so every region total was 100 times too small.
- **Speed grows with file size.** Grimoire answers in 5 to 12 s at every size.
  Plain Hermes needs 43 to 170 s on the large CSV files (5x to 19x slower), because it reads the whole file with awk or Python first.
  On Parquet the gap is small (1.2x to 2.5x): Parquet is quick to read even from plain Python.
- **Tokens:** Grimoire uses about 35,500 input tokens per answer on every model and file, with 2 model calls.
  On 15 of the 18 file and model pairs that is 17% to 56% fewer input tokens than plain Hermes.
  The exceptions are on the taxi data: plain Sonnet (both files) and plain Haiku (CSV) answered in 2 calls and used slightly fewer input tokens than Grimoire (34,100 to 34,500 against about 35,900).
  Most input tokens are Hermes's own system prompt, sent again with every model call; Grimoire saves by needing fewer calls and shorter answers.
- **What plain Hermes does not do at any token cost:** the number check after each reply, the Data page charts, pivots and drill-down, and the learning cards.
  All of these run as plugin code and use 0 model tokens.
- During the run, plain Hermes installed the `duckdb` Python package by itself (`pip3 install duckdb`), and plain Opus made its own virtual environments to install it.
  So the plain rows are Hermes with DuckDB through Python where it chose to install it, not Hermes without DuckDB.

## Earlier runs (2026-11-09)

## v0.19.7: sales data in US dollars

The sales files now have an `amount_cents` column and the questions ask for US dollars (same seed, same values as before).
8 questions on `sales_50k.csv`, one run each, free model `meituan/longcat-2.5:free`, 2026-11-09. Raw results: `results.jsonl`.

| Setup | Correct | Input tokens (median) | Time (median) | Cost per answer* | Tool calls |
|---|---|---|---|---|---|
| Plain Hermes | 8/8 | 65,362 | 33 s | $0.0457 | 4 |
| Hermes with Grimoire | 8/8 | 23,572 | 15 s | $0.0236 | 1 |
| Data bot (Grimoire's tools only) | 8/8 | 4,436 | 16 s | $0.0128 | 1 |

Number check: 15 of 16 Grimoire answers "ready to share"; the other wrote a stray 25,000 before correcting itself, and was flagged.

## v0.19.1: NYC taxi trips, 20.3M rows

Real public data: NYC yellow taxi trips, January to June 2024, as 6 Parquet files (340 MB) and as one 2 GB CSV.
6 questions per file, free model `meituan/longcat-2.5:free`, one run each, 2026-11-09.
True answers come from SQL written by hand for this data (`bench/nyc.py`).
Raw results: `results-nyc.jsonl`.

| File | Setup | Correct | Input tokens (median) | Time (median) | Cost per answer* | Tool calls |
|---|---|---|---|---|---|---|
| Parquet | Plain Hermes | 6/6 | 123,437 | 75 s | $0.0912 | 10 |
| Parquet | Hermes with Grimoire | 6/6 | 23,866 | 12 s | $0.0277 | 1 |
| Parquet | Data bot (Grimoire's tools only) | 6/6 | 5,037 | 12 s | $0.0112 | 1 |
| CSV, 2 GB | Plain Hermes | 6/6 | 58,640 | 111 s | $0.0424 | 4 |
| CSV, 2 GB | Hermes with Grimoire | 6/6 | 23,752 | 17 s | $0.0271 | 1 |
| CSV, 2 GB | Data bot (Grimoire's tools only) | 6/6 | 4,504 | 13 s | $0.0101 | 1 |

*Tokens priced at $3 input, $0.30 cached input and $15 output per million.

What this shows:

- Every setup got every answer right; this model can write DuckDB itself.
- Plain Hermes paid for it: it searched the disk for a Python with pyarrow or a DuckDB binary, wrote scripts, and retried. One run walked the home folder with `find`, which made macOS ask for Music and Photos access.
- With Grimoire every answer took one query. The Data bot used 24 to 25 times fewer input tokens than plain Hermes on Parquet, and 6 to 9 times less time.
- The number check passed 22 of 24 Grimoire answers. The 2 it flagged wrote "hour 18 (6 PM)"; v0.19.2 reads "6 PM" as the hour 18.
- Before v0.19.1 a glob path in the question was not opened in advance, and one answer took 6 calls and 84,807 tokens.

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

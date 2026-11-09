"""Text charts for chats and a self-contained HTML report of saved queries (every number with its SQL)."""

import datetime
import html
import re

BAR = 28


def _numeric(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def chart_columns(columns, rows):
    """(label index, value index) for a label-and-number chart, or None."""
    if not rows or len(rows) < 2:
        return None
    value = next((i for i in range(len(columns)) if all(_numeric(r[i]) or r[i] is None for r in rows)
                  and any(_numeric(r[i]) for r in rows) and i > 0), None)
    if value is None:
        return None
    label = next((i for i in range(len(columns)) if i != value and not all(_numeric(r[i]) for r in rows)), 0)
    return label, value


_TIME = re.compile(r"^\d{4}(-\d{2}(-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?)?)?$")


def is_time(values):
    """True when every label is a year, month, date or timestamp written in ISO form."""
    vals = [str(v) for v in values if v is not None]
    return len(vals) >= 3 and all(_TIME.match(v) for v in vals)


def text_chart(q, limit=25):
    """Unicode bar chart of a saved query result, or an explanation of why not."""
    pick = chart_columns(q["columns"], q["rows"])
    if not pick:
        return f"{q['id']} has no label-and-number columns to chart (it needs 2 or more rows)."
    li, vi = pick
    rows = [r for r in q["rows"] if _numeric(r[vi])][:limit]
    top = max(abs(r[vi]) for r in rows) or 1
    width = max(len(str(r[li])) for r in rows)
    lines = [f"{q['id']}: {q['columns'][vi]} by {q['columns'][li]}"]
    for r in rows:
        n = round(abs(r[vi]) / top * BAR)
        lines.append(f"{str(r[li]):<{width}}  {'█' * n}{'▏' if n == 0 else ''} {_fmt(r[vi])}")
    if len(q["rows"]) > len(rows):
        lines.append(f"... {len(q['rows']) - len(rows)} more rows")
    return "\n".join(lines)


def ticks(n, width, label_px):
    """Indexes of the axis labels to draw: evenly spaced so labels never touch, always the last one."""
    if n <= 1:
        return list(range(n))
    step = width / (n - 1)
    every = max(1, -(-int(label_px * 1.6) // max(1, int(step))))
    keep = [i for i in range(0, n - 1, every) if (n - 1 - i) * step >= label_px * 1.6]
    return keep + [n - 1]


_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]00:00:00$")


def _fmt(v):
    if isinstance(v, str) and _MIDNIGHT.match(v):
        return v[:10]  # a date stored as a timestamp
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return "" if v is None else str(v)


def _short(v):
    """A chart label: 91M or 4.1K for big numbers, the exact value otherwise (tables keep exact values)."""
    return compact(v) if _numeric(v) and abs(v) >= 10000 else _fmt(v)


def compact(v):
    """Short axis label: 8.17M, 4.09K, 12."""
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= size:
            return f"{v / size:.3g}{unit}"
    return f"{v:.3g}"


def _svg_line(q, li, vi):
    rows = sorted((r for r in q["rows"] if _numeric(r[vi]) and r[li] is not None), key=lambda r: str(r[li]))[:120]
    vals = [r[vi] for r in rows]
    lo, hi = min(0, min(vals)), max(vals) or 1
    marks = (lo, (lo + hi) / 2, hi)
    w, h, bottom = 560, 200, 24
    left = 14 + 7 * max(len(compact(v)) for v in marks)
    x = lambda i: left + (w - left - 10) * (i / max(1, len(rows) - 1))
    y = lambda v: 8 + (h - bottom - 8) * (1 - (v - lo) / ((hi - lo) or 1))
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
    shown = ticks(len(rows), w - left - 10, 7 * max(len(str(r[li])[:10]) for r in rows))
    anchor = lambda i: "start" if i == 0 else "end" if i == len(rows) - 1 else "middle"  # keep edge labels inside
    labels = "".join(f'<text x="{x(i):.1f}" y="{h - 6}" text-anchor="{anchor(i)}" class="lbl">{html.escape(str(rows[i][li])[:10])}</text>'
                     for i in shown)
    grid = "".join(f'<line x1="{left}" x2="{w - 10}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                   f'<text x="{left - 6}" y="{y(v) + 4:.1f}" text-anchor="end" class="lbl">{html.escape(compact(v))}</text>'
                   for v in marks)
    dots = "".join(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.5" class="dot"><title>{html.escape(str(r[li]))}: '
                   f'{html.escape(_fmt(v))}</title></circle>' for i, (r, v) in enumerate(zip(rows, vals)))
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(q["columns"][vi])} over '
            f'{html.escape(q["columns"][li])}">{grid}<polyline points="{pts}" class="line"/>{dots}{labels}</svg>')


def chart_kind(columns, rows):
    """Which chart fits a result: line (time), heatmap (two labels and a number), histogram (equal
    buckets and counts), scatter (two numbers), bars (a label and a number), or None."""
    if not rows or len(rows) < 2:
        return None
    nums = _number_columns(columns, rows)
    texts = [i for i in range(len(columns)) if i not in nums]
    if len(columns) == 3 and len(nums) >= 1 and _heatmap_axes(columns, rows, nums):
        return "heatmap"
    if not texts and len(nums) >= 2:
        counts = [r[nums[1]] or 0 for r in rows]
        if _even_steps([r[nums[0]] for r in rows]) and all(c >= 0 and float(c).is_integer() for c in counts):  # counts per bucket
            return "histogram"
        return "scatter" if len(rows) >= 5 else "bars"
    pick = chart_columns(columns, rows)
    if not pick:
        return None
    return "line" if is_time([r[pick[0]] for r in rows]) else "bars"


def _number_columns(columns, rows):
    return [i for i in range(len(columns)) if all(_numeric(r[i]) or r[i] is None for r in rows)
            and any(_numeric(r[i]) for r in rows)]


def _heatmap_axes(columns, rows, nums):
    """(x index, y index, value index) when two columns label a grid of at most 31 by 31, else None."""
    value = nums[-1]
    x, y = [i for i in range(3) if i != value]
    xs, ys = {r[x] for r in rows}, {r[y] for r in rows}
    if None in xs or None in ys or not (2 <= len(xs) <= 31 and 2 <= len(ys) <= 31):
        return None
    if len({(r[x], r[y]) for r in rows}) != len(rows) or len(rows) < 0.5 * len(xs) * len(ys):
        return None  # each cell once, and at least half of the grid filled
    if x in nums and y in nums and len(xs) > 12 and len(ys) > 12:
        return None  # two wide number columns: a scatter, not a grid
    return x, y, value


def _even_steps(values):
    """True for ascending bucket starts with one step: 0, 10, 20, 30 ..."""
    if len(values) < 3 or any(not _numeric(v) for v in values):
        return False
    steps = [b - a for a, b in zip(values, values[1:])]
    return steps[0] > 0 and all(abs(st - steps[0]) <= 1e-9 + 0.01 * steps[0] for st in steps)


_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]


def _order(values):
    """Numbers ascending; weekday and month names in calendar order (full or 3-letter); other text A to Z."""
    def key(v):
        if _numeric(v):
            return (0, v, "")
        t = str(v).strip().lower()
        for group, names in ((1, _DAYS), (2, _MONTHS)):
            hit = next((i for i, n in enumerate(names) if t in (n, n[:3])), None)
            if hit is not None:
                return (group, hit, "")
        return (3, 0, t)
    return sorted(values, key=key)


def _svg_heatmap(q):
    x, y, vi = _heatmap_axes(q["columns"], q["rows"], _number_columns(q["columns"], q["rows"]))
    if len({r[x] for r in q["rows"]}) < len({r[y] for r in q["rows"]}):
        x, y = y, x  # the axis with more values runs across
    xs, ys = _order({r[x] for r in q["rows"]}), _order({r[y] for r in q["rows"]})
    cell = {(r[x], r[y]): r[vi] for r in q["rows"] if _numeric(r[vi])}
    lo, hi = min(cell.values(), default=0), max(cell.values(), default=1)
    w, ch, top = 560, 22, 22
    left = 14 + 7 * max(len(str(v)[:14]) for v in ys)
    cw = (w - left - 4) / len(xs)
    h = top + ch * len(ys)
    cut = lambda v: str(v) if len(str(v)) <= 12 else str(v)[:11] + "…"
    every = max(1, -(-7 * max(len(cut(v)) for v in xs) // max(1, int(cw) - 4)))
    parts = [f'<text x="{left + cw * i + cw / 2:.1f}" y="14" text-anchor="middle" class="lbl">{html.escape(cut(v))}</text>'
             for i, v in enumerate(xs) if i % every == 0]
    for j, yv in enumerate(ys):
        parts.append(f'<text x="{left - 8}" y="{top + ch * j + 15}" text-anchor="end" class="lbl">{html.escape(str(yv)[:14])}</text>')
        for i, xv in enumerate(xs):
            v = cell.get((xv, yv))
            if v is None:
                continue
            step = round(6 * (v - lo) / ((hi - lo) or 1))  # 7 steps of one blue ramp, light to dark (dark mode: reversed)
            parts.append(f'<rect x="{left + cw * i + 1:.1f}" y="{top + ch * j + 1}" width="{max(1, cw - 2):.1f}" height="{ch - 2}" '
                         f'rx="2" class="cell h{step}"><title>{html.escape(str(xv))}, {html.escape(str(yv))}: '
                         f'{html.escape(_fmt(v))}</title></rect>')
    parts.append(f'<text x="{left}" y="{h + 16}" class="lbl">Stronger color = more {html.escape(q["columns"][vi])}: '
                 f'from {html.escape(_fmt(lo))} to {html.escape(_fmt(hi))}.</text>')
    return (f'<svg viewBox="0 0 {w} {h + 22}" role="img" aria-label="{html.escape(q["columns"][vi])} by '
            f'{html.escape(q["columns"][x])} and {html.escape(q["columns"][y])}">' + "".join(parts) + "</svg>")


def _axis(lo, hi):
    return (lo, (lo + hi) / 2, hi)


def _svg_histogram(q):
    rows = q["rows"][:120]
    starts, counts = [r[0] for r in rows], [r[1] or 0 for r in rows]
    step = starts[1] - starts[0]
    top = max(counts) or 1
    w, h, bottom = 560, 200, 24
    left = 14 + 7 * max(len(compact(v)) for v in _axis(0, top))
    bw = (w - left - 10) / len(rows)
    y = lambda v: 8 + (h - bottom - 8) * (1 - v / top)
    grid = "".join(f'<line x1="{left}" x2="{w - 10}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                   f'<text x="{left - 6}" y="{y(v) + 4:.1f}" text-anchor="end" class="lbl">{html.escape(compact(v))}</text>'
                   for v in _axis(0, top))
    bars = "".join(f'<rect x="{left + bw * i + 1:.1f}" y="{y(c):.1f}" width="{max(1, bw - 2):.1f}" height="{max(0, y(0) - y(c)):.1f}" '
                   f'rx="2" class="bar"><title>{html.escape(_fmt(s_))} to {html.escape(_fmt(s_ + step))}: {html.escape(_fmt(c))}'
                   f'</title></rect>' for i, (s_, c) in enumerate(zip(starts, counts)))
    labels = "".join(f'<text x="{left + bw * i:.1f}" y="{h - 6}" text-anchor="{"start" if i == 0 else "middle"}" class="lbl">'
                     f'{html.escape(compact(starts[i]))}</text>' for i in ticks(len(rows), w - left - 10, 7 * max(len(compact(v)) for v in starts))
                     if i < len(rows) - 1 or len(rows) == 1)
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(q["columns"][1])} per bucket of '
            f'{html.escape(q["columns"][0])}">{grid}{bars}{labels}</svg>')


def _svg_scatter(q):
    pts = [(r[0], r[1]) for r in q["rows"] if _numeric(r[0]) and _numeric(r[1])]
    xs, ys = [p_[0] for p_ in pts], [p_[1] for p_ in pts]
    xlo, xhi, ylo, yhi = min(xs), max(xs), min(0, min(ys)), max(ys)
    w, h, bottom, top = 560, 240, 40, 22
    left = 14 + 7 * max(len(compact(v)) for v in _axis(ylo, yhi))
    x = lambda v: left + 6 + (w - left - 20) * ((v - xlo) / ((xhi - xlo) or 1))
    y = lambda v: top + (h - bottom - top) * (1 - (v - ylo) / ((yhi - ylo) or 1))
    grid = "".join(f'<line x1="{left}" x2="{w - 10}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                   f'<text x="{left - 6}" y="{y(v) + 4:.1f}" text-anchor="end" class="lbl">{html.escape(compact(v))}</text>'
                   for v in _axis(ylo, yhi))
    ticks = "".join(f'<text x="{x(v):.1f}" y="{h - 22}" text-anchor="middle" class="lbl">{html.escape(compact(v))}</text>'
                    for v in _axis(xlo, xhi))
    names = (f'<text x="{left}" y="12" class="lbl">{html.escape(q["columns"][1])} ↑</text>'
             f'<text x="{(left + w) / 2:.1f}" y="{h - 4}" text-anchor="middle" class="lbl">{html.escape(q["columns"][0])} →</text>')
    dots = "".join(f'<circle cx="{x(a):.1f}" cy="{y(b):.1f}" r="4" class="pt"><title>{html.escape(q["columns"][0])} '
                   f'{html.escape(_fmt(a))}, {html.escape(q["columns"][1])} {html.escape(_fmt(b))}</title></circle>' for a, b in pts)
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(q["columns"][1])} against '
            f'{html.escape(q["columns"][0])}">{grid}{ticks}{names}{dots}</svg>')


def chart_data(q, limit=200):
    """Plain data for the Desktop page to draw a heatmap, histogram or scatter itself; None otherwise."""
    kind = chart_kind(q["columns"], q["rows"])
    rows, cols = q["rows"][:limit], q["columns"]
    try:
        if kind == "heatmap":
            x, y, vi = _heatmap_axes(cols, rows, _number_columns(cols, rows))
            if len({r[x] for r in rows}) < len({r[y] for r in rows}):
                x, y = y, x  # the axis with more values runs across, as in the report
            xs, ys = _order({r[x] for r in rows}), _order({r[y] for r in rows})
            xi, yi = {v: i for i, v in enumerate(xs)}, {v: i for i, v in enumerate(ys)}
            cells = [[xi[r[x]], yi[r[y]], r[vi]] for r in rows if _numeric(r[vi])]
            return {"kind": kind, "x": cols[x], "y": cols[y], "value": cols[vi],
                    "xs": [str(v) for v in xs], "ys": [str(v) for v in ys], "cells": cells}
        if kind == "histogram":
            return {"kind": kind, "x": cols[0], "y": cols[1], "starts": [r[0] for r in rows],
                    "counts": [r[1] or 0 for r in rows], "step": rows[1][0] - rows[0][0]}
        if kind == "scatter":
            return {"kind": kind, "x": cols[0], "y": cols[1],
                    "points": [[r[0], r[1]] for r in rows if _numeric(r[0]) and _numeric(r[1])]}
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    return None


def chart_svg(q):
    """The chart that fits a saved query result, as inline SVG; "" when none fits."""
    kind = chart_kind(q["columns"], q["rows"])
    try:
        if kind == "heatmap":
            return _svg_heatmap(q)
        if kind == "histogram":
            return _svg_histogram(q)
        if kind == "scatter":
            return _svg_scatter(q)
    except (TypeError, ValueError, ZeroDivisionError):
        return ""  # mixed or odd values: show the table only
    return _svg_bars(q) if kind in ("bars", "line") else ""


def _svg_bars(q):
    pick = chart_columns(q["columns"], q["rows"])
    if not pick:
        return ""
    li, vi = pick
    if is_time([r[li] for r in q["rows"]]):
        return _svg_line(q, li, vi)
    rows = [r for r in q["rows"] if _numeric(r[vi])][:25]
    top = max(abs(r[vi]) for r in rows) or 1
    h, bar_w = 22, 360
    label_w = 16 + 7 * max(len(str(r[li])[:20]) for r in rows)  # about 7 px per character at 12 px
    parts = [f'<svg viewBox="0 0 {label_w + bar_w + 120} {len(rows) * h + 8}" role="img" '
             f'aria-label="{html.escape(q["columns"][vi])} by {html.escape(q["columns"][li])}">']
    for i, r in enumerate(rows):
        y = i * h + 4
        w = max(1, abs(r[vi]) / top * bar_w)
        parts.append(f'<text x="{label_w - 8}" y="{y + 15}" text-anchor="end" class="lbl">'
                     f'{html.escape(str(r[li])[:20])}</text>')
        parts.append(f'<rect x="{label_w}" y="{y + 3}" width="{w:.1f}" height="{h - 8}" rx="2" class="bar{' neg' if r[vi] < 0 else ''}"/>')
        parts.append(f'<text x="{label_w + w + 6:.1f}" y="{y + 15}" class="val">{html.escape(_short(r[vi]))}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _table(q, limit=50):
    nums = [bool(q["rows"]) and all(_numeric(r[i]) or r[i] is None for r in q["rows"]) for i in range(len(q["columns"]))]
    head = "".join(f'<th class="{"num" if n else ""}" aria-sort="none"><button type="button" data-num="{int(n)}">'
                   f'{html.escape(c)}</button></th>' for c, n in zip(q["columns"], nums))
    whole = [n and all(v is None or float(v).is_integer() for v in (r[i] for r in q["rows"])) for i, n in enumerate(nums)]
    show = lambda v, i: _fmt(int(v)) if whole[i] and isinstance(v, float) else _fmt(v)  # 5.0 buckets read as 5
    body = []
    for r in q["rows"][:limit]:
        cells = "".join(f'<td class="{"num" if _numeric(v) else ""}"' + (f' data-v="{v!r}"' if _numeric(v) else "")
                        + f'>{html.escape(show(v, i))}</td>' for i, v in enumerate(r))
        body.append(f"<tr>{cells}</tr>")
    more = (f'<p class="muted">{len(q["rows"]) - limit} more rows not shown.</p>'
            if len(q["rows"]) > limit else "")
    return f'<div class="tw"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>{more}'


def _issue_text(i):
    if i.get("issue") == "duplicate rows":
        return f"{i['rows']:,} duplicate rows"
    if i.get("issue") == "empty values":
        return f"{i['column']}: {i['percent']}% empty"
    if i.get("issue") == "spelling variants of one value":
        return f"{i['column']}: " + " / ".join(f"'{v['value']}'" for v in i["variants"])
    rows = f" ({i['rows']:,} rows)" if i.get("rows") else ""
    return f"{i.get('column', '')}: {i.get('issue', '')}{rows}"


def _files(files, metrics):
    """The data behind the report: each file's health and problems, column notes, saved metrics."""
    if not files and not metrics:
        return ""
    items = []
    for f in files:
        h = f.get("health")
        chip = (f'<span class="chip" title="{html.escape(", ".join(h["off"]) or "No problems found")}">Health {h["score"]}/100</span>'
                if h else "")
        probs = "".join(f"<li>{html.escape(_issue_text(i))}</li>" for i in f.get("issues", [])[:8])
        notes = "".join(f"<li><b>{html.escape(c)}</b>: {html.escape(t)}</li>" for c, t in f.get("notes", []))
        items.append(f'<div class="file"><h3>{html.escape(f["name"])} {chip}</h3>'
                     + (f'<p class="muted">Data problems</p><ul>{probs}</ul>' if probs else '<p class="muted">No data problems found.</p>')
                     + (f'<p class="muted">Column notes</p><ul>{notes}</ul>' if notes else "") + "</div>")
    defs = "".join(f"<li><code>{html.escape(n)}()</code> = <code>{html.escape(e)}</code></li>" for n, e in metrics.items())
    return ('<section class="about"><h2>About the data</h2>' + "".join(items)
            + (f'<p class="muted">Saved metrics used</p><ul>{defs}</ul>' if defs else "") + "</section>")


def _queries(n):
    return f"{n} query" if n == 1 else f"{n} queries"


def _toolbar(queries):
    names = sorted({n for q in queries for n in q["datasets"]})
    pick = ("" if len(names) < 2 else '<select id="file" aria-label="File"><option value="">All files</option>'
            + "".join(f'<option>{html.escape(n)}</option>' for n in names) + "</select>")
    return (f'<div class="bar-tools" role="search">{pick}<input id="find" type="search" placeholder="Filter queries" '
            f'aria-label="Filter queries"><span id="count" class="muted" aria-live="polite">{_queries(len(queries))}</span></div>')


def _section(q, caveats=()):
    title = html.escape(q["purpose"] or q["question"] or q["id"])
    question = f'<p class="q">Question: {html.escape(q["question"])}</p>' if q.get("question") else ""
    if len(q["rows"]) == 1 and len(q["columns"]) <= 4 and all(_numeric(v) or v is None for v in q["rows"][0]):
        body = '<div class="kpis">' + "".join(
            f'<div class="kpi"><div class="kv">{html.escape(_fmt(v))}</div><div class="kl">{html.escape(c)}</div></div>'
            for c, v in zip(q["columns"], q["rows"][0])) + "</div>"
    else:
        body = chart_svg(q) + _table(q)
    when = datetime.datetime.fromtimestamp(q["created_at"]).strftime("%Y-%m-%d %H:%M")
    warn = ("".join(f"<li>{html.escape(c)}</li>" for c in caveats))
    body += f'<div class="caveats"><b>Caveats</b><ul>{warn}</ul></div>' if warn else ""
    text = html.escape(" ".join(str(x) for x in (q["id"], q["purpose"], q["question"], q["sql"]) if x).lower())
    return (f'<section id="{q["id"]}" class="query" data-files="{html.escape("|".join(q["datasets"]))}" data-text="{text}">'
            f'<h2><span class="qid">{q["id"]}</span> {title}</h2>{question}{body}'
            f'<details><summary>SQL behind these numbers</summary><pre>{html.escape(q["sql"])}</pre></details>'
            f'<p class="muted">Run {when} · files: {html.escape(", ".join(q["datasets"]) or "unknown")}</p></section>')


CSS = """
:root{--bg:#f6f7f5;--card:#fff;--fg:#1c2421;--muted:#5d6b66;--line:#dde3e0;--accent:#0f766e;--code:#eef2f0;--s1:#2a78d6;--neg:#e34948;
--h0:#cde2fb;--h1:#9ec5f4;--h2:#6da7ec;--h3:#3987e5;--h4:#256abf;--h5:#184f95;--h6:#0d366b}
@media (prefers-color-scheme:dark){:root{--bg:#0f1514;--card:#162020;--fg:#e3ebe8;--muted:#93a39e;--line:#26332f;--accent:#3cc4b4;--code:#1d2a28;--s1:#3987e5;--neg:#e66767;
--h0:#0d366b;--h1:#104281;--h2:#184f95;--h3:#256abf;--h4:#3987e5;--h5:#6da7ec;--h6:#b7d3f6}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,system-ui,"Segoe UI",sans-serif;padding:32px 16px}
main{max-width:860px;margin:0 auto;display:flex;flex-direction:column;gap:20px}
h1{font-size:1.7rem;margin:0}h2{font-size:1.1rem;margin:0 0 8px}.qid{font:600 .8rem ui-monospace,Menlo,monospace;color:var(--accent);margin-right:6px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px}
.q,.muted{color:var(--muted);font-size:.88rem;margin:4px 0}.kpis{display:flex;flex-wrap:wrap;gap:12px}
.kpi{border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-width:140px}.kv{font-size:1.5rem;font-weight:650;font-variant-numeric:tabular-nums}.kl{color:var(--muted);font-size:.8rem}
svg{width:100%;max-width:620px;margin:6px 0}.bar{fill:var(--s1)}.bar.neg{fill:var(--neg)}.lbl,.val{fill:var(--fg);font-size:12px}
.h0{fill:var(--h0)}.h1{fill:var(--h1)}.h2{fill:var(--h2)}.h3{fill:var(--h3)}.h4{fill:var(--h4)}.h5{fill:var(--h5)}.h6{fill:var(--h6)}
.pt{fill:var(--s1);stroke:var(--card);stroke-width:2}
.line{fill:none;stroke:var(--s1);stroke-width:2}.dot{fill:var(--s1)}.grid{stroke:var(--line);stroke-width:1}.lbl{fill:var(--muted)}
.tw{overflow:auto;max-height:360px;margin-top:8px}table{border-collapse:collapse;font-size:.88rem}th,td{text-align:left;padding:5px 10px;border-bottom:1px solid var(--line)}th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
th{position:sticky;top:0;background:var(--card)}th button{all:unset;cursor:pointer;font-weight:600}th button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
th[aria-sort=ascending] button::after{content:" ▲";font-size:.7em}th[aria-sort=descending] button::after{content:" ▼";font-size:.7em}
.bar-tools{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.bar-tools input,.bar-tools select{font:inherit;color:var(--fg);background:var(--card);border:1px solid var(--line);border-radius:7px;padding:6px 10px}
.bar-tools input{flex:1;min-width:180px}.about h3{font-size:1rem;margin:8px 0 2px;display:flex;gap:8px;align-items:center}
.about ul,.caveats ul{margin:2px 0 8px;padding-left:20px}.chip{font-size:.75rem;font-weight:500;padding:1px 8px;border-radius:5px;background:var(--code);color:var(--muted)}
.caveats{margin-top:10px;padding:8px 12px;border-left:3px solid var(--accent);background:var(--code);border-radius:4px;font-size:.9rem}
section[hidden]{display:none}
details{margin-top:10px}pre{background:var(--code);padding:10px;border-radius:6px;overflow-x:auto;font-size:.82rem}
"""


SCRIPT = """
const q=[...document.querySelectorAll('section.query')],find=document.getElementById('find'),file=document.getElementById('file'),
count=document.getElementById('count');
function filter(){const t=find.value.trim().toLowerCase(),f=file?file.value:'';let n=0;
q.forEach(s=>{const ok=(!t||s.dataset.text.includes(t))&&(!f||s.dataset.files.split('|').includes(f));s.hidden=!ok;n+=ok});
const w=k=>k===1?' query':' queries';count.textContent=n===q.length?q.length+w(q.length):n+' of '+q.length+w(q.length)}
find.addEventListener('input',filter);if(file)file.addEventListener('change',filter);
document.querySelectorAll('th button').forEach(b=>b.addEventListener('click',()=>{const th=b.parentElement,
tr=th.parentElement,i=[...tr.children].indexOf(th),body=th.closest('table').tBodies[0],
dir=th.getAttribute('aria-sort')==='ascending'?'descending':'ascending',num=b.dataset.num==='1';
[...tr.children].forEach(c=>c.setAttribute('aria-sort','none'));th.setAttribute('aria-sort',dir);
const key=r=>{const c=r.children[i];return num?parseFloat(c.dataset.v??'NaN'):c.textContent};
[...body.rows].sort((a,b)=>{let x=key(a),y=key(b);if(num){x=isNaN(x)?-Infinity:x;y=isNaN(y)?-Infinity:y}
const c=num?x-y:String(x).localeCompare(String(y),undefined,{numeric:true});return dir==='ascending'?c:-c})
.forEach(r=>body.appendChild(r))}));
"""


def html_report(queries, title, context=None):
    context = context or {}
    caveats = context.get("caveats", {})
    sections = (_toolbar(queries) + _files(context.get("files", []), context.get("metrics", {}))
                + "".join(_section(q, caveats.get(q["id"], ())) for q in queries))
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style>'
            f'</head><body><main><header><h1>{html.escape(title)}</h1><p class="muted">Made by Grimoire on {now}. '
            f'Every number below comes from the SQL shown under it, run with DuckDB on your files.</p></header>'
            f'{sections}</main><script>{SCRIPT}</script></body></html>')

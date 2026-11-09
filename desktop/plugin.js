import { ROUTES_AREA, SIDEBAR_NAV_AREA, PALETTE_AREA, host, queryClient, useQuery, useMutation, useValue } from '@hermes/plugin-sdk'
import { useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'grimoire'
let pluginCtx

const PATHS = [/^\/summary$/, /^\/queries(\?dataset=[\w-]+)?$/, /^\/queries\/q\d+\/explain$/, /^\/settings$/,
  /^\/merges\/(approve|reject)$/, /^\/datasets\/[\w-]+\/forget$/]

export function assertPath(path) {
  if (!PATHS.some((re) => re.test(path))) throw new Error('Unsupported Grimoire path')
  return path
}

export function errorText(error) {
  const message = error?.detail || error?.error?.message || error?.message || String(error)
  try {
    const parsed = JSON.parse(message)
    return parsed?.detail || parsed?.error?.message || message
  } catch {
    return message
  }
}

async function request(path, options = {}) {
  assertPath(path)
  const result = await pluginCtx.rest(path, { timeoutMs: 15000, ...options })
  if (result?.error || result?.detail) throw new Error(errorText(result))
  return result
}

function useData(path) {
  const profile = useValue(host.state.profile)
  const connectionId = useValue(host.state.connectionId)
  return useQuery({ queryKey: [ID, profile, connectionId, path], queryFn: () => request(path), refetchInterval: 5000, retry: false })
}

function useAction() {
  return useMutation({
    mutationFn: ({ path, body }) => request(path, { method: 'POST', body: body || {} }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [ID] }),
    onError: (error) => host.notify({ kind: 'error', message: errorText(error) })
  })
}

export const isNum = (v) => typeof v === 'number' && Number.isFinite(v)
export function fmt(v) {
  if (v === null || v === undefined) return ''
  if (isNum(v)) return Number.isInteger(v) ? v.toLocaleString('en-US') : v.toLocaleString('en-US', { maximumFractionDigits: 2 })
  const t = String(v)
  return /^\d{4}-\d{2}-\d{2}[T ]00:00:00$/.test(t) ? t.slice(0, 10) : t  // a date stored as a timestamp
}

/** [label index, value index] for a bar chart, or null (same rule as the chat chart). */
export function chartColumns(columns, rows) {
  if (!rows || rows.length < 2) return null
  const value = columns.findIndex((_, i) => i > 0 && rows.every((r) => isNum(r[i]) || r[i] === null) && rows.some((r) => isNum(r[i])))
  if (value < 0) return null
  const label = columns.findIndex((_, i) => i !== value && !rows.every((r) => isNum(r[i])))
  return [label < 0 ? 0 : label, value]
}

function ago(seconds) {
  const s = Math.max(0, Date.now() / 1000 - seconds)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return new Date(seconds * 1000).toISOString().slice(0, 10)
}

// The Grimoire icon: Hermes Trismegistus (engraving by Jean-Louis Durant, 1675, public domain), 64 px.
const ICON = 'data:image/png;base64,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'
const Mark = () => jsx('img', { src: ICON, alt: '', width: 32, height: 32, style: { borderRadius: 8, display: 'block' } })

function Toggle({ label, checked, disabled, onChange, hint }) {
  return jsxs('label', { className: 'gr-toggle', 'data-disabled': disabled || undefined, title: hint, children: [
    jsx('input', { type: 'checkbox', role: 'switch', checked: !!checked, disabled, onChange: (e) => onChange(e.target.checked) }),
    jsx('span', { className: 'gr-switch', 'aria-hidden': true }),
    jsx('span', { children: label })
  ] })
}

function Header({ summary, act }) {
  const s = summary || {}
  const p = s.predictions || { asked: 0, close: 0 }
  return jsxs('header', { className: 'gr-top', children: [
    jsxs('div', { className: 'gr-brand', children: [
      jsx('span', { className: 'gr-mark', children: jsx(Mark, {}) }),
      jsxs('div', { children: [jsx('h1', { children: 'Data' }), jsx('p', { children: `Grimoire ${s.version || ''} · every number has a receipt` })] })
    ] }),
    jsxs('div', { className: 'gr-toggles', children: [
      jsx(Toggle, { label: 'Learning mode', checked: s.learn, hint: 'A short SQL lesson and a better question after data answers',
        onChange: (v) => act.mutate({ path: '/settings', body: { learn: v } }) }),
      jsx(Toggle, { label: s.predict && p.asked ? `Predictions · ${p.close} of ${p.asked} close` : 'Predictions', checked: s.predict, disabled: !s.learn,
        hint: s.learn ? 'Guess the main number before you see it' : 'Turn on learning mode first',
        onChange: (v) => act.mutate({ path: '/settings', body: { predict: v } }) })
    ] })
  ] })
}

function Pending({ pending, act }) {
  if (!pending?.length) return null
  return jsxs('section', { className: 'gr-pending', role: 'status', children: [
    jsxs('div', { className: 'gr-pending-text', children: [
      jsx('b', { children: `${pending.length} merge${pending.length > 1 ? 's' : ''} waiting for you` }),
      jsx('ul', { children: pending.map((m, i) => jsxs('li', { children: [jsx('code', { children: `${m.dataset}.${m.column}` }), ` '${m.from}' → '${m.to}'`] }, i)) })
    ] }),
    jsxs('div', { className: 'gr-actions', children: [
      jsx('button', { className: 'gr-cta', onClick: () => act.mutate({ path: '/merges/approve' }), children: 'Apply' }),
      jsx('button', { className: 'gr-btn', onClick: () => act.mutate({ path: '/merges/reject' }), children: 'Drop' })
    ] })
  ] })
}

function LeanTip({ tip, act }) {
  if (!tip) return null
  return jsxs('section', { className: 'gr-lean', 'aria-label': 'Use fewer tokens', children: [
    jsxs('div', { className: 'gr-lean-text', children: [
      jsx('b', { children: 'Use about a fifth of the tokens with a Data bot' }),
      jsx('p', { children: `Your data chats send ${fmt(tip.tools)} tools and about ${fmt(tip.tokens)} tokens with every model call. A bot with only Grimoire's tools sends about a fifth of that, and answers faster.` }),
      jsxs('ol', { children: [
        jsxs('li', { children: ['Open ', jsx('b', { children: 'Bots' }), ', then ', jsx('b', { children: 'New Agent' }), '. Name it Data.'] }),
        jsxs('li', { children: ['Open ', jsx('b', { children: 'Advanced' }), ' and clone from the profile that has Grimoire.'] }),
        jsxs('li', { children: ['Under toolsets, keep only ', jsx('b', { children: 'Grimoire' }), ' and ', jsx('b', { children: 'Clarifying Questions' }), '.'] }),
        jsx('li', { children: "Ask data questions in the Data bot's chat. Your main agent keeps all its tools." })
      ] })
    ] }),
    jsx('button', { className: 'gr-btn gr-small', onClick: () => act.mutate({ path: '/settings', body: { hide_lean_tip: true } }), children: 'Hide' })
  ] })
}

function issueText(i) {
  if (i.issue === 'duplicate rows') return `${fmt(i.rows)} duplicate rows`
  if (i.issue === 'empty values') return `${i.column}: ${fmt(i.percent)}% empty`
  if (i.rows) return `${i.column}: ${i.issue} (${fmt(i.rows)} rows)`
  if (i.issue === 'spelling variants of one value') return `${i.column}: ${i.variants.map((v) => `'${v.value}'`).join(' / ')}`
  return `${i.column}: ${i.issue}`
}

function Files({ datasets, act, filter, setFilter }) {
  const [armed, setArmed] = useState(null)
  if (!datasets?.length) return jsx('p', { className: 'gr-empty', children: 'No data files yet. Ask Hermes a question about a CSV, JSON, Parquet or SQLite file.' })
  return jsx('div', { className: 'gr-files', children: datasets.map((d) => jsxs('article', { className: 'gr-file', 'aria-current': filter === d.name || undefined, children: [
    jsxs('div', { className: 'gr-file-top', children: [
      jsx('button', { className: 'gr-link', onClick: () => setFilter(filter === d.name ? null : d.name), title: 'Show only this file\'s queries', children: d.name }),
      jsx('span', { className: 'gr-chip', children: d.kind }),
      d.health ? jsx('span', { className: 'gr-chip gr-health', 'data-level': d.health.score >= 90 ? 'good' : d.health.score >= 70 ? 'fair' : 'poor',
        title: d.health.off.length ? `Health ${d.health.score}/100: ${d.health.off.join(', ')}` : 'No data problems found', children: `Health ${d.health.score}` }) : null,
      d.missing ? jsx('span', { className: 'gr-chip gr-warn', children: 'file missing' }) : null,
      jsx('button', { className: 'gr-btn gr-small gr-push', 'data-armed': armed === d.name || undefined,
        onClick: () => { if (armed === d.name) { setArmed(null); act.mutate({ path: `/datasets/${d.name}/forget` }) } else setArmed(d.name) },
        onBlur: () => setArmed(null),
        children: armed === d.name ? 'Click again to delete' : 'Forget' })
    ] }),
    jsx('div', { className: 'gr-path', title: d.path, children: d.path }),
    d.issues?.length ? jsx('div', { className: 'gr-chips', children: d.issues.slice(0, 4).map((i, n) => jsx('span', { className: 'gr-chip gr-issue', children: issueText(i) }, n)) }) : null,
    d.merges?.length ? jsx('div', { className: 'gr-meta', children: 'Merges: ' + d.merges.map((m) => `${m.column} '${m.from}' → '${m.to}'`).join(' · ') }) : null,
    d.notes?.length ? jsx('div', { className: 'gr-meta', children: 'Notes: ' + d.notes.map((n) => `${n.column}: ${n.note}`).join(' · ') }) : null
  ] }, d.name)) })
}

const TIME = /^\d{4}(-\d{2}(-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?)?)?$/
export const isTime = (values) => {
  const vals = values.filter((v) => v !== null && v !== undefined).map(String)
  return vals.length >= 3 && vals.every((v) => TIME.test(v))
}

export function compact(v) {
  for (const [size, unit] of [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']]) if (Math.abs(v) >= size) return `${Number((v / size).toPrecision(3))}${unit}`
  return `${Number(v.toPrecision(3))}`
}

/** Axis labels to draw: evenly spaced so they never touch, always the last one (same rule as report.ticks). */
export function ticks(n, width, labelPx) {
  if (n <= 1) return [...Array(n).keys()]
  const step = width / (n - 1)
  const every = Math.max(1, Math.ceil(Math.floor(labelPx * 1.6) / Math.max(1, Math.floor(step))))
  const keep = []
  for (let i = 0; i < n - 1; i += every) if ((n - 1 - i) * step >= labelPx * 1.6) keep.push(i)
  return [...keep, n - 1]
}

function Line({ q, li, vi }) {
  const rows = q.rows.filter((r) => isNum(r[vi]) && r[li] !== null).sort((a, b) => String(a[li]).localeCompare(String(b[li]))).slice(0, 120)
  const vals = rows.map((r) => r[vi])
  const lo = Math.min(0, ...vals), hi = Math.max(...vals) || 1
  const marks = [lo, (lo + hi) / 2, hi]
  const W = 560, H = 190, B = 22, L = 14 + 7 * Math.max(...marks.map((v) => compact(v).length))
  const x = (i) => L + (W - L - 10) * (i / Math.max(1, rows.length - 1))
  const y = (v) => 8 + (H - B - 8) * (1 - (v - lo) / (hi - lo || 1))
  return jsxs('svg', { className: 'gr-line', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `${q.columns[vi]} over ${q.columns[li]}`, children: [
    ...marks.map((v, i) => jsxs('g', { children: [
      jsx('line', { x1: L, x2: W - 10, y1: y(v), y2: y(v), className: 'gr-grid' }),
      jsx('text', { x: L - 6, y: y(v) + 4, textAnchor: 'end', className: 'gr-tick', children: compact(v) })
    ] }, 'g' + i)),
    jsx('polyline', { points: vals.map((v, i) => `${x(i)},${y(v)}`).join(' '), className: 'gr-path-line' }, 'p'),
    ...rows.map((r, i) => jsx('circle', { cx: x(i), cy: y(r[vi]), r: 2.5, className: 'gr-dot', children: jsx('title', { children: `${r[li]}: ${fmt(r[vi])}` }) }, 'd' + i)),
    ...ticks(rows.length, W - L - 10, 7 * Math.max(...rows.map((r) => String(r[li]).slice(0, 10).length))).map((i) =>
      jsx('text', { x: x(i), y: H - 5, textAnchor: i === 0 ? 'start' : i === rows.length - 1 ? 'end' : 'middle', className: 'gr-tick', children: String(rows[i][li]).slice(0, 10) }, 't' + i))
  ] })
}

function Bars({ q }) {
  const pick = chartColumns(q.columns, q.rows)
  if (!pick) return null
  const [li, vi] = pick
  if (isTime(q.rows.map((r) => r[li]))) return jsx(Line, { q, li, vi })
  const rows = q.rows.filter((r) => isNum(r[vi])).slice(0, 25)
  const top = Math.max(...rows.map((r) => Math.abs(r[vi]))) || 1
  return jsx('div', { className: 'gr-bars', role: 'img', 'aria-label': `${q.columns[vi]} by ${q.columns[li]}`, children: rows.map((r, i) => jsxs('div', { className: 'gr-bar-row', children: [
    jsx('span', { className: 'gr-bar-label', title: String(r[li]), children: fmt(r[li]) }),
    jsx('span', { className: 'gr-bar-track', children: jsx('span', { className: 'gr-bar', style: { width: `${(Math.abs(r[vi]) / top) * 100}%` } }) }),
    jsx('span', { className: 'gr-bar-value', title: fmt(r[vi]), children: Math.abs(r[vi]) >= 10000 ? compact(r[vi]) : fmt(r[vi]) })
  ] }, i)) })
}

function Result({ q }) {
  if (q.rows.length === 1 && q.columns.length <= 4 && q.rows[0].every((v) => isNum(v) || v === null))
    return jsx('div', { className: 'gr-kpis', children: q.columns.map((c, i) => jsxs('div', { className: 'gr-kpi', children: [jsx('b', { children: fmt(q.rows[0][i]) }), jsx('span', { children: c })] }, c)) })
  const numeric = q.columns.map((_, i) => q.rows.length > 0 && q.rows.every((r) => isNum(r[i]) || r[i] === null))
  return jsxs('div', { children: [
    q.chart?.svg
      // Drawn by the plugin's own report code; every value in it is HTML-escaped there.
      ? jsx('div', { className: 'gr-svg', dangerouslySetInnerHTML: { __html: q.chart.svg } })
      : jsx(Bars, { q }),
    jsx('div', { className: 'gr-table-wrap', children: jsxs('table', { className: 'gr-table', children: [
      jsx('thead', { children: jsx('tr', { children: q.columns.map((c, i) => jsx('th', { className: numeric[i] ? 'gr-num' : '', children: c }, i)) }) }),
      jsx('tbody', { children: q.rows.map((r, n) => jsx('tr', { children: r.map((v, i) => jsx('td', { className: numeric[i] ? 'gr-num' : '', children: fmt(v) }, i)) }, n)) })
    ] }) }),
    q.total_rows > q.rows.length || q.truncated ? jsx('p', { className: 'gr-muted', children: `Showing ${q.rows.length} of ${q.truncated ? 'more than ' : ''}${fmt(q.total_rows)} rows.` }) : null
  ] })
}

function Explain({ id }) {
  const data = useData(`/queries/${id}/explain`)
  if (data.isLoading) return jsx('p', { className: 'gr-muted', children: 'Loading…' })
  if (data.error) return jsx('p', { className: 'gr-error', children: errorText(data.error) })
  return jsx('pre', { className: 'gr-explain', children: data.data.text })
}

function Detail({ q }) {
  const [explain, setExplain] = useState(false)
  const copy = () => navigator.clipboard.writeText(q.sql).then(
    () => host.notify({ kind: 'success', message: `Copied the SQL of ${q.id}` }),
    () => host.notify({ kind: 'error', message: 'Could not copy. Select the SQL and copy it.' }))
  return jsxs('div', { className: 'gr-detail', children: [
    jsxs('div', { className: 'gr-detail-head', children: [
      jsx('span', { className: 'gr-qid', children: q.id }),
      jsx('h2', { children: q.purpose || 'Query' })
    ] }),
    q.question ? jsx('p', { className: 'gr-question', children: `“${q.question}”` }) : null,
    jsx(Result, { q }),
    jsxs('div', { className: 'gr-sql-head', children: [
      jsx('span', { children: 'SQL behind these numbers' }),
      jsx('button', { className: 'gr-btn gr-small', onClick: copy, children: 'Copy' }),
      jsx('button', { className: 'gr-btn gr-small', 'aria-expanded': explain, onClick: () => setExplain(!explain), children: explain ? 'Hide explanation' : 'Explain' })
    ] }),
    jsx('pre', { className: 'gr-sql', children: q.sql }),
    explain ? jsx(Explain, { id: q.id }) : null,
    jsx('p', { className: 'gr-muted', children: `${ago(q.created_at)} · ${q.datasets.join(', ') || 'unknown file'} · type /grimoire rerun ${q.id} in chat to check it still holds` })
  ] })
}

function Queries({ filter }) {
  const data = useData(filter ? `/queries?dataset=${filter}` : '/queries')
  const [selected, setSelected] = useState(null)
  if (data.isLoading) return jsx('p', { className: 'gr-muted gr-pad', children: 'Loading…' })
  if (data.error) return jsx('p', { className: 'gr-error gr-pad', children: errorText(data.error) })
  const list = data.data.queries || []
  if (!list.length) return jsx('p', { className: 'gr-empty', children: 'No saved queries yet. Every answer about your data saves one here, with its SQL.' })
  const current = list.find((q) => q.id === selected) || list[0]
  return jsxs('div', { className: 'gr-split', children: [
    jsx('nav', { className: 'gr-list', 'aria-label': 'Saved queries', children: list.map((q) => jsxs('button', { className: 'gr-item', 'aria-current': q.id === current.id || undefined, onClick: () => setSelected(q.id), children: [
      jsxs('span', { className: 'gr-item-top', children: [jsx('span', { className: 'gr-qid', children: q.id }), jsx('b', { children: q.purpose || q.question || q.sql })] }),
      jsx('span', { className: 'gr-item-sub', children: `${ago(q.created_at)} · ${q.datasets.join(', ')}` })
    ] }, q.id)) }),
    jsx(Detail, { q: current }, current.id)
  ] })
}

function GrimoirePage() {
  const summary = useData('/summary')
  const act = useAction()
  const [filter, setFilter] = useState(null)
  return jsxs('div', { className: 'gr-page', children: [
    jsx('style', { children: CSS }),
    jsx(Header, { summary: summary.data, act }),
    summary.error ? jsx('p', { className: 'gr-error gr-pad', children: `Grimoire is not reachable: ${errorText(summary.error)}. Check that the plugin is enabled.` }) : null,
    jsxs('main', { className: 'gr-body', children: [
      jsx(Pending, { pending: summary.data?.pending, act }),
      jsx(LeanTip, { tip: summary.data?.lean_tip, act }),
      jsxs('section', { children: [jsx('h3', { className: 'gr-h', children: 'Files' }), jsx(Files, { datasets: summary.data?.datasets, act, filter, setFilter })] }),
      summary.data?.metrics?.length ? jsxs('section', { children: [
        jsx('h3', { className: 'gr-h', children: 'Saved metrics' }),
        jsx('div', { className: 'gr-chips', children: summary.data.metrics.map((m) => jsxs('span', { className: 'gr-chip gr-metric', title: 'Remove with /grimoire undefine ' + m.name, children: [jsx('b', { children: `${m.name}()` }), ` = ${m.expression}`] }, m.name)) })
      ] }) : null,
      jsxs('section', { className: 'gr-grow', children: [
        jsxs('h3', { className: 'gr-h', children: ['Saved queries', filter ? jsx('button', { className: 'gr-chip gr-filter', onClick: () => setFilter(null), children: `${filter} ×` }) : null] }),
        jsx(Queries, { filter }, filter || 'all')
      ] })
    ] })
  ] })
}

const CSS = `
.gr-page{height:100%;min-height:0;display:flex;flex-direction:column;color:var(--foreground);font-size:13px;overflow:hidden;container-type:inline-size}
.gr-page *{box-sizing:border-box}.gr-page :focus-visible{outline:2px solid var(--ui-accent);outline-offset:-2px}
.gr-muted{color:var(--ui-text-tertiary);font-size:12px;margin:8px 0 0}.gr-error{color:var(--ui-red,var(--ui-error,var(--foreground)))}.gr-pad{padding:0 20px}
.gr-empty{color:var(--ui-text-tertiary);margin:6px 0 0}
.gr-top{display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding:16px 20px 12px;border-bottom:1px solid var(--ui-stroke-secondary)}
.gr-brand{display:flex;align-items:center;gap:10px;min-width:0}.gr-brand h1{margin:0;font-size:16px;font-weight:600}.gr-brand p{margin:1px 0 0;font-size:12px;color:var(--ui-text-tertiary)}
.gr-mark{width:32px;height:32px;flex:none;border-radius:8px;overflow:hidden}
.gr-toggles{margin-left:auto;display:flex;gap:16px;flex-wrap:wrap}
.gr-toggle{display:inline-flex;align-items:center;gap:8px;cursor:pointer;color:var(--ui-text-secondary)}.gr-toggle[data-disabled]{opacity:.5;cursor:default}
.gr-toggle input{position:absolute;opacity:0;width:1px;height:1px}
.gr-switch{width:28px;height:16px;border-radius:8px;background:var(--ui-stroke-secondary);position:relative;transition:background .15s;flex:none}
.gr-switch::after{content:'';position:absolute;top:2px;left:2px;width:12px;height:12px;border-radius:50%;background:var(--background);transition:transform .15s}
.gr-toggle input:checked+.gr-switch{background:var(--ui-accent)}.gr-toggle input:checked+.gr-switch::after{transform:translateX(12px)}
.gr-toggle input:focus-visible+.gr-switch{outline:2px solid var(--ui-accent);outline-offset:2px}
.gr-body{flex:1;min-height:0;overflow:auto;padding:16px 20px 24px;display:flex;flex-direction:column;gap:18px}
.gr-h{margin:0 0 8px;font-size:12px;font-weight:500;color:var(--ui-text-secondary);display:flex;align-items:center;gap:8px}
.gr-pending{display:flex;gap:16px;align-items:center;flex-wrap:wrap;padding:12px 14px;border-radius:8px;border:1px solid color-mix(in srgb,var(--ui-accent) 40%,transparent);background:color-mix(in srgb,var(--ui-accent) 8%,transparent)}
.gr-lean{display:flex;gap:16px;align-items:flex-start;padding:12px 14px;border-radius:8px;border:1px solid var(--ui-stroke-secondary)}
.gr-lean-text{flex:1;min-width:0}.gr-lean p{margin:4px 0 0;color:var(--ui-text-secondary)}.gr-lean ol{margin:6px 0 0;padding-left:20px;color:var(--ui-text-secondary);display:flex;flex-direction:column;gap:2px}
.gr-lean ol b{color:var(--foreground);font-weight:500}
.gr-pending-text{flex:1;min-width:0}.gr-pending ul{margin:4px 0 0;padding-left:18px;color:var(--ui-text-secondary)}.gr-actions{display:flex;gap:8px}
.gr-btn{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--ui-stroke-secondary);border-radius:7px;padding:6px 12px;font:inherit;cursor:pointer;color:var(--foreground);background:transparent}
.gr-btn:hover{background:var(--chrome-action-hover)}.gr-small{padding:3px 9px;font-size:12px}.gr-btn[data-armed]{color:var(--ui-red,var(--foreground));border-color:currentColor}
.gr-cta{border:0;border-radius:7px;padding:7px 14px;font:inherit;font-weight:600;cursor:pointer;color:var(--background);background:var(--ui-accent)}
.gr-files{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}
.gr-file{min-width:0;padding:10px 12px;border:1px solid var(--ui-stroke-secondary);border-radius:8px;display:flex;flex-direction:column;gap:5px}
.gr-file[aria-current]{border-color:var(--ui-accent)}
.gr-file-top{display:flex;align-items:center;gap:6px;min-width:0}.gr-push{margin-left:auto}
.gr-link{border:0;padding:0;background:none;font:inherit;font-weight:600;color:var(--foreground);cursor:pointer;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.gr-link:hover{color:var(--ui-accent)}
.gr-path{font-family:var(--font-mono,ui-monospace,monospace);font-size:11px;color:var(--ui-text-tertiary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;direction:rtl;text-align:left}
.gr-chips{display:flex;flex-wrap:wrap;gap:4px}
.gr-chip{display:inline-flex;align-items:center;font-size:11px;padding:1px 7px;border-radius:5px;border:0;font-family:inherit;color:var(--ui-text-secondary);background:var(--chrome-action-hover);white-space:nowrap}
.gr-issue{color:var(--ui-yellow,var(--ui-text-secondary));background:color-mix(in srgb,var(--ui-yellow,var(--ui-text-tertiary)) 14%,transparent);max-width:100%;overflow:hidden;text-overflow:ellipsis}
.gr-health[data-level=good]{color:var(--ui-green,var(--ui-text-secondary))}.gr-health[data-level=fair]{color:var(--ui-yellow,var(--ui-text-secondary))}.gr-health[data-level=poor]{color:var(--ui-red,var(--foreground))}
.gr-warn{color:var(--ui-red,var(--foreground))}.gr-metric{font-family:var(--font-mono,ui-monospace,monospace);white-space:normal}.gr-metric b{font-weight:600;margin-right:2px;color:var(--foreground)}.gr-filter{cursor:pointer}
.gr-meta{font-size:12px;color:var(--ui-text-tertiary);overflow-wrap:anywhere}
.gr-grow{flex:1;min-height:320px;display:flex;flex-direction:column}
.gr-split{flex:1;min-height:0;display:flex;border:1px solid var(--ui-stroke-secondary);border-radius:8px;overflow:hidden}
.gr-list{width:min(38%,340px);min-width:200px;overflow:auto;border-right:1px solid var(--ui-stroke-secondary)}
.gr-item{display:block;width:100%;text-align:left;padding:9px 12px;border:0;border-bottom:1px solid var(--ui-stroke-secondary);background:transparent;color:inherit;font:inherit;cursor:pointer}
.gr-item:hover{background:var(--chrome-action-hover)}.gr-item[aria-current]{background:color-mix(in srgb,var(--ui-accent) 10%,transparent)}
.gr-item-top{display:flex;gap:8px;align-items:baseline;min-width:0}.gr-item-top b{font-weight:500;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gr-item-sub{display:block;margin-top:3px;font-size:11px;color:var(--ui-text-tertiary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gr-qid{flex:none;font:600 11px var(--font-mono,ui-monospace,monospace);color:var(--ui-accent)}
.gr-detail{flex:1;min-width:0;overflow:auto;padding:16px 20px}
.gr-detail-head{display:flex;gap:8px;align-items:baseline}.gr-detail-head h2{margin:0;font-size:16px;font-weight:600;overflow-wrap:anywhere}
.gr-question{margin:4px 0 12px;color:var(--ui-text-secondary)}
.gr-kpis{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0}.gr-kpi{display:flex;flex-direction:column;padding:10px 14px;border:1px solid var(--ui-stroke-secondary);border-radius:8px;min-width:130px}
.gr-kpi b{font-size:22px;font-weight:600;font-variant-numeric:tabular-nums}.gr-kpi span{font-size:12px;color:var(--ui-text-tertiary)}
.gr-bars{display:grid;grid-template-columns:minmax(60px,max-content) minmax(80px,1fr) max-content;gap:4px 10px;align-items:center;margin:10px 0;max-width:640px}
.gr-bar-row{display:contents}.gr-bar-label{text-align:right;color:var(--ui-text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:160px}
.gr-bar-track{height:12px}.gr-bar{display:block;height:100%;min-width:2px;border-radius:2px;background:var(--ui-accent)}
.gr-bar-value{font-variant-numeric:tabular-nums;color:var(--ui-text-secondary);font-size:12px}
.gr-svg svg{width:100%;max-width:640px;margin:10px 0;display:block}.gr-svg .bar,.gr-svg .cell{fill:var(--ui-accent)}
.gr-svg .pt{fill:var(--ui-accent);stroke:var(--background);stroke-width:2}.gr-svg .grid{stroke:var(--ui-stroke-secondary);stroke-width:1}
.gr-svg .lbl{fill:var(--ui-text-tertiary);font-size:11px}
.gr-line{width:100%;max-width:640px;margin:10px 0;display:block}.gr-path-line{fill:none;stroke:var(--ui-accent);stroke-width:2}
.gr-dot{fill:var(--ui-accent)}.gr-grid{stroke:var(--ui-stroke-secondary)}.gr-tick{fill:var(--ui-text-tertiary);font-size:11px}
.gr-table-wrap{overflow-x:auto;margin-top:8px}.gr-table{border-collapse:collapse;font-size:12px}
.gr-table th,.gr-table td{padding:5px 10px;border-bottom:1px solid var(--ui-stroke-secondary);text-align:left;white-space:nowrap}
.gr-table th{font-weight:500;color:var(--ui-text-secondary)}.gr-num{text-align:right!important;font-variant-numeric:tabular-nums}
.gr-sql-head{display:flex;align-items:center;gap:8px;margin-top:16px;font-size:12px;color:var(--ui-text-secondary)}.gr-sql-head span{margin-right:auto}
.gr-sql,.gr-explain{margin:6px 0 0;padding:10px 12px;border-radius:6px;background:var(--chrome-action-hover);font:12px/1.5 var(--font-mono,ui-monospace,monospace);white-space:pre-wrap;overflow-wrap:anywhere}
@container (max-width:560px){.gr-split{flex-direction:column}.gr-list{width:auto;max-height:200px;border-right:0;border-bottom:1px solid var(--ui-stroke-secondary)}.gr-toggles{margin-left:0}}
`

export default {
  id: ID,
  name: 'Grimoire',
  defaultEnabled: false,
  register(ctx) {
    pluginCtx = ctx
    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: '/grimoire' }, render: () => jsx(GrimoirePage, {}) },
      { id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: '/grimoire', label: 'Data', codicon: 'database' } },
      { id: 'open', area: PALETTE_AREA, data: { id: 'grimoire.open', label: 'Open Grimoire data', keywords: ['data', 'csv', 'queries', 'grimoire'], run: () => host.navigate('/grimoire') } }
    ])
    ctx.onEvent('gateway.ready', () => queryClient.removeQueries({ queryKey: [ID] }))
    ctx.onDispose(() => {
      queryClient.removeQueries({ queryKey: [ID] })
      pluginCtx = null
    })
  }
}

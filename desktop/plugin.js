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
  return String(v)
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

const Mark = () => jsxs('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', 'aria-hidden': true, children: [
  jsx('ellipse', { cx: 12, cy: 5.5, rx: 7.5, ry: 3 }, 'a'),
  jsx('path', { d: 'M4.5 5.5v6c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3v-6' }, 'b'),
  jsx('path', { d: 'M4.5 11.5v6c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3v-6' }, 'c')
] })

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

function Line({ q, li, vi }) {
  const rows = q.rows.filter((r) => isNum(r[vi]) && r[li] !== null).sort((a, b) => String(a[li]).localeCompare(String(b[li]))).slice(0, 120)
  const vals = rows.map((r) => r[vi])
  const lo = Math.min(0, ...vals), hi = Math.max(...vals) || 1
  const marks = [lo, (lo + hi) / 2, hi]
  const W = 560, H = 190, B = 22, L = 14 + 7 * Math.max(...marks.map((v) => compact(v).length))
  const x = (i) => L + (W - L - 10) * (i / Math.max(1, rows.length - 1))
  const y = (v) => 8 + (H - B - 8) * (1 - (v - lo) / (hi - lo || 1))
  const every = Math.max(1, Math.floor(rows.length / 6))
  return jsxs('svg', { className: 'gr-line', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `${q.columns[vi]} over ${q.columns[li]}`, children: [
    ...marks.map((v, i) => jsxs('g', { children: [
      jsx('line', { x1: L, x2: W - 10, y1: y(v), y2: y(v), className: 'gr-grid' }),
      jsx('text', { x: L - 6, y: y(v) + 4, textAnchor: 'end', className: 'gr-tick', children: compact(v) })
    ] }, 'g' + i)),
    jsx('polyline', { points: vals.map((v, i) => `${x(i)},${y(v)}`).join(' '), className: 'gr-path-line' }, 'p'),
    ...rows.map((r, i) => jsx('circle', { cx: x(i), cy: y(r[vi]), r: 2.5, className: 'gr-dot', children: jsx('title', { children: `${r[li]}: ${fmt(r[vi])}` }) }, 'd' + i)),
    ...rows.map((r, i) => (i % every === 0 ? jsx('text', { x: x(i), y: H - 5, textAnchor: 'middle', className: 'gr-tick', children: String(r[li]).slice(0, 10) }, 't' + i) : null))
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
    jsx('span', { className: 'gr-bar-value', children: fmt(r[vi]) })
  ] }, i)) })
}

function Result({ q }) {
  if (q.rows.length === 1 && q.columns.length <= 4 && q.rows[0].every((v) => isNum(v) || v === null))
    return jsx('div', { className: 'gr-kpis', children: q.columns.map((c, i) => jsxs('div', { className: 'gr-kpi', children: [jsx('b', { children: fmt(q.rows[0][i]) }), jsx('span', { children: c })] }, c)) })
  const numeric = q.columns.map((_, i) => q.rows.length > 0 && q.rows.every((r) => isNum(r[i]) || r[i] === null))
  return jsxs('div', { children: [
    jsx(Bars, { q }),
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
.gr-mark{width:32px;height:32px;flex:none;border-radius:9px;display:flex;align-items:center;justify-content:center;color:var(--ui-accent);background:color-mix(in srgb,var(--ui-accent) 15%,transparent)}.gr-mark svg{width:18px;height:18px}
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

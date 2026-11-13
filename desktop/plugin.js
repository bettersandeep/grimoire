import { ROUTES_AREA, SIDEBAR_NAV_AREA, PALETTE_AREA, host, queryClient, useQuery, useMutation, useValue } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'grimoire'
let pluginCtx

const PATHS = [/^\/summary$/, /^\/queries(\?dataset=[\w-]+)?$/, /^\/queries\/q\d+\/explain$/, /^\/settings$/,
  /^\/merges\/(approve|reject)$/, /^\/datasets\/[\w-]+\/(forget|check|columns)$/, /^\/charts$/]

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

function useData(path, live = true) {
  const profile = useValue(host.state.profile)
  const connectionId = useValue(host.state.connectionId)
  return useQuery({ queryKey: [ID, profile, connectionId, path], queryFn: () => request(path), enabled: !!path,
    refetchInterval: live ? 5000 : false, retry: false })
}

/** Check files that have no health score yet, one at a time, on the page's own engine (no model tokens). */
function useAutoCheck(datasets) {
  const tried = useRef(new Set())
  const [checking, setChecking] = useState(new Set())
  useEffect(() => {
    const next = (datasets || []).find((d) => !d.health && !d.missing && !tried.current.has(d.name))
    if (!next || checking.size) return
    tried.current.add(next.name)
    setChecking(new Set([next.name]))
    request(`/datasets/${next.name}/check`, { method: 'POST', body: {}, timeoutMs: 120000 })
      .catch(() => {})  // the chip stays "Not checked" and its tooltip says how to check from a chat
      .finally(() => { setChecking(new Set()); queryClient.invalidateQueries({ queryKey: [ID] }) })
  }, [datasets, checking])
  return checking
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

// The Grimoire icon: the enchanter Merlin (pen drawing by Howard Pyle, 1903, public domain), 64 px.
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
      jsxs('div', { children: [jsx('h1', { children: 'Data' }), jsx('p', { children: `Grimoire ${s.version || ''} · numbers with receipts` })] })
    ] }),
    jsxs('div', { className: 'gr-toggles', children: [
      jsx(Toggle, { label: 'Learning mode', checked: s.learn, hint: 'After data answers: how the answer was made, and a better question',
        onChange: (v) => act.mutate({ path: '/settings', body: { learn: v } }) }),
      jsxs('div', { className: 'gr-seg', role: 'radiogroup', 'aria-label': 'Lesson style', 'data-disabled': !s.learn || undefined, children: [
        ['plain', 'Plain words', 'Step by step, with the row count at each step'], ['sql', 'SQL', 'One SQL idea from each answer']
      ].map(([v, label, hint]) => jsx('button', { role: 'radio', 'aria-checked': (s.learn_style || 'plain') === v, title: hint, disabled: !s.learn,
        onClick: () => act.mutate({ path: '/settings', body: { learn_style: v } }), children: label }, v)) }),
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

function About({ show, act }) {
  if (!show) return null
  return jsxs('section', { className: 'gr-about', 'aria-label': 'What Grimoire does', children: [
    jsxs('div', { className: 'gr-about-text', children: [
      jsx('b', { children: 'Ask questions about your data files, and check the numbers' }),
      jsx('p', { children: 'Name a CSV, JSON, Parquet or SQLite file in any chat. Grimoire answers with a real SQL query and flags any number in the reply that no query produced. It reads your files where they are and never changes them.' }),
      jsxs('ul', { children: [
        jsxs('li', { children: [jsx('b', { children: 'Files' }), ' are the files you named in chats. Each gets a ', jsx('b', { children: 'Data health' }), ' score: how far you can trust its numbers. Click the score to see why.'] }),
        jsxs('li', { children: [jsx('b', { children: 'Saved queries' }), ' are the answers: chart, table, the SQL, and how each answer was made. Click ', jsx('b', { children: 'New chart' }), ' to make your own.'] }),
        jsxs('li', { children: ['Try in a chat: ', jsx('code', { children: 'What is the total revenue per region in ~/Downloads/sales.csv?' })] })
      ] })
    ] }),
    jsx('button', { className: 'gr-btn gr-small', onClick: () => act.mutate({ path: '/settings', body: { hide_about: true } }), children: 'Got it' })
  ] })
}

// Most serious first: a reader should see negative amounts before 9.7% empty cells.
const RANK = ['duplicate rows', 'negative values', 'dates in the future', 'spelling variants of one value', 'same value in every row']
export function issueRank(i) {
  const k = RANK.indexOf(i.issue)
  if (k >= 0) return k
  if (i.issue === 'empty values') return 100 - Math.min(99, i.percent || 0) / 100
  return RANK.length  // placeholders and numbers stored as text
}

function IssueChips({ issues }) {
  const sorted = [...issues].sort((a, b) => issueRank(a) - issueRank(b))
  const rest = sorted.slice(4)
  return jsxs('div', { className: 'gr-chips', children: [
    ...sorted.slice(0, 4).map((i, n) => jsx('span', { className: 'gr-chip gr-issue', children: issueText(i) }, n)),
    rest.length ? jsx('span', { className: 'gr-chip', title: rest.map(issueText).join('\n'), children: `+${rest.length} more` }, 'more') : null
  ] })
}

function issueText(i) {
  if (i.issue === 'duplicate rows') return `${fmt(i.rows)} duplicate rows`
  if (i.issue === 'empty values') return `${i.column}: ${fmt(i.percent)}% empty`
  if (i.rows) return `${i.column}: ${i.issue} (${fmt(i.rows)} rows)`
  if (i.issue === 'spelling variants of one value') return `${i.column}: ${i.variants.map((v) => `'${v.value}'`).join(' / ')}`
  return `${i.column}: ${i.issue}`
}

const LEVELS = [[90, 'good', 'Only small problems: read them below before you share.'], [70, 'fair', 'Check the problems below before you share numbers from this file.'],
  [-Infinity, 'poor', 'Fix or explain the problems below before you use numbers from this file.']]
export const healthLevel = (score) => LEVELS.find(([min]) => score >= min)

function HealthChip({ d, open, toggle, checking }) {
  if (d.health) {
    const [, level] = healthLevel(d.health.score)
    return jsx('button', { className: 'gr-chip gr-health', 'data-level': level, 'aria-expanded': open, onClick: toggle,
      title: 'What does this mean?', children: `Data health ${d.health.score}` })
  }
  if (d.missing) return null
  return jsx('span', { className: 'gr-chip', title: checking ? 'Grimoire is looking for problems in this file. This uses no model tokens.' : `Could not check this file here. Ask in a chat: check the data quality of ${d.name}`,
    children: checking ? 'Checking…' : 'Not checked' })
}

function HealthInfo({ health }) {
  const advice = health.off.length ? healthLevel(health.score)[2] : ''
  return jsxs('div', { className: 'gr-health-info', children: [
    jsxs('p', { children: [jsx('b', { children: `Data health ${health.score} of 100` }), ' shows how far you can trust the numbers in this file. 100 means Grimoire found no problems. ', advice] }),
    health.off.length ? jsx('ul', { children: health.off.map((o) => {
      const m = /^-(\d+) (.*)$/.exec(o)
      const why = m ? m[2] + (/other problems?$/.test(m[2]) ? ', listed below' : '') : o
      return jsx('li', { children: m ? `${m[1]} point${m[1] === '1' ? '' : 's'} off: ${why}` : o }, o)
    }) }) : null
  ] })
}

function Files({ datasets, act, filter, setFilter, checking }) {
  const [armed, setArmed] = useState(null)
  const [info, setInfo] = useState(null)
  if (!datasets?.length) return jsx('p', { className: 'gr-empty', children: 'No data files yet. Name a CSV, JSON, Parquet or SQLite file in a chat, and it shows here.' })
  return jsx('div', { className: 'gr-files', children: datasets.map((d) => jsxs('article', { className: 'gr-file', 'aria-current': filter === d.name || undefined, children: [
    jsxs('div', { className: 'gr-file-top', children: [
      jsx('button', { className: 'gr-link', onClick: () => setFilter(filter === d.name ? null : d.name), title: 'Show only this file\'s queries', children: d.name }),
      jsx('span', { className: 'gr-chip', children: d.kind }),
      jsx(HealthChip, { d, open: info === d.name, toggle: () => setInfo(info === d.name ? null : d.name), checking: checking.has(d.name) }),
      d.missing ? jsx('span', { className: 'gr-chip gr-warn', children: 'file missing' }) : null,
      jsx('button', { className: 'gr-btn gr-small gr-push', 'data-armed': armed === d.name || undefined,
        onClick: () => { if (armed === d.name) { setArmed(null); act.mutate({ path: `/datasets/${d.name}/forget` }) } else setArmed(d.name) },
        onBlur: () => setArmed(null),
        children: armed === d.name ? 'Click again to delete' : 'Forget' })
    ] }),
    jsx('div', { className: 'gr-path', title: d.path, children: d.path }),
    jsx('div', { className: 'gr-meta', children: [d.rows != null ? `${fmt(d.rows)}\u00a0rows` : null, d.added_at ? `added from a chat ${ago(d.added_at)}` : null,
      `${d.queries || 0}\u00a0${d.queries === 1 ? 'query' : 'queries'}`].filter(Boolean).join(' · ') }),
    d.health && info === d.name ? jsx(HealthInfo, { health: d.health }) : null,
    d.health && !d.issues?.length ? jsx('div', { className: 'gr-meta', children: 'No problems found.' }) : null,
    d.issues?.length ? jsx(IssueChips, { issues: d.issues }) : null,
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

/** A hover tooltip for one chart: bind(text) goes on each mark; tip is drawn over the chart. */
function useTip() {
  const [tip, setTip] = useState(null)
  const bind = (text) => ({
    onMouseMove: (e) => {
      const box = e.currentTarget.closest('.gr-chart').getBoundingClientRect()
      setTip({ x: e.clientX - box.left, y: e.clientY - box.top, text, right: e.clientX - box.left > box.width * 0.6 })
    },
    onMouseLeave: () => setTip(null)
  })
  const el = tip ? jsx('div', { className: 'gr-tip', 'data-right': tip.right || undefined, style: { left: tip.x, top: tip.y }, children: tip.text }) : null
  return [el, bind]
}

const chart = (tip, svg) => jsxs('div', { className: 'gr-chart', children: [svg, tip] })

function axis(lo, hi, L, W, y) {
  return [lo, (lo + hi) / 2, hi].map((v, i) => jsxs('g', { children: [
    jsx('line', { x1: L, x2: W - 10, y1: y(v), y2: y(v), className: 'gr-grid' }),
    jsx('text', { x: L - 6, y: y(v) + 4, textAnchor: 'end', className: 'gr-tick', children: compact(v) })
  ] }, 'g' + i))
}

/** Line or area over time (or any ordered label). */
function Line({ q, li, vi, area }) {
  const [tip, bind] = useTip()
  const rows = q.rows.filter((r) => isNum(r[vi]) && r[li] !== null).sort((a, b) => String(a[li]).localeCompare(String(b[li]))).slice(0, 120)
  const vals = rows.map((r) => r[vi])
  const lo = Math.min(0, ...vals), hi = Math.max(...vals) || 1
  const W = 560, H = 200, B = 22, L = 14 + 7 * Math.max(...[lo, hi].map((v) => compact(v).length))
  const x = (i) => L + (W - L - 10) * (i / Math.max(1, rows.length - 1))
  const y = (v) => 8 + (H - B - 8) * (1 - (v - lo) / (hi - lo || 1))
  const pts = vals.map((v, i) => `${x(i)},${y(v)}`).join(' ')
  const slot = (W - L - 10) / Math.max(1, rows.length - 1)
  return chart(tip, jsxs('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `${q.columns[vi]} over ${q.columns[li]}`, children: [
    ...axis(lo, hi, L, W, y),
    area ? jsx('polygon', { points: `${x(0)},${y(lo)} ${pts} ${x(rows.length - 1)},${y(lo)}`, className: 'gr-area' }, 'a') : null,
    jsx('polyline', { points: pts, className: 'gr-path-line' }, 'p'),
    ...rows.map((r, i) => jsx('circle', { cx: x(i), cy: y(r[vi]), r: rows.length > 40 ? 2 : 4, className: 'gr-dot' }, 'd' + i)),
    ...rows.map((r, i) => jsx('rect', { x: x(i) - slot / 2, y: 0, width: slot, height: H - B, className: 'gr-hit', ...bind(`${fmt(r[li])}: ${fmt(r[vi])}`) }, 'h' + i)),
    ...ticks(rows.length, W - L - 10, 7 * Math.max(...rows.map((r) => String(r[li]).slice(0, 10).length))).map((i) =>
      jsx('text', { x: x(i), y: H - 5, textAnchor: i === 0 ? 'start' : i === rows.length - 1 ? 'end' : 'middle', className: 'gr-tick', children: String(rows[i][li]).slice(0, 10) }, 't' + i))
  ] }))
}

/** Horizontal bars: the default for categories. */
function Bars({ q, li, vi, onPick }) {
  const [tip, bind] = useTip()
  const rows = q.rows.filter((r) => isNum(r[vi])).slice(0, 25)
  const top = Math.max(...rows.map((r) => Math.abs(r[vi]))) || 1
  return chart(tip, jsx('div', { className: 'gr-bars', role: 'img', 'aria-label': `${q.columns[vi]} by ${q.columns[li]}`, children: rows.map((r, i) => jsxs('div', { className: 'gr-bar-row', 'data-pick': onPick ? true : undefined, onClick: onPick ? () => onPick(r[li]) : undefined, ...bind(`${fmt(r[li])}: ${fmt(r[vi])}`), children: [
    jsx('span', { className: 'gr-bar-label', children: fmt(r[li]) }),
    jsx('span', { className: 'gr-bar-track', children: jsx('span', { className: 'gr-bar', 'data-neg': r[vi] < 0 || undefined, style: { width: `${(Math.abs(r[vi]) / top) * 100}%` } }) }),
    jsx('span', { className: 'gr-bar-value', children: Math.abs(r[vi]) >= 10000 ? compact(r[vi]) : fmt(r[vi]) })
  ] }, i)) }))
}

/** Vertical columns. */
function Columns({ q, li, vi, onPick }) {
  const [tip, bind] = useTip()
  const rows = q.rows.filter((r) => isNum(r[vi])).slice(0, 60)
  const vals = rows.map((r) => r[vi]), lo = Math.min(0, ...vals), hi = Math.max(0, ...vals) || 1
  const W = 560, H = 210, B = 22, L = 14 + 7 * Math.max(...[lo, hi].map((v) => compact(v).length))
  const bw = (W - L - 10) / rows.length, y = (v) => 8 + (H - B - 8) * (1 - (v - lo) / (hi - lo || 1))
  const labels = rows.map((r) => String(fmt(r[li])).slice(0, 10))
  const shown = ticks(rows.length, W - L - 10 - bw, 7 * Math.max(...labels.map((t) => t.length)))
  return chart(tip, jsxs('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `${q.columns[vi]} by ${q.columns[li]}`, children: [
    ...axis(lo, hi, L, W, y),
    ...rows.map((r, i) => jsx('rect', { x: L + bw * i + 1, y: Math.min(y(r[vi]), y(0)), width: Math.max(1, bw - 2), height: Math.abs(y(0) - y(r[vi])), rx: 3,
      className: r[vi] < 0 ? 'gr-col gr-neg' : 'gr-col', 'data-pick': onPick ? true : undefined, onClick: onPick ? () => onPick(r[li]) : undefined,
      ...bind(`${fmt(r[li])}: ${fmt(r[vi])}`) }, 'c' + i)),
    ...shown.map((i) => jsx('text', { x: L + bw * i + bw / 2, y: H - 5, textAnchor: 'middle', className: 'gr-tick', children: labels[i] }, 't' + i))
  ] }))
}

/** Parts of a whole: a donut with a legend, for up to 6 positive values. */
function Donut({ q, li, vi, onPick }) {
  const [tip, bind] = useTip()
  const rows = q.rows.filter((r) => isNum(r[vi]) && r[vi] > 0)
  const total = rows.reduce((a, r) => a + r[vi], 0) || 1
  const R = 80, r0 = 50, C = 100
  let angle = -Math.PI / 2
  const arcs = rows.map((r, i) => {
    const a0 = angle, a1 = angle + (2 * Math.PI * r[vi]) / total
    angle = a1
    const big = a1 - a0 > Math.PI ? 1 : 0, p = (a, rad) => `${C + rad * Math.cos(a)},${C + rad * Math.sin(a)}`
    const d = rows.length === 1 ? `M${C - R},${C}a${R},${R} 0 1,0 ${2 * R},0a${R},${R} 0 1,0 ${-2 * R},0M${C - r0},${C}a${r0},${r0} 0 1,1 ${2 * r0},0a${r0},${r0} 0 1,1 ${-2 * r0},0`
      : `M${p(a0, R)}A${R},${R} 0 ${big},1 ${p(a1, R)}L${p(a1, r0)}A${r0},${r0} 0 ${big},0 ${p(a0, r0)}Z`
    return jsx('path', { d, className: `gr-slice gr-s${i + 1}`, 'data-pick': onPick ? true : undefined, onClick: onPick ? () => onPick(r[li]) : undefined, ...bind(`${fmt(r[li])}: ${fmt(r[vi])} (${((100 * r[vi]) / total).toFixed(1)}%)`) }, i)
  })
  return chart(tip, jsxs('div', { className: 'gr-donut', children: [
    jsxs('svg', { viewBox: '0 0 200 200', role: 'img', 'aria-label': `Share of ${q.columns[vi]} by ${q.columns[li]}`, children: [
      ...arcs,
      jsx('text', { x: C, y: C - 2, textAnchor: 'middle', className: 'gr-donut-total', children: compact(total) }, 'n'),
      jsx('text', { x: C, y: C + 16, textAnchor: 'middle', className: 'gr-tick', children: 'total' }, 'l')
    ] }),
    jsx('ul', { className: 'gr-legend', children: rows.map((r, i) => jsxs('li', { children: [
      jsx('span', { className: `gr-swatch gr-s${i + 1}` }), jsx('span', { children: fmt(r[li]) }),
      jsx('b', { children: `${((100 * r[vi]) / total).toFixed(1)}%` })
    ] }, i)) })
  ] }))
}

// Heatmap, histogram and scatter: the plugin's Python picks the chart and orders the data; drawn here.
function Heatmap({ c }) {
  const [tip, bind] = useTip()
  const vals = c.cells.map((t) => t[2]), lo = Math.min(...vals), hi = Math.max(...vals)
  const W = 560, CH = 20, TOP = 20, L = 12 + 7 * Math.max(...c.ys.map((v) => v.slice(0, 14).length))
  const cw = (W - L - 4) / c.xs.length, H = TOP + CH * c.ys.length
  const cut = (v) => (v.length > 12 ? v.slice(0, 11) + '…' : v)
  const every = Math.max(1, Math.ceil((7 * Math.max(...c.xs.map((v) => cut(v).length))) / Math.max(1, cw - 4)))
  const step = (v) => Math.min(6, Math.floor((7 * (v - lo)) / (hi - lo || 1)))
  return chart(tip, jsxs('svg', { viewBox: `0 0 ${W} ${H + 24}`, role: 'img', 'aria-label': `${c.value} by ${c.x} and ${c.y}`, children: [
    ...c.xs.map((v, i) => (i % every === 0 ? jsx('text', { x: L + cw * i + cw / 2, y: 13, textAnchor: 'middle', className: 'gr-tick', children: cut(v) }, 'x' + i) : null)),
    ...c.ys.map((v, j) => jsx('text', { x: L - 6, y: TOP + CH * j + 14, textAnchor: 'end', className: 'gr-tick', children: v.slice(0, 14) }, 'y' + j)),
    ...c.cells.map(([i, j, v], n) => jsx('rect', { x: L + cw * i + 1, y: TOP + CH * j + 1, width: Math.max(1, cw - 2), height: CH - 2, rx: 2,
      className: `gr-heat gr-h${step(v)}`, ...bind(`${c.xs[i]}, ${c.ys[j]}: ${fmt(v)}`) }, 'c' + n)),
    ...[0, 1, 2, 3, 4, 5, 6].map((k) => jsx('rect', { x: L + 14 * k, y: H + 8, width: 12, height: 10, rx: 2, className: `gr-heat gr-h${k}` }, 'k' + k)),
    jsx('text', { x: L + 14 * 7 + 6, y: H + 17, className: 'gr-tick', children: `${c.value}: ${fmt(lo)} to ${fmt(hi)}` }, 'legend')
  ] }))
}

function Histogram({ c }) {
  const [tip, bind] = useTip()
  const top = Math.max(...c.counts) || 1
  const W = 560, H = 190, B = 22, L = 14 + 7 * compact(top).length
  const bw = (W - L - 10) / c.counts.length, y = (v) => 8 + (H - B - 8) * (1 - v / top)
  const shown = ticks(c.starts.length, W - L - 10, 7 * Math.max(...c.starts.map((v) => compact(v).length))).filter((i) => i < c.starts.length - 1)
  return chart(tip, jsxs('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `${c.y} per bucket of ${c.x}`, children: [
    ...axis(0, top, L, W, y),
    ...c.counts.map((n, i) => jsx('rect', { x: L + bw * i + 1, y: y(n), width: Math.max(1, bw - 2), height: Math.max(0, y(0) - y(n)), rx: 2, className: 'gr-col',
      ...bind(`${fmt(c.starts[i])} to ${fmt(c.starts[i] + c.step)}: ${fmt(n)}`) }, 'b' + i)),
    ...shown.map((i) => jsx('text', { x: L + bw * i, y: H - 5, textAnchor: i === 0 ? 'start' : 'middle', className: 'gr-tick', children: compact(c.starts[i]) }, 't' + i))
  ] }))
}

function Scatter({ c }) {
  const [tip, bind] = useTip()
  const xs = c.points.map((p) => p[0]), ys = c.points.map((p) => p[1])
  const xlo = Math.min(...xs), xhi = Math.max(...xs), ylo = Math.min(0, ...ys), yhi = Math.max(...ys)
  const W = 560, H = 230, B = 40, TOP = 22, L = 14 + 7 * Math.max(...[ylo, yhi].map((v) => compact(v).length))
  const x = (v) => L + 6 + (W - L - 20) * ((v - xlo) / (xhi - xlo || 1)), y = (v) => TOP + (H - B - TOP) * (1 - (v - ylo) / (yhi - ylo || 1))
  return chart(tip, jsxs('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `${c.y} against ${c.x}`, children: [
    ...axis(ylo, yhi, L, W, y),
    ...[xlo, (xlo + xhi) / 2, xhi].map((v, i) => jsx('text', { x: x(v), y: H - 22, textAnchor: 'middle', className: 'gr-tick', children: compact(v) }, 'x' + i)),
    jsx('text', { x: L, y: 12, className: 'gr-tick', children: `${c.y} ↑` }, 'yn'),
    jsx('text', { x: (L + W) / 2, y: H - 4, textAnchor: 'middle', className: 'gr-tick', children: `${c.x} →` }, 'xn'),
    ...c.points.map(([a, b], i) => jsx('circle', { cx: x(a), cy: y(b), r: 4, className: 'gr-pt', ...bind(`${c.x} ${fmt(a)}, ${c.y} ${fmt(b)}`) }, 'p' + i))
  ] }))
}

const CHARTS = { heatmap: Heatmap, histogram: Histogram, scatter: Scatter }
const KINDS = { bars: ['Bars', Bars], columns: ['Columns', Columns], line: ['Line', Line], area: ['Area', (p) => jsx(Line, { ...p, area: true })], donut: ['Donut', Donut] }

/** Chart types that fit a label-and-number result, best first. */
export function chartKinds(q, li, vi) {
  const labels = q.rows.map((r) => r[li])
  if (isTime(labels)) return ['line', 'area', 'columns']
  const vals = q.rows.map((r) => r[vi]).filter(isNum)
  const donut = q.rows.length <= 6 && vals.length === q.rows.length && vals.every((v) => v > 0)
  return ['bars', 'columns', ...(donut ? ['donut'] : []), 'line']
}

const measures = (q, li) => q.columns.map((_, i) => i).filter((i) => i !== li && q.rows.every((r) => isNum(r[i]) || r[i] === null) && q.rows.some((r) => isNum(r[i])))

function Picker({ label, options, value, onChange }) {
  return jsxs('div', { className: 'gr-picker', role: 'radiogroup', 'aria-label': label, children: [
    jsx('span', { className: 'gr-picker-label', children: label }),
    ...options.map(([v, text]) => jsx('button', { role: 'radio', 'aria-checked': v === value, className: 'gr-chip gr-opt', onClick: () => onChange(v), children: text }, v))
  ] })
}

/** The latest value of a time series and its change from the period before, or null. */
export function trend(q, li, vi) {
  const rows = q.rows.filter((r) => isNum(r[vi]) && r[li] !== null).sort((a, b) => String(a[li]).localeCompare(String(b[li])))
  if (rows.length < 2 || !isTime(rows.map((r) => r[li]))) return null
  const [prev, last] = rows.slice(-2)
  const pct = prev[vi] ? ((last[vi] - prev[vi]) / Math.abs(prev[vi])) * 100 : null
  return { label: fmt(last[li]), value: last[vi], prev: fmt(prev[li]), pct }
}

function Trend({ t, name }) {
  const up = t.pct >= 0
  return jsxs('div', { className: 'gr-trend', children: [
    jsx('span', { className: 'gr-muted', children: `${name}, latest (${t.label})` }),
    jsx('b', { children: fmt(t.value) }),
    t.pct === null ? null : jsx('span', { className: 'gr-delta',
      children: `${up ? '▲' : '▼'} ${Math.abs(t.pct).toFixed(1)}% from ${t.prev}` })
  ] })
}

function ChartView({ q, onDrill }) {
  const pick = chartColumns(q.columns, q.rows)
  const [kind, setKind] = useState(null)
  const [measure, setMeasure] = useState(null)
  const source = q.datasets.length === 1 ? q.datasets[0] : null
  const meta = useData(source && onDrill ? `/datasets/${source}/columns` : null, false)
  if (CHARTS[q.chart?.kind]) return jsx(CHARTS[q.chart.kind], { c: q.chart })
  if (!pick) return null
  const li = pick[0], all = measures(q, li), vi = all.includes(measure) ? measure : pick[1]
  const kinds = chartKinds(q, li, vi), k = kinds.includes(kind) ? kind : kinds[0]
  const t = trend(q, li, vi)
  // Look inside one bar: only when the label is a real column of the file (an alias or a computed label is not).
  const known = (meta.data?.tables || []).some((tb) => tb.columns.some((c) => c.name === q.columns[li] && c.kind !== 'time'))
  const onPick = known && !t ? (value) => onDrill({ dataset: source, fcol: q.columns[li], value: String(value) }) : null
  return jsxs('div', { children: [
    t ? jsx(Trend, { t, name: q.columns[vi] }) : null,
    jsxs('div', { className: 'gr-pickers', children: [
      jsx(Picker, { label: 'Chart', options: kinds.map((v) => [v, KINDS[v][0]]), value: k, onChange: setKind }),
      all.length > 1 ? jsx(Picker, { label: 'Show', options: all.map((i) => [i, q.columns[i]]), value: vi, onChange: setMeasure }) : null
    ] }),
    jsx(KINDS[k][1], { q, li, vi, onPick }),
    onPick && k !== 'line' ? jsx('p', { className: 'gr-muted', children: `Click a ${k === 'donut' ? 'slice' : k === 'columns' ? 'column' : 'bar'} to look inside it: a new chart with only those rows.` }) : null
  ] })
}

/** [row label, column label, number] indexes for a pivot table, or null: two labels and one number, few columns. */
export function pivotColumns(q) {
  if (q.columns.length !== 3 || q.rows.length < 2) return null
  const nums = [0, 1, 2].filter((i) => q.rows.every((r) => isNum(r[i]) || r[i] === null))
  if (nums.length !== 1) return null
  const [a, b] = [0, 1, 2].filter((i) => i !== nums[0])
  const across = new Set(q.rows.map((r) => r[b]))
  return across.size >= 2 && across.size <= 24 ? [a, b, nums[0]] : null
}

function Pivot({ q }) {
  const [a, b, v] = pivotColumns(q)
  const rowKeys = [...new Set(q.rows.map((r) => r[a]))], colKeys = [...new Set(q.rows.map((r) => r[b]))]
  const cell = new Map(q.rows.map((r) => [`${r[a]}\u0000${r[b]}`, r[v]]))
  const top = Math.max(...q.rows.map((r) => Math.abs(r[v] || 0))) || 1
  const dec = decimals(q.rows, v)
  return jsxs('div', { children: [
    jsx('div', { className: 'gr-table-wrap', children: jsxs('table', { className: 'gr-table gr-pivot', children: [
      jsx('thead', { children: jsxs('tr', { children: [jsx('th', { children: `${q.columns[a]} \\ ${q.columns[b]}` }),
        ...colKeys.map((c) => jsx('th', { className: 'gr-num', children: fmt(c) }, String(c)))] }) }),
      jsx('tbody', { children: rowKeys.map((rk) => jsxs('tr', { children: [jsx('th', { children: fmt(rk) }), ...colKeys.map((ck) => {
        const x = cell.get(`${rk}\u0000${ck}`)
        return jsx('td', { className: 'gr-num', 'data-neg': x < 0 || undefined,
          style: isNum(x) ? { '--heat': `${Math.round(6 + (44 * Math.abs(x)) / top)}%` } : undefined,
          children: isNum(x) ? x.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec }) : '' }, String(ck))
      })] }, String(rk))) })
    ] }) }),
    jsx('p', { className: 'gr-muted', children: `${q.columns[v]} for each ${q.columns[a]} and ${q.columns[b]}; a stronger color is a larger number.` })
  ] })
}

export const hasChart = (q) => !!(CHARTS[q.chart?.kind] || chartColumns(q.columns, q.rows))

/** Decimals for each number column: as many as its values need, at most 2, the same on every row. */
export function decimals(rows, i) {
  let d = 0
  for (const r of rows) if (isNum(r[i]) && !Number.isInteger(r[i])) d = Math.max(d, Math.min(2, (String(r[i]).split('.')[1] || '').length))
  return d
}

function Table({ q }) {
  const numeric = q.columns.map((_, i) => q.rows.length > 0 && q.rows.every((r) => isNum(r[i]) || r[i] === null))
  const dec = q.columns.map((_, i) => (numeric[i] ? decimals(q.rows, i) : 0))
  const top = q.columns.map((_, i) => (numeric[i] && q.rows.length > 1 ? Math.max(...q.rows.map((r) => Math.abs(r[i] || 0))) : 0))
  const cell = (v, i) => {
    if (!numeric[i] || !isNum(v)) return jsx('td', { children: fmt(v) }, i)
    const text = v.toLocaleString('en-US', { minimumFractionDigits: dec[i], maximumFractionDigits: dec[i] })
    return jsx('td', { className: 'gr-num', 'data-neg': v < 0 || undefined,
      style: top[i] ? { '--w': `${(Math.abs(v) / top[i]) * 100}%` } : undefined, children: text }, i)
  }
  return jsxs('div', { children: [
    jsx('div', { className: 'gr-table-wrap', children: jsxs('table', { className: 'gr-table', children: [
      jsx('thead', { children: jsx('tr', { children: q.columns.map((c, i) => jsx('th', { className: numeric[i] ? 'gr-num' : '', children: c }, i)) }) }),
      jsx('tbody', { children: q.rows.map((r, n) => jsx('tr', { children: r.map(cell) }, n)) })
    ] }) }),
    q.total_rows > q.rows.length || q.truncated ? jsx('p', { className: 'gr-muted', children: `Showing ${q.rows.length} of ${q.truncated ? 'more than ' : ''}${fmt(q.total_rows)} rows.` }) : null
  ] })
}

const isKpi = (q) => q.rows.length === 1 && q.columns.length <= 4 && q.rows[0].every((v) => isNum(v) || v === null)

function Kpis({ q }) {
  return jsx('div', { className: 'gr-kpis', children: q.columns.map((c, i) => jsxs('div', { className: 'gr-kpi', children: [jsx('b', { children: fmt(q.rows[0][i]) }), jsx('span', { children: c })] }, c)) })
}

function Explain({ id }) {
  const data = useData(`/queries/${id}/explain`)
  if (data.isLoading) return jsx('p', { className: 'gr-muted', children: 'Loading…' })
  if (data.error) return jsx('p', { className: 'gr-error', children: errorText(data.error) })
  return jsx('pre', { className: 'gr-explain', children: data.data.text })
}

function Detail({ q, onDrill }) {
  const tabs = [...(isKpi(q) ? [['result', 'Result']] : hasChart(q) ? [['chart', 'Chart']] : []), ...(pivotColumns(q) ? [['pivot', 'Pivot']] : []),
    ...(isKpi(q) ? [] : [['table', 'Table']]), ['sql', 'SQL'], ['explain', 'How it was made']]
  const [tab, setTab] = useState(tabs[0][0])
  const copy = () => navigator.clipboard.writeText(q.sql).then(
    () => host.notify({ kind: 'success', message: `Copied the SQL of ${q.id}` }),
    () => host.notify({ kind: 'error', message: 'Could not copy. Select the SQL and copy it.' }))
  return jsxs('div', { className: 'gr-detail', children: [
    jsxs('div', { className: 'gr-detail-head', children: [
      jsx('span', { className: 'gr-qid', children: q.id }),
      jsx('h2', { children: q.purpose || 'Query' }),
      jsx('button', { className: 'gr-btn gr-small gr-push', onClick: copy, title: 'Copy the SQL behind these numbers', children: 'Copy SQL' })
    ] }),
    q.question ? jsx('p', { className: 'gr-question', children: `“${q.question}”` }) : null,
    jsx('div', { className: 'gr-tabs', role: 'tablist', 'aria-label': 'Query views', children: tabs.map(([id, label]) =>
      jsx('button', { role: 'tab', 'aria-selected': tab === id, className: 'gr-tab', onClick: () => setTab(id), children: label }, id)) }),
    jsxs('div', { role: 'tabpanel', className: 'gr-panel', children: [
      tab === 'result' ? jsx(Kpis, { q }) : null,
      tab === 'chart' ? jsx(ChartView, { q, onDrill }) : null,
      tab === 'pivot' ? jsx(Pivot, { q }) : null,
      tab === 'table' ? jsx(Table, { q }) : null,
      tab === 'sql' ? jsx('pre', { className: 'gr-sql', children: q.sql }) : null,
      tab === 'explain' ? jsx(Explain, { id: q.id }) : null
    ] }),
    jsx('p', { className: 'gr-muted', children: `${ago(q.created_at)} · ${q.datasets.join(', ') || 'unknown file'} · type /grimoire rerun ${q.id} in chat to check it still holds` })
  ] })
}

function Queries({ filter, selected, setSelected, onDrill }) {
  const data = useData(filter ? `/queries?dataset=${filter}` : '/queries')
  if (data.isLoading) return jsx('p', { className: 'gr-muted gr-pad', children: 'Loading…' })
  if (data.error) return jsx('p', { className: 'gr-error gr-pad', children: errorText(data.error) })
  const list = data.data.queries || []
  if (!list.length) return jsx('p', { className: 'gr-empty', children: 'No saved queries yet. Every answer about your data saves one here, with its SQL. Or click New chart.' })
  const current = list.find((q) => q.id === selected) || list[0]
  return jsxs('div', { className: 'gr-split', children: [
    jsx('nav', { className: 'gr-list', 'aria-label': 'Saved queries', children: list.map((q) => jsxs('button', { className: 'gr-item', 'aria-current': q.id === current.id || undefined, onClick: () => setSelected(q.id), children: [
      jsxs('span', { className: 'gr-item-top', children: [jsx('span', { className: 'gr-qid', children: q.id }), jsx('b', { children: q.purpose || q.question || q.sql })] }),
      jsx('span', { className: 'gr-item-sub', children: `${ago(q.created_at)} · ${q.datasets.join(', ')}` })
    ] }, q.id)) }),
    jsx(Detail, { q: current, onDrill }, current.id)
  ] })
}

export const isId = (name) => /(^|_)id$/i.test(name)
const MEASURE_OPTS = [['count', 'Count rows'], ['sum', 'Total of'], ['avg', 'Average of'], ['min', 'Smallest'], ['max', 'Largest']]

function Field({ label, children }) {
  return jsxs('label', { className: 'gr-field', children: [jsx('span', { children: label }), children] })
}

function Select({ value, onChange, options }) {
  return jsx('select', { className: 'gr-select', value, onChange: (e) => onChange(e.target.value),
    children: options.map(([v, label]) => jsx('option', { value: v, children: label }, v)) })
}

function NewChart({ datasets, preset, onDone, onClose }) {
  const files = datasets.filter((d) => !d.missing)
  const [form, setForm] = useState({ dataset: files[0]?.name || '', table: '', group: '', group2: '', bucket: 'month', measure: 'count', column: '', fcol: '', op: '=', value: '', ...preset })
  const box = useRef(null)
  useEffect(() => { box.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, [])
  const set = (patch) => setForm((f) => ({ ...f, ...patch }))
  const meta = useData(form.dataset ? `/datasets/${form.dataset}/columns` : null, false)
  const make = useMutation({
    mutationFn: (body) => request('/charts', { method: 'POST', body, timeoutMs: 60000 }),
    onSuccess: (r) => { queryClient.invalidateQueries({ queryKey: [ID] }); onDone(r.id) }
  })
  const tables = meta.data?.tables || []
  const table = tables.find((t) => t.table === form.table) || tables[0]
  const cols = table?.columns || []
  const nums = cols.filter((c) => c.kind === 'number').sort((a, b) => isId(a.name) - isId(b.name))  // ids last: nobody totals them
  const groupKind = cols.find((c) => c.name === form.group)?.kind
  const across = cols.filter((c) => c.kind === 'text' && c.name !== form.group)
  const group2 = form.group && across.some((c) => c.name === form.group2) ? form.group2 : ''
  const column = nums.some((c) => c.name === form.column) ? form.column : nums[0]?.name || ''
  const submit = (e) => {
    e.preventDefault()
    make.mutate({ dataset: form.dataset, table: table?.table, group: form.group || null, group2: group2 || null, bucket: groupKind === 'time' ? form.bucket : null,
      measure: form.measure, column: form.measure === 'count' ? null : column,
      filter: form.fcol ? { column: form.fcol, op: form.op, value: form.value } : null })
  }
  const colOpts = cols.map((c) => [c.name, c.name])
  return jsxs('form', { className: 'gr-builder', ref: box, onSubmit: submit, 'aria-label': 'New chart', children: [
    preset?.fcol ? jsx('p', { className: 'gr-builder-note', children: `Only rows where ${preset.fcol} = ${preset.value}. Pick what to group them by.` }) : null,
    jsxs('div', { className: 'gr-fields', children: [
      jsx(Field, { label: 'File', children: jsx(Select, { value: form.dataset, onChange: (v) => set({ dataset: v, table: '', group: '', column: '', fcol: '' }), options: files.map((d) => [d.name, d.name]) }) }),
      tables.length > 1 ? jsx(Field, { label: 'Table', children: jsx(Select, { value: table.table, onChange: (v) => set({ table: v, group: '', column: '', fcol: '' }), options: tables.map((t) => [t.table, t.table]) }) }) : null,
      jsx(Field, { label: 'Measure', children: jsx(Select, { value: form.measure, onChange: (v) => set({ measure: v }), options: nums.length ? MEASURE_OPTS : MEASURE_OPTS.slice(0, 1) }) }),
      form.measure !== 'count' ? jsx(Field, { label: 'Of', children: jsx(Select, { value: column, onChange: (v) => set({ column: v }), options: nums.map((c) => [c.name, c.name]) }) }) : null,
      jsx(Field, { label: 'Group by', children: jsx(Select, { value: form.group, onChange: (v) => set({ group: v }), options: [['', 'Nothing (one number)'], ...colOpts] }) }),
      groupKind === 'time' ? jsx(Field, { label: 'Per', children: jsx(Select, { value: form.bucket, onChange: (v) => set({ bucket: v }), options: [['day', 'Day'], ['month', 'Month'], ['year', 'Year']] }) }) : null,
      form.group && across.length ? jsx(Field, { label: 'And by (pivot)', children: jsx(Select, { value: group2, onChange: (v) => set({ group2: v }), options: [['', 'Nothing'], ...across.map((c) => [c.name, c.name])] }) }) : null,
      jsx(Field, { label: 'Only rows where', children: jsx(Select, { value: form.fcol, onChange: (v) => set({ fcol: v }), options: [['', 'All rows'], ...colOpts] }) }),
      form.fcol ? jsx(Field, { label: 'Is', children: jsx(Select, { value: form.op, onChange: (v) => set({ op: v }), options: [['=', '='], ['!=', '≠'], ['>', '>'], ['<', '<'], ['>=', '≥'], ['<=', '≤']] }) }) : null,
      form.fcol ? jsx(Field, { label: 'Value', children: jsx('input', { className: 'gr-select', value: form.value, onChange: (e) => set({ value: e.target.value }), required: true }) }) : null
    ] }),
    meta.error ? jsx('p', { className: 'gr-error', children: errorText(meta.error) }) : null,
    make.error ? jsx('p', { className: 'gr-error', children: errorText(make.error) }) : null,
    jsxs('div', { className: 'gr-actions', children: [
      jsx('button', { className: 'gr-cta', type: 'submit', disabled: !table || make.isPending, children: make.isPending ? 'Making…' : 'Make chart' }),
      jsx('button', { className: 'gr-btn', type: 'button', onClick: onClose, children: 'Cancel' }),
      jsx('span', { className: 'gr-muted', children: 'Grimoire writes the SQL and saves it as a query. No model tokens.' })
    ] })
  ] })
}

function GrimoirePage() {
  const summary = useData('/summary')
  const act = useAction()
  const [filter, setFilter] = useState(null)
  const [selected, setSelected] = useState(null)
  const [building, setBuilding] = useState(false)
  const checking = useAutoCheck(summary.data?.datasets)
  const files = (summary.data?.datasets || []).filter((d) => !d.missing)
  return jsxs('div', { className: 'gr-page', children: [
    jsx('style', { children: CSS }),
    jsx(Header, { summary: summary.data, act }),
    summary.error ? jsx('p', { className: 'gr-error gr-pad', children: `Grimoire is not reachable: ${errorText(summary.error)}. Check that the plugin is enabled.` }) : null,
    jsxs('main', { className: 'gr-body', children: [
      jsx(About, { show: summary.data?.about, act }),
      jsx(Pending, { pending: summary.data?.pending, act }),
      jsxs('section', { children: [jsx('h3', { className: 'gr-h', children: 'Files' }), jsx(Files, { datasets: summary.data?.datasets, act, filter, setFilter, checking })] }),
      summary.data?.metrics?.length ? jsxs('section', { children: [
        jsx('h3', { className: 'gr-h', children: 'Saved metrics' }),
        jsx('div', { className: 'gr-chips', children: summary.data.metrics.map((m) => jsxs('span', { className: 'gr-chip gr-metric', title: 'Remove with /grimoire undefine ' + m.name, children: [jsx('b', { children: `${m.name}()` }), ` = ${m.expression}`] }, m.name)) })
      ] }) : null,
      jsxs('section', { className: 'gr-grow', children: [
        jsxs('h3', { className: 'gr-h', children: ['Saved queries', filter ? jsx('button', { className: 'gr-chip gr-filter', onClick: () => setFilter(null), children: `${filter} ×` }) : null,
          files.length && !building ? jsx('button', { className: 'gr-btn gr-small gr-push', onClick: () => setBuilding({}), children: '+ New chart' }) : null] }),
        building ? jsx(NewChart, { datasets: files, preset: building.preset, onClose: () => setBuilding(false), onDone: (id) => { setBuilding(false); setFilter(null); setSelected(id) } }, JSON.stringify(building)) : null,
        jsx(Queries, { filter, selected, setSelected, onDrill: (preset) => setBuilding({ preset }) }, filter || 'all')
      ] })
    ] })
  ] })
}

const CSS = `
.gr-page{--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--neg:#e34948;
--h0:#cde2fb;--h1:#9ec5f4;--h2:#6da7ec;--h3:#3987e5;--h4:#256abf;--h5:#184f95;--h6:#0d366b}
:root[data-hermes-mode=dark] .gr-page{--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--neg:#e66767;
--h0:#0d366b;--h1:#104281;--h2:#184f95;--h3:#256abf;--h4:#3987e5;--h5:#6da7ec;--h6:#b7d3f6}
.gr-page{height:100%;min-height:0;display:flex;flex-direction:column;color:var(--foreground);font-size:13px;overflow:hidden;container-type:inline-size}
.gr-page *{box-sizing:border-box}.gr-page :focus-visible{outline:2px solid var(--ui-accent);outline-offset:-2px}
.gr-muted{color:var(--ui-text-tertiary);font-size:12px;margin:8px 0 0}.gr-error{color:var(--ui-red,var(--ui-error,var(--foreground)))}.gr-pad{padding:0 20px}
.gr-empty{color:var(--ui-text-tertiary);margin:6px 0 0}
.gr-top{display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding:16px 20px 12px;border-bottom:1px solid var(--ui-stroke-secondary)}
.gr-brand{display:flex;align-items:center;gap:10px;min-width:0}.gr-brand h1{margin:0;font-size:16px;font-weight:600}.gr-brand p{margin:1px 0 0;font-size:12px;color:var(--ui-text-tertiary)}
.gr-mark{width:32px;height:32px;flex:none;border-radius:8px;overflow:hidden}
.gr-toggles{margin-left:auto;display:flex;gap:16px;flex-wrap:wrap}
.gr-seg{display:inline-flex;border:1px solid var(--ui-stroke-secondary);border-radius:7px;overflow:hidden}.gr-seg[data-disabled]{opacity:.5}
.gr-seg button{border:0;background:transparent;color:var(--ui-text-secondary);font:inherit;font-size:12px;padding:4px 10px;cursor:pointer}
.gr-seg button+button{border-left:1px solid var(--ui-stroke-secondary)}.gr-seg button[aria-checked=true]{background:color-mix(in srgb,var(--ui-accent) 18%,transparent);color:var(--foreground)}
.gr-seg button:disabled{cursor:default}.gr-seg button:focus-visible{outline:2px solid var(--ui-accent);outline-offset:-2px}
.gr-toggle{display:inline-flex;align-items:center;gap:8px;cursor:pointer;color:var(--ui-text-secondary)}.gr-toggle[data-disabled]{opacity:.5;cursor:default}
.gr-toggle input{position:absolute;opacity:0;width:1px;height:1px}
.gr-switch{width:28px;height:16px;border-radius:8px;background:var(--ui-stroke-secondary);position:relative;transition:background .15s;flex:none}
.gr-switch::after{content:'';position:absolute;top:2px;left:2px;width:12px;height:12px;border-radius:50%;background:var(--background);transition:transform .15s}
.gr-toggle input:checked+.gr-switch{background:var(--ui-accent)}.gr-toggle input:checked+.gr-switch::after{transform:translateX(12px)}
.gr-toggle input:focus-visible+.gr-switch{outline:2px solid var(--ui-accent);outline-offset:2px}
.gr-body{flex:1;min-height:0;overflow:auto;padding:16px 20px 24px;display:flex;flex-direction:column;gap:18px}
.gr-h{margin:0 0 8px;font-size:12px;font-weight:500;color:var(--ui-text-secondary);display:flex;align-items:center;gap:8px}
.gr-pending{display:flex;gap:16px;align-items:center;flex-wrap:wrap;padding:12px 14px;border-radius:8px;border:1px solid color-mix(in srgb,var(--ui-accent) 40%,transparent);background:color-mix(in srgb,var(--ui-accent) 8%,transparent)}
.gr-about{display:flex;gap:16px;align-items:flex-start;padding:12px 14px;border-radius:8px;border:1px solid color-mix(in srgb,var(--s1) 35%,transparent);background:color-mix(in srgb,var(--s1) 6%,transparent)}
.gr-about p{margin:4px 0 0;color:var(--ui-text-secondary)}.gr-about ul{margin:6px 0 0;padding-left:18px;color:var(--ui-text-secondary);display:flex;flex-direction:column;gap:2px}
.gr-about b{font-weight:600}.gr-about li b{color:var(--foreground);font-weight:500}.gr-about code{font:12px var(--font-mono,ui-monospace,monospace);color:var(--foreground)}
.gr-about-text{flex:1;min-width:0}
.gr-health{cursor:pointer}.gr-health:hover{background:color-mix(in srgb,currentColor 14%,transparent)}
.gr-health-info{font-size:12px;color:var(--ui-text-secondary);padding:8px 10px;border-radius:6px;background:var(--chrome-action-hover)}
.gr-health-info p{margin:0}.gr-health-info b{color:var(--foreground);font-weight:500}.gr-health-info ul{margin:4px 0 0;padding-left:18px}
.gr-builder{display:flex;flex-direction:column;gap:10px;padding:12px 14px;margin-bottom:10px;border:1px solid var(--ui-stroke-secondary);border-radius:8px}
.gr-fields{display:flex;flex-wrap:wrap;gap:10px 12px}.gr-field{display:flex;flex-direction:column;gap:3px;font-size:11px;color:var(--ui-text-tertiary);min-width:0}
.gr-select{font:inherit;font-size:12px;color:var(--foreground);background:var(--background);border:1px solid var(--ui-stroke-secondary);border-radius:6px;padding:4px 8px;min-width:120px;max-width:220px}
.gr-builder .gr-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.gr-builder .gr-muted{margin:0}
.gr-cta:disabled{opacity:.6;cursor:default}
.gr-builder-note{margin:0;font-size:12px;color:var(--foreground)}
[data-pick]{cursor:pointer}.gr-bar-row[data-pick]:hover .gr-bar,.gr-col[data-pick]:hover,.gr-slice[data-pick]:hover{filter:brightness(1.15)}
.gr-trend{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-bottom:8px}.gr-trend .gr-muted{margin:0}.gr-trend b{font-size:20px;font-weight:600}
.gr-delta{font-size:12px;color:var(--ui-text-secondary)}
.gr-pivot th{text-align:left;font-weight:500}.gr-table.gr-pivot td.gr-num[style]{background:color-mix(in srgb,var(--s1) var(--heat),transparent)}
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
.gr-grow{flex:1;min-height:560px;display:flex;flex-direction:column}
.gr-split{flex:1;min-height:0;display:flex;border:1px solid var(--ui-stroke-secondary);border-radius:8px;overflow:hidden}
.gr-list{width:min(38%,340px);min-width:200px;overflow:auto;border-right:1px solid var(--ui-stroke-secondary)}
.gr-item{display:block;width:100%;text-align:left;padding:9px 12px;border:0;border-bottom:1px solid var(--ui-stroke-secondary);background:transparent;color:inherit;font:inherit;cursor:pointer}
.gr-item:hover{background:var(--chrome-action-hover)}.gr-item[aria-current]{background:color-mix(in srgb,var(--ui-accent) 10%,transparent)}
.gr-item-top{display:flex;gap:8px;align-items:baseline;min-width:0}.gr-item-top b{font-weight:500;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gr-item-sub{display:block;margin-top:3px;font-size:11px;color:var(--ui-text-tertiary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gr-qid{flex:none;font:600 11px var(--font-mono,ui-monospace,monospace);color:var(--ui-accent)}
.gr-detail{flex:1;min-width:0;overflow:auto;padding:16px 20px}
.gr-detail-head{display:flex;gap:8px;align-items:baseline;min-width:0}.gr-detail-head h2{margin:0;font-size:16px;font-weight:600;overflow-wrap:anywhere}
.gr-question{margin:4px 0 12px;color:var(--ui-text-secondary)}
.gr-kpis{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0}.gr-kpi{display:flex;flex-direction:column;padding:10px 14px;border:1px solid var(--ui-stroke-secondary);border-radius:8px;min-width:130px}
.gr-kpi b{font-size:22px;font-weight:600;font-variant-numeric:tabular-nums}.gr-kpi span{font-size:12px;color:var(--ui-text-tertiary)}
.gr-bars{display:grid;grid-template-columns:minmax(60px,max-content) minmax(80px,1fr) max-content;gap:4px 10px;align-items:center;margin:10px 0;max-width:640px}
.gr-bar-row{display:contents}.gr-bar-label{text-align:right;color:var(--ui-text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:160px}
.gr-bar-value{font-variant-numeric:tabular-nums;color:var(--ui-text-secondary);font-size:12px}
.gr-tabs{display:flex;gap:2px;border-bottom:1px solid var(--ui-stroke-secondary);margin:4px 0 12px}
.gr-tab{border:0;background:none;font:inherit;color:var(--ui-text-secondary);padding:7px 12px;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}
.gr-tab:hover{color:var(--foreground)}.gr-tab[aria-selected=true]{color:var(--foreground);border-bottom-color:var(--s1);font-weight:500}
.gr-pickers{display:flex;flex-wrap:wrap;gap:6px 16px;margin-bottom:6px}.gr-picker{display:flex;align-items:center;gap:4px;flex-wrap:wrap}
.gr-picker-label{font-size:11px;color:var(--ui-text-tertiary);margin-right:2px}.gr-opt{cursor:pointer;padding:2px 9px}
.gr-opt[aria-checked=true]{background:color-mix(in srgb,var(--s1) 20%,transparent);color:var(--foreground)}
.gr-chart{position:relative;max-width:640px;margin:6px 0}.gr-chart svg{width:100%;display:block}
.gr-tip{position:absolute;z-index:2;pointer-events:none;transform:translate(12px,-120%);padding:4px 8px;border-radius:6px;font-size:12px;white-space:nowrap;
background:var(--background);color:var(--foreground);border:1px solid var(--ui-stroke-secondary);box-shadow:0 4px 14px rgba(0,0,0,.18);font-variant-numeric:tabular-nums}
.gr-tip[data-right]{transform:translate(calc(-100% - 12px),-120%)}
.gr-hit{fill:transparent}.gr-grid{stroke:var(--ui-stroke-secondary)}.gr-tick{fill:var(--ui-text-tertiary);font-size:11px}
.gr-path-line{fill:none;stroke:var(--s1);stroke-width:2;stroke-linejoin:round}.gr-area{fill:color-mix(in srgb,var(--s1) 18%,transparent)}
.gr-dot{fill:var(--s1);stroke:var(--background);stroke-width:1.5}.gr-col{fill:var(--s1)}.gr-col:hover,.gr-pt:hover,.gr-heat:hover,.gr-slice:hover{opacity:.8}
.gr-neg{fill:var(--neg)}.gr-pt{fill:var(--s1);stroke:var(--background);stroke-width:2}
.gr-heat.gr-h0{fill:var(--h0)}.gr-heat.gr-h1{fill:var(--h1)}.gr-heat.gr-h2{fill:var(--h2)}.gr-heat.gr-h3{fill:var(--h3)}.gr-heat.gr-h4{fill:var(--h4)}.gr-heat.gr-h5{fill:var(--h5)}.gr-heat.gr-h6{fill:var(--h6)}
.gr-bar-track{height:14px}.gr-bar{display:block;height:100%;min-width:2px;border-radius:0 4px 4px 0;background:var(--s1)}.gr-bar[data-neg]{background:var(--neg)}
.gr-bar-row:hover .gr-bar{opacity:.8}
.gr-donut{display:flex;align-items:center;gap:20px;flex-wrap:wrap}.gr-donut svg{width:200px;flex:none}
.gr-slice{stroke:var(--background);stroke-width:2}.gr-donut-total{fill:var(--foreground);font-size:20px;font-weight:600}
.gr-legend{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--ui-text-secondary)}
.gr-legend li{display:flex;align-items:center;gap:8px}.gr-legend b{margin-left:auto;padding-left:12px;font-weight:500;color:var(--foreground);font-variant-numeric:tabular-nums}
.gr-swatch{width:10px;height:10px;border-radius:3px;flex:none}
.gr-s1{fill:var(--s1);background:var(--s1)}.gr-s2{fill:var(--s2);background:var(--s2)}.gr-s3{fill:var(--s3);background:var(--s3)}
.gr-s4{fill:var(--s4);background:var(--s4)}.gr-s5{fill:var(--s5);background:var(--s5)}.gr-s6{fill:var(--s6);background:var(--s6)}
.gr-table td.gr-num[style]{background:linear-gradient(to left,color-mix(in srgb,var(--s1) 14%,transparent) var(--w),transparent var(--w))}
.gr-table td[data-neg]{color:var(--neg)}
.gr-table-wrap{overflow-x:auto;margin-top:8px}.gr-table{border-collapse:collapse;font-size:12px}
.gr-table th,.gr-table td{padding:5px 10px;border-bottom:1px solid var(--ui-stroke-secondary);text-align:left;white-space:nowrap}
.gr-table th{font-weight:500;color:var(--ui-text-secondary)}.gr-num{text-align:right!important;font-variant-numeric:tabular-nums}
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

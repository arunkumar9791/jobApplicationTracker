import { useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AlertTriangle, Award, FileSpreadsheet, BellRing, Briefcase, Clock, MessageSquareReply, Table2, Target, TrendingUp, Users, XCircle } from 'lucide-react'
import { api, type DashboardFilters } from '../lib/api'
import { formatDate, todayIso } from '../lib/format'

type Range = 'week' | 'month' | '90d' | 'all' | 'custom'
const RANGE_LABEL: Record<Range, string> = { week: 'This week', month: 'This month', '90d': 'Last 90 days', all: 'All time', custom: 'Custom' }

function isoDaysAgo(n: number) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function rangeDates(range: Range, custom: { start: string; end: string }): Pick<DashboardFilters, 'start' | 'end'> {
  const today = todayIso()
  switch (range) {
    case 'week': return { start: isoDaysAgo((new Date().getDay() + 6) % 7), end: today } // Monday-based
    case 'month': return { start: `${today.slice(0, 8)}01`, end: today }
    case '90d': return { start: isoDaysAgo(89), end: today }
    case 'custom': return { start: custom.start || undefined, end: custom.end || undefined }
    default: return {}
  }
}

const pct = (r: number | null | undefined) => (r == null ? '—' : `${Math.round(r * 100)}%`)

export function DashboardPage() {
  const [range, setRange] = useState<Range>('all')
  const [custom, setCustom] = useState({ start: '', end: '' })
  const [source, setSource] = useState('')
  const [location, setLocation] = useState('')

  const filters = useMemo(() => ({ ...rangeDates(range, custom), source: source || undefined, location: location || undefined }), [range, custom, source, location])
  const { data, error, isFetching } = useQuery({ queryKey: ['dashboard', filters], queryFn: () => api.dashboard(filters), placeholderData: keepPreviousData })

  if (error && !data) return <div className="card p-6 text-sm text-red-600">Couldn't load the dashboard: {error.message}</div>
  if (!data) return <p className="py-16 text-center text-sm text-slate-500">Loading…</p>
  const k = data.kpis
  const filtered = range !== 'all' || source || location

  return (
    <div className={clsx('space-y-5 transition-opacity', isFetching && 'opacity-70')}>
      {/* Filters: one row above everything they control. */}
      <div className="card flex flex-wrap items-end gap-3 p-4">
        <div>
          <span className="label">Date applied</span>
          <div className="flex flex-wrap rounded-lg bg-slate-100 p-1 text-sm dark:bg-slate-800">
            {(Object.keys(RANGE_LABEL) as Range[]).map((r) => (
              <button
                key={r}
                onClick={() => setRange(r)}
                aria-pressed={range === r}
                className={clsx('rounded-md px-3 py-1 font-medium', range === r ? 'bg-white text-indigo-700 shadow-sm dark:bg-slate-900 dark:text-indigo-300' : 'text-slate-500')}
              >
                {RANGE_LABEL[r]}
              </button>
            ))}
          </div>
        </div>
        {range === 'custom' && (
          <div className="flex items-end gap-2">
            <label><span className="label">From</span><input type="date" className="input-sm" value={custom.start} onChange={(e) => setCustom((c) => ({ ...c, start: e.target.value }))} /></label>
            <label><span className="label">To</span><input type="date" className="input-sm" value={custom.end} onChange={(e) => setCustom((c) => ({ ...c, end: e.target.value }))} /></label>
          </div>
        )}
        <label className="min-w-40">
          <span className="label">Source</span>
          <select className="input-sm" value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">All sources</option>
            {data.options.sources.map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <label className="min-w-40">
          <span className="label">Location</span>
          <select className="input-sm" value={location} onChange={(e) => setLocation(e.target.value)}>
            <option value="">All locations</option>
            {data.options.locations.map((l) => <option key={l}>{l}</option>)}
          </select>
        </label>
        {filtered && (
          <button className="btn-ghost text-indigo-600" onClick={() => { setRange('all'); setSource(''); setLocation('') }}>Reset filters</button>
        )}
        <a className="btn-ghost ml-auto ring-1 ring-inset ring-slate-200 dark:ring-slate-700" href="/api/export/xlsx" download title="Workbook with a live-formula dashboard, native charts and dropdowns (all records, unfiltered)">
          <FileSpreadsheet size={16} className="text-emerald-600" /> Download Excel
        </a>
      </div>

      {(k.future_dated > 0 || k.undated > 0) && (
        <Link to="/applications?review=1" className="flex items-center gap-2 rounded-lg bg-amber-50 px-4 py-2.5 text-sm text-amber-800 hover:bg-amber-100 dark:bg-amber-500/10 dark:text-amber-200">
          <AlertTriangle size={16} className="shrink-0" />
          <span>
            {[k.future_dated && `${k.future_dated} application${k.future_dated > 1 ? 's have' : ' has'} a future applied date`, k.undated && `${k.undated} ha${k.undated > 1 ? 've' : 's'} no applied date`].filter(Boolean).join(' and ')}
            {' '}– counted in totals, left out of the weekly chart and response times. Review them →
          </span>
        </Link>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Stat icon={Briefcase} label="Applications" value={k.applications} sub={`${k.applications_this_week} this week · ${k.applications_this_month} this month`} />
        <Stat icon={TrendingUp} label="Active" value={k.active} sub={`${k.awaiting_response} awaiting reply`} />
        <Stat icon={MessageSquareReply} label="Response rate" value={pct(k.response_rate)} sub={`${k.responded} of ${k.applications} responded`} />
        <Stat icon={Users} label="Interviews" value={k.interviews} sub={`${pct(k.interview_rate)} interview rate`} />
        <Stat icon={Award} label="Offers" value={k.offers} sub={`${pct(k.offer_rate)} offer rate`} />
        <Stat icon={XCircle} label="Rejections" value={k.rejections} sub={k.applications ? `${pct(k.rejections / k.applications)} of applications` : '—'} />
        <Stat icon={Clock} label="Avg days to response" value={k.avg_days_to_response ?? '—'} sub="from applying to first reply" />
        <Stat icon={BellRing} label="Follow-ups" value={k.follow_ups_overdue} sub={`overdue · ${k.follow_ups_due_this_week} due this week`} tone={k.follow_ups_overdue ? 'warn' : undefined} />
        <Stat icon={Target} label="Wishlist" value={k.wishlist} sub="companies to apply to" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="Applications per week"
          subtitle="By week applied (Monday start)"
          className="lg:col-span-2"
          table={{ head: ['Week of', 'Applications', 'Responded'], rows: data.weekly.map((w) => [formatDate(w.week), w.applications, w.responded]) }}
        >
          {data.weekly.length === 0 ? <NoData /> : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={data.weekly} margin={{ top: 20, right: 8, left: -16, bottom: 0 }} barCategoryGap={2}>
                <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
                <XAxis dataKey="week" tickFormatter={(w: string) => formatDate(w).replace(/ \d{4}$/, '')} tick={{ fill: 'var(--chart-axis)', fontSize: 12 }} axisLine={false} tickLine={false} minTickGap={16} />
                <YAxis allowDecimals={false} tick={{ fill: 'var(--chart-axis)', fontSize: 12 }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: 'var(--chart-cursor)' }} content={<Tip render={(p: { week: string; applications: number; responded: number }) => (
                  <><p className="font-medium">Week of {formatDate(p.week)}</p><p>{p.applications} applications · {p.responded} responded</p></>
                )} />} />
                <Bar dataKey="applications" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={48} isAnimationActive={false}>
                  {data.weekly.length <= 16 && <LabelList dataKey="applications" position="top" className="fill-slate-500 text-xs" formatter={(v: unknown) => (v ? String(v) : '')} />}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard
          title="Pipeline funnel"
          subtitle="Applications that reached each stage"
          table={{ head: ['Stage', 'Reached', '% of applied'], rows: data.funnel.map((f) => [f.status, f.count, pct(k.applications ? f.count / k.applications : null)]) }}
        >
          <HBars data={data.funnel.map((f) => ({ label: f.status, value: f.count, text: `${f.count} · ${pct(k.applications ? f.count / k.applications : null)}` }))} />
        </ChartCard>

        <ChartCard
          title="Current status"
          subtitle="Where each application stands now"
          table={{ head: ['Status', 'Applications'], rows: data.by_status.map((s) => [s.status, s.count]) }}
        >
          <HBars data={data.by_status.map((s) => ({ label: s.status, value: s.count }))} />
        </ChartCard>

        <ChartCard
          title="By source"
          subtitle="Applications, and the share that got a response"
          className="lg:col-span-2"
          table={{ head: ['Source', 'Applications', 'Responded', 'Response rate'], rows: data.by_source.map((s) => [s.source, s.applications, s.responded, pct(s.response_rate)]) }}
        >
          {/* Two measures, two charts sharing one row order – never a dual axis. */}
          <div className="grid gap-6 md:grid-cols-2">
            <div>
              <p className="mb-1 text-xs font-medium text-slate-500">Applications</p>
              <HBars data={data.by_source.map((s) => ({ label: s.source, value: s.applications }))} />
            </div>
            <div>
              <p className="mb-1 text-xs font-medium text-slate-500">Response rate</p>
              <HBars max={1} data={data.by_source.map((s) => ({ label: s.source, value: s.response_rate ?? 0, text: `${pct(s.response_rate)} (${s.responded}/${s.applications})` }))} />
            </div>
          </div>
        </ChartCard>

        <ChartCard
          title="By location"
          subtitle="Multi-city roles count once per city"
          table={{ head: ['Location', 'Applications'], rows: data.by_location.map((l) => [l.location, l.applications]) }}
        >
          <HBars data={data.by_location.map((l) => ({ label: l.location, value: l.applications }))} />
        </ChartCard>

        <ChartCard
          title="By work mode"
          subtitle="Onsite, hybrid or remote"
          table={{ head: ['Work mode', 'Applications'], rows: data.by_work_mode.map((m) => [m.work_mode, m.applications]) }}
        >
          <HBars data={data.by_work_mode.map((m) => ({ label: m.work_mode, value: m.applications }))} />
        </ChartCard>
      </div>
    </div>
  )
}

function Stat({ icon: Icon, label, value, sub, tone }: { icon: typeof Briefcase; label: string; value: ReactNode; sub: string; tone?: 'warn' }) {
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">{label}</p>
        <Icon size={18} className={tone === 'warn' ? 'text-amber-500' : 'text-indigo-500'} />
      </div>
      <p className={clsx('mt-2 text-3xl font-bold tabular-nums', tone === 'warn' && 'text-amber-600')}>{value}</p>
      <p className="mt-1 text-xs text-slate-500">{sub}</p>
    </div>
  )
}

function ChartCard({ title, subtitle, className, table, children }: {
  title: string; subtitle: string; className?: string; table: { head: string[]; rows: ReactNode[][] }; children: ReactNode
}) {
  const [showTable, setShowTable] = useState(false)
  return (
    <section className={clsx('card p-5', className)}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">{title}</h2>
          <p className="text-xs text-slate-500">{subtitle}</p>
        </div>
        <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setShowTable((t) => !t)} aria-pressed={showTable}>
          <Table2 size={14} /> {showTable ? 'Chart' : 'Table'}
        </button>
      </div>
      {showTable ? (
        <table className="w-full text-sm">
          <thead><tr className="border-b border-slate-200 text-left text-xs text-slate-500 dark:border-slate-800">{table.head.map((h) => <th key={h} className="py-1.5 pr-3 font-medium">{h}</th>)}</tr></thead>
          <tbody>{table.rows.map((r, i) => <tr key={i} className="border-b border-slate-100 dark:border-slate-800/60">{r.map((c, j) => <td key={j} className="py-1.5 pr-3 tabular-nums">{c}</td>)}</tr>)}</tbody>
        </table>
      ) : children}
    </section>
  )
}

/** Ranked horizontal bars with the value at the bar end; category labels on the left. */
function HBars({ data, max }: { data: { label: string; value: number; text?: string }[]; max?: number }) {
  if (data.length === 0) return <NoData />
  const height = data.length * 34 + 8
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 112, left: 0, bottom: 0 }} barCategoryGap={6}>
        <XAxis type="number" hide domain={[0, max ?? 'dataMax']} />
        <YAxis type="category" dataKey="label" width={130} tick={{ fill: 'var(--chart-axis)', fontSize: 12 }} axisLine={false} tickLine={false} interval={0} />
        <Tooltip cursor={{ fill: 'var(--chart-cursor)' }} content={<Tip render={(p: { label: string; value: number; text?: string }) => <><p className="font-medium">{p.label}</p><p>{p.text ?? p.value}</p></>} />} />
        <Bar dataKey="value" fill="var(--series-1)" radius={[0, 4, 4, 0]} minPointSize={2} isAnimationActive={false}>
          <LabelList dataKey={(d: { value: number; text?: string }) => d.text ?? d.value} position="right" className="fill-slate-600 text-xs dark:fill-slate-300" style={{ whiteSpace: 'nowrap' }} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function Tip({ active, payload, render }: { active?: boolean; payload?: { payload: any }[]; render: (p: any) => ReactNode }) {
  if (!active || !payload?.length) return null
  return <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900">{render(payload[0].payload)}</div>
}

function NoData() {
  return <p className="py-10 text-center text-sm text-slate-500">No applications in this range.</p>
}

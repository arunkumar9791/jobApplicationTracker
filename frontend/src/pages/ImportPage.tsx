import { useMemo, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertTriangle, ArrowRight, Check, ChevronDown, CircleX, FileSpreadsheet, Loader2, RotateCcw, Upload, Wand2 } from 'lucide-react'
import { api, type ImportAnalysis, type ImportOptions, type ImportSummary, type RowAction, type UploadResult } from '../lib/api'
import { describeFlag, formatDate } from '../lib/format'

const ACTION_STYLE: Record<RowAction, string> = {
  add: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
  update: 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300',
  unchanged: 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400',
  merged: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
  skip: 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300',
}
const ACTION_LABEL: Record<RowAction, string> = { add: 'Add', update: 'Update', unchanged: 'No change', merged: 'Duplicate', skip: 'Skip' }
const FIELD_LABEL: Record<string, string> = { source: 'Source', location: 'Location', work_mode: 'Work mode', company: 'Company', status: 'Status' }
const REASON_LABEL = { alias: 'known variant', case: 'capitalisation', typo: 'likely typo' }
const PREVIEW_LIMIT = 500

export function ImportPage() {
  const [upload, setUpload] = useState<UploadResult | null>(null)
  const [summary, setSummary] = useState<ImportSummary | null>(null)

  if (summary) return <Done summary={summary} onAgain={() => { setSummary(null); setUpload(null) }} />
  if (!upload) return <UploadStep onUploaded={setUpload} />
  return <Configure upload={upload} onReset={() => setUpload(null)} onDone={setSummary} />
}

function UploadStep({ onUploaded }: { onUploaded: (u: UploadResult) => void }) {
  const ref = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const mutation = useMutation({ mutationFn: api.importUpload, onSuccess: onUploaded })
  const pick = (f?: File) => f && mutation.mutate(f)

  return (
    <div className="card mx-auto max-w-2xl p-8">
      <h2 className="text-lg font-semibold">Import from Excel or CSV</h2>
      <p className="mt-1 text-sm text-slate-500">
        Upload your tracker spreadsheet. Nothing changes until you review the preview and confirm.
      </p>
      <button
        type="button"
        onClick={() => ref.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]) }}
        className={clsx(
          'mt-6 flex w-full flex-col items-center gap-3 rounded-xl border-2 border-dashed px-6 py-12 text-center transition',
          drag ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-500/10' : 'border-slate-300 hover:border-indigo-400 dark:border-slate-700',
        )}
      >
        {mutation.isPending ? <Loader2 className="animate-spin text-indigo-600" size={32} /> : <Upload className="text-indigo-600" size={32} />}
        <span className="font-medium">{mutation.isPending ? 'Reading file…' : 'Drop a file here or click to choose'}</span>
        <span className="text-xs text-slate-500">.xlsx, .xls or .csv · up to 20 MB</span>
      </button>
      <input ref={ref} type="file" hidden accept=".xlsx,.xlsm,.xls,.csv,.tsv" onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />
      {mutation.error && <p className="mt-3 text-sm text-red-600">{mutation.error.message}</p>}
    </div>
  )
}

function Configure({ upload, onReset, onDone }: { upload: UploadResult; onReset: () => void; onDone: (s: ImportSummary) => void }) {
  const qc = useQueryClient()
  const firstSheet = upload.sheets.find((s) => s.name === 'Applications')?.name ?? [...upload.sheets].sort((a, b) => b.rows - a.rows)[0]?.name
  const [opts, setOpts] = useState<ImportOptions>({
    token: upload.token, sheet: firstSheet, header_row: null, mapping: null, mode: 'merge', declined: null, keep_duplicates: null, date_fixes: {},
  })
  const set = (patch: Partial<ImportOptions>) => setOpts((o) => ({ ...o, ...patch }))

  const analysis = useQuery({
    queryKey: ['import-analysis', opts],
    queryFn: () => api.importAnalyze(opts),
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: Infinity,
  })
  const commit = useMutation({
    mutationFn: () => api.importCommit({ ...opts, header_row: analysis.data?.header_row, mapping: analysis.data?.mapping }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ['applications'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      onDone(s)
    },
  })

  // Keep showing the last successful analysis when a change fails (e.g. Company unmapped), so it can be undone.
  const [lastGood, setLastGood] = useState<ImportAnalysis | undefined>()
  if (analysis.data && analysis.data !== lastGood) setLastGood(analysis.data)
  const a = analysis.data ?? lastGood
  const toggle = (list: string[], key: string) => (list.includes(key) ? list.filter((k) => k !== key) : [...list, key])

  return (
    <div className="space-y-4 pb-28">
      <div className="card flex flex-wrap items-center gap-4 p-4">
        <FileSpreadsheet className="text-emerald-600" />
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold">{upload.filename}</p>
          {a && (
            <p className="text-xs text-slate-500">
              {a.counts.rows} rows read{a.counts.blank > 0 && `, ${a.counts.blank} blank rows ignored`}
            </p>
          )}
        </div>
        {upload.sheets.length > 1 && (
          <label className="text-sm">
            <span className="label">Sheet</span>
            <select className="input-sm w-48" value={opts.sheet ?? ''} onChange={(e) => set({ sheet: e.target.value, header_row: null, mapping: null, date_fixes: {}, declined: null, keep_duplicates: null })}>
              {upload.sheets.map((s) => <option key={s.name} value={s.name}>{s.name} ({s.rows} rows)</option>)}
            </select>
          </label>
        )}
        <label className="text-sm">
          <span className="label">Header row</span>
          <input
            type="number" min={1} className="input-sm w-24"
            value={opts.header_row ?? a?.header_row ?? ''}
            onChange={(e) => set({ header_row: Number(e.target.value) || null, mapping: null })}
          />
        </label>
        <button className="btn-ghost" onClick={onReset}><RotateCcw size={15} /> Choose another file</button>
      </div>

      {analysis.error && !a && (
        <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
          {analysis.error.message}
          {analysis.error.message.includes('expired') && <button className="ml-2 underline" onClick={onReset}>Upload again</button>}
        </div>
      )}
      {!a && analysis.isLoading && <p className="py-12 text-center text-sm text-slate-500"><Loader2 className="mr-2 inline animate-spin" size={16} />Analysing…</p>}

      {a && (
        <>
          <Counts a={a} />
          {analysis.error && <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">{analysis.error.message}</div>}

          <Section
            title="1. Column mapping"
            subtitle={`${Object.values(a.mapping).filter((f) => f && f !== '__notes__').length} columns recognised`}
            defaultOpen={Object.values(a.mapping).some((f) => f === '__notes__') || !Object.values(a.mapping).includes('company')}
          >
            <Mapping a={a} mapping={opts.mapping ?? a.mapping} onChange={(mapping) => set({ mapping, header_row: a.header_row })} />
          </Section>

          <Section
            title="2. Normalise values"
            subtitle={a.suggestions.length ? `${a.suggestions.filter((s) => s.approved).length} of ${a.suggestions.length} merges approved` : 'No variants found'}
            defaultOpen={a.suggestions.length > 0}
          >
            {a.suggestions.length === 0 ? <Empty>All category values look consistent.</Empty> : (
              <div className="space-y-1">
                <div className="mb-2 flex gap-2 text-xs">
                  <button className="text-indigo-600 hover:underline" onClick={() => set({ declined: [] })}>Approve all</button>
                  <button className="text-indigo-600 hover:underline" onClick={() => set({ declined: a.suggestions.map((s) => s.key) })}>Approve none</button>
                </div>
                {a.suggestions.map((s) => (
                  <label key={s.key} className="flex cursor-pointer flex-wrap items-center gap-3 rounded-lg px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <input type="checkbox" checked={s.approved} onChange={() => set({ declined: toggle(a.suggestions.filter((x) => !x.approved).map((x) => x.key), s.key) })} />
                    <span className="w-20 text-xs font-medium uppercase tracking-wide text-slate-400">{FIELD_LABEL[s.field] ?? s.field}</span>
                    <span className={clsx('font-mono text-sm', s.approved && 'text-slate-400 line-through')}>{s.source}</span>
                    <ArrowRight size={14} className="text-slate-400" />
                    <span className="font-mono text-sm font-medium">{s.target}</span>
                    <span className="text-xs text-slate-500">{REASON_LABEL[s.reason]} · {s.count} row{s.count > 1 && 's'}</span>
                  </label>
                ))}
              </div>
            )}
          </Section>

          <Section
            title="3. Possible duplicates"
            subtitle={a.duplicates.length ? `${a.duplicates.length} group${a.duplicates.length > 1 ? 's' : ''}` : 'None found'}
            defaultOpen={a.duplicates.length > 0}
          >
            {a.duplicates.length === 0 ? <Empty>No duplicates by Company + Job ID or Company + Title.</Empty> : (
              <div className="space-y-2">
                {a.duplicates.map((d) => (
                  <div key={d.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 px-3 py-2.5 dark:border-slate-800">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium">{d.label}</p>
                      <p className="text-xs text-slate-500">
                        Rows {d.rows.join(', ')} · {d.kind === 'wishlist' ? 'Merge drops the wishlist row and keeps the application.' : 'Merge keeps the most recently updated row and fills its blanks from the others.'}
                      </p>
                    </div>
                    <div className="flex rounded-lg bg-slate-100 p-0.5 text-xs dark:bg-slate-800">
                      {[false, true].map((keep) => (
                        <button
                          key={String(keep)}
                          onClick={() => d.keep !== keep && set({ keep_duplicates: toggle(a.duplicates.filter((x) => x.keep).map((x) => x.id), d.id) })}
                          className={clsx('rounded-md px-3 py-1 font-medium', d.keep === keep ? 'bg-white text-indigo-700 shadow-sm dark:bg-slate-900 dark:text-indigo-300' : 'text-slate-500')}
                        >
                          {keep ? 'Keep both' : 'Merge'}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Section>

          <Section
            title="4. Issues to review"
            subtitle={`${a.counts.errors} error${a.counts.errors === 1 ? '' : 's'}, ${a.counts.warnings} warning${a.counts.warnings === 1 ? '' : 's'}`}
            defaultOpen={a.issues.length > 0}
          >
            {a.issues.length === 0 && Object.keys(opts.date_fixes).length === 0 ? <Empty>No problems found.</Empty> : (
              <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                {a.issues.map((i, idx) => (
                  <li key={idx} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                    {i.level === 'error' ? <CircleX size={16} className="text-red-500" /> : <AlertTriangle size={16} className="text-amber-500" />}
                    <span className="w-14 text-xs text-slate-400">Row {i.row}</span>
                    <span className="w-40 truncate font-medium">{i.company ?? '—'}</span>
                    <span className="flex-1 text-slate-600 dark:text-slate-300">{i.message}</span>
                    {i.fix && (
                      <button className="btn-ghost py-1 text-xs text-indigo-600 ring-1 ring-inset ring-indigo-200 dark:ring-indigo-500/30" onClick={() => set({ date_fixes: { ...opts.date_fixes, [i.row]: i.fix!.value } })}>
                        <Wand2 size={13} /> {i.fix.label}
                      </button>
                    )}
                  </li>
                ))}
                {Object.entries(opts.date_fixes).map(([row, value]) => (
                  <li key={`fix-${row}`} className="flex items-center gap-3 py-2 text-sm">
                    <Check size={16} className="text-emerald-500" />
                    <span className="w-14 text-xs text-slate-400">Row {row}</span>
                    <span className="flex-1 text-slate-600 dark:text-slate-300">Date applied set to {formatDate(value)}</span>
                    <button className="text-xs text-slate-500 hover:underline" onClick={() => { const { [row]: _, ...rest } = opts.date_fixes; set({ date_fixes: rest }) }}>Undo</button>
                  </li>
                ))}
              </ul>
            )}
            {a.counts.flagged > 0 && <p className="mt-3 text-xs text-slate-500">Rows with warnings are imported and marked "Needs review" in the Applications table.</p>}
          </Section>

          <Section title="5. Preview" subtitle={`${a.counts.add + a.counts.update} rows will be written`} defaultOpen>
            <Preview a={a} />
          </Section>
        </>
      )}

      {a && (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white/95 backdrop-blur dark:border-slate-800 dark:bg-slate-900/95">
          <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-4 px-4 py-3 sm:px-6">
            <fieldset className="flex flex-wrap gap-4 text-sm">
              <ModeOption checked={opts.mode === 'merge'} onChange={() => set({ mode: 'merge' })} title="Merge" text="update matching records, add new ones" />
              <ModeOption checked={opts.mode === 'replace'} onChange={() => set({ mode: 'replace' })} title="Replace all" text={`delete the ${a.counts.existing} existing records first`} danger />
            </fieldset>
            <div className="ml-auto flex items-center gap-3">
              {commit.error && <span className="text-sm text-red-600">{commit.error.message}</span>}
              {analysis.isFetching && <Loader2 size={16} className="animate-spin text-slate-400" />}
              <button
                className={opts.mode === 'replace' && a.counts.existing > 0 ? 'btn-danger' : 'btn-primary'}
                disabled={commit.isPending || analysis.isFetching || !!analysis.error || a.counts.add + a.counts.update === 0}
                onClick={() => {
                  if (opts.mode === 'replace' && a.counts.existing > 0 && !confirm(`Delete all ${a.counts.existing} existing records and import ${a.counts.add}?`)) return
                  commit.mutate()
                }}
              >
                {commit.isPending ? 'Importing…' : opts.mode === 'merge' ? `Import: add ${a.counts.add}, update ${a.counts.update}` : `Replace with ${a.counts.add} records`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Counts({ a }: { a: ImportAnalysis }) {
  const c = a.counts
  const items: [string, ReactNode, string?][] = [
    ['Applications', <>{c.applications} <span className="text-sm font-normal text-slate-500">({c.companies} companies)</span></>],
    ['Wishlist', c.wishlist],
    ...(a.mode === 'merge' && c.existing ? [['New', c.add], ['Updated', c.update], ['Unchanged', c.unchanged]] as [string, number][] : []),
    ['Skipped / merged', c.skipped],
    ['Flagged for review', c.flagged, c.flagged ? 'text-amber-600' : undefined],
  ]
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
      {items.map(([label, value, cls]) => (
        <div key={label} className="card px-4 py-3">
          <p className="text-xs text-slate-500">{label}</p>
          <p className={clsx('mt-1 text-2xl font-bold', cls)}>{value}</p>
        </div>
      ))}
    </div>
  )
}

/** `mapping` is the user's current choice, which can differ from the last successful analysis after an error. */
function Mapping({ a, mapping, onChange }: { a: ImportAnalysis; mapping: Record<string, string | null>; onChange: (m: Record<string, string | null>) => void }) {
  const used = new Set(Object.values(mapping))
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
            <th className="py-2 pr-4 font-semibold">Column in file</th>
            <th className="py-2 pr-4 font-semibold">Sample values</th>
            <th className="w-64 py-2 font-semibold">Import as</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {a.headers.map((h) => {
            const value = mapping[String(h.index)] ?? ''
            return (
              <tr key={h.index}>
                <td className="whitespace-nowrap py-2 pr-4 font-medium">{h.text || <span className="text-slate-400">Column {h.index + 1}</span>}</td>
                <td className="max-w-0 truncate py-2 pr-4 text-xs text-slate-500">{h.samples.join(' · ') || '—'}</td>
                <td className="py-2">
                  <select
                    aria-label={`Import ${h.text || `column ${h.index + 1}`} as`}
                    className={clsx('input-sm min-w-44', !value && 'text-slate-400', value === '__notes__' && 'text-amber-700 dark:text-amber-300')}
                    value={value}
                    onChange={(e) => onChange({ ...mapping, [h.index]: e.target.value || null })}
                  >
                    <option value="">Ignore</option>
                    <option value="__notes__">Append to notes</option>
                    {a.fields.map((f) => (
                      <option key={f.key} value={f.key} disabled={used.has(f.key) && value !== f.key}>{f.label}</option>
                    ))}
                  </select>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Preview({ a }: { a: ImportAnalysis }) {
  const [filter, setFilter] = useState<'all' | 'write' | 'skipped' | 'flagged'>('all')
  const rows = useMemo(() => a.rows.filter((r) =>
    filter === 'write' ? r.action === 'add' || r.action === 'update'
      : filter === 'skipped' ? r.action === 'skip' || r.action === 'merged'
        : filter === 'flagged' ? r.flags.length > 0 : true), [a.rows, filter])
  return (
    <>
      <div className="mb-3 flex flex-wrap gap-1 text-xs">
        {(['all', 'write', 'skipped', 'flagged'] as const).map((f) => (
          <button key={f} onClick={() => setFilter(f)} className={clsx('rounded-md px-2.5 py-1 font-medium', filter === f ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800')}>
            {{ all: 'All rows', write: 'Will be written', skipped: 'Skipped / duplicates', flagged: 'Flagged' }[f]}
          </button>
        ))}
      </div>
      <div className="max-h-[480px] overflow-auto rounded-lg border border-slate-200 dark:border-slate-800">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900">
            <tr>{['Row', 'Action', 'Company', 'Role', 'Job ID', 'Applied', 'Status', 'Source', 'Location'].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {rows.slice(0, PREVIEW_LIMIT).map((r) => (
              <tr key={r.row} className={clsx((r.action === 'skip' || r.action === 'merged') && 'opacity-60')}>
                <td className="px-3 py-1.5 text-xs text-slate-400">{r.row}</td>
                <td className="px-3 py-1.5">
                  <span title={r.note ?? (r.changes.length ? `Changes: ${r.changes.join(', ')}` : undefined)} className={clsx('whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium', ACTION_STYLE[r.action])}>
                    {ACTION_LABEL[r.action]}
                  </span>
                </td>
                <td className="whitespace-nowrap px-3 py-1.5 font-medium">{r.company ?? '—'}</td>
                <td className="max-w-64 truncate px-3 py-1.5">{r.title ?? ''}</td>
                <td className="px-3 py-1.5 font-mono text-xs text-slate-500">{r.job_id ?? ''}</td>
                <td className="whitespace-nowrap px-3 py-1.5">
                  {formatDate(r.date_applied)}
                  {r.flags.length > 0 && <span title={r.flags.map(describeFlag).join('\n')}><AlertTriangle size={13} className="ml-1 inline text-amber-500" /></span>}
                </td>
                <td className="whitespace-nowrap px-3 py-1.5">{r.status}</td>
                <td className="whitespace-nowrap px-3 py-1.5">{r.source ?? ''}</td>
                <td className="whitespace-nowrap px-3 py-1.5">{r.location ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > PREVIEW_LIMIT && <p className="px-3 py-2 text-xs text-slate-500">Showing the first {PREVIEW_LIMIT} of {rows.length} rows.</p>}
        {rows.length === 0 && <p className="px-3 py-6 text-center text-sm text-slate-500">No rows.</p>}
      </div>
    </>
  )
}

function Section({ title, subtitle, defaultOpen, children }: { title: string; subtitle: string; defaultOpen?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(!!defaultOpen)
  return (
    <section className="card">
      <button className="flex w-full items-center gap-3 px-5 py-4 text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="font-semibold">{title}</span>
        <span className="text-sm text-slate-500">{subtitle}</span>
        <ChevronDown size={18} className={clsx('ml-auto text-slate-400 transition', open && 'rotate-180')} />
      </button>
      {open && <div className="border-t border-slate-100 px-5 py-4 dark:border-slate-800">{children}</div>}
    </section>
  )
}

function ModeOption({ checked, onChange, title, text, danger }: { checked: boolean; onChange: () => void; title: string; text: string; danger?: boolean }) {
  return (
    <label className="flex cursor-pointer items-center gap-2">
      <input type="radio" name="import-mode" checked={checked} onChange={onChange} />
      <span className={clsx('font-medium', danger && checked && 'text-red-600')}>{title}</span>
      <span className="hidden text-slate-500 md:inline">– {text}</span>
    </label>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-slate-500">{children}</p>
}

function Done({ summary, onAgain }: { summary: ImportSummary; onAgain: () => void }) {
  const items: [string, number, string][] = [
    ['Added', summary.added, 'text-emerald-600'],
    ['Updated', summary.updated, 'text-blue-600'],
    ['Unchanged', summary.unchanged, 'text-slate-500'],
    ['Skipped / merged', summary.skipped, 'text-slate-500'],
    ['Flagged for review', summary.flagged, 'text-amber-600'],
  ]
  return (
    <div className="card mx-auto max-w-3xl p-8 text-center">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 dark:bg-emerald-500/10"><Check /></div>
      <h2 className="mt-4 text-lg font-semibold">Import complete</h2>
      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
        {items.map(([label, n, cls]) => (
          <div key={label} className="rounded-xl bg-slate-50 px-3 py-4 dark:bg-slate-800/50">
            <p className={clsx('text-2xl font-bold', cls)}>{n}</p>
            <p className="mt-1 text-xs text-slate-500">{label}</p>
          </div>
        ))}
      </div>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <Link className="btn-primary" to="/applications">View applications</Link>
        {summary.flagged > 0 && <Link className="btn-ghost ring-1 ring-inset ring-amber-200 text-amber-700" to="/applications?review=1">Review {summary.flagged} flagged</Link>}
        <button className="btn-ghost" onClick={onAgain}>Import another file</button>
      </div>
    </div>
  )
}

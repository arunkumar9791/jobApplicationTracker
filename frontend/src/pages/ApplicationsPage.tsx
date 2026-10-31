import { useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'
import {
  createColumnHelper,
  createSortedRowModel,
  columnVisibilityFeature,
  rowSelectionFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_text,
  tableFeatures,
  useTable,
  type SortingState,
  type ColumnVisibilityState as VisibilityState,
} from '@tanstack/react-table'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useSearchParams } from 'react-router'
import { AlertTriangle, ArrowDown, ArrowUp, Columns3, Download, ExternalLink, FileSpreadsheet, Pencil, Plus, Search, Trash2, X } from 'lucide-react'
import { api, WORK_MODES, type Application, type ApplicationFields } from '../lib/api'
import { DATE_PRESETS, matchDatePreset, matchesSearch, type DatePreset } from '../lib/filters'
import { describeFlag, formatDate, formatDateTime, todayIso } from '../lib/format'
import { useApplications, useBulkStatus, useDeleteApplications, useSettings, useStatusMap, useUpdateApplication } from '../lib/hooks'
import { EditableCell } from '../components/EditableCell'
import { StatusSelect } from '../components/StatusBadge'
import { ApplicationForm } from '../components/ApplicationForm'

const features = tableFeatures({
  rowSortingFeature,
  rowSelectionFeature,
  columnVisibilityFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { alphanumeric: sortFn_alphanumeric, text: sortFn_text },
})
const helper = createColumnHelper<typeof features, Application>()

type View = 'applications' | 'wishlist' | 'all'
type FilterKind = 'text' | 'date' | 'status' | 'source' | 'work_mode'

/** Column layout: width in px and which filter control the column gets. */
const COLS: Record<string, { width: number; filter?: FilterKind }> = {
  select: { width: 44 },
  company: { width: 170, filter: 'text' },
  title: { width: 280, filter: 'text' },
  job_id: { width: 110, filter: 'text' },
  date_applied: { width: 130, filter: 'date' },
  source: { width: 160, filter: 'source' },
  location: { width: 170, filter: 'text' },
  work_mode: { width: 120, filter: 'work_mode' },
  status: { width: 150, filter: 'status' },
  last_updated: { width: 150 },
  next_follow_up: { width: 130, filter: 'date' },
  contact_person: { width: 160, filter: 'text' },
  contact_info: { width: 200, filter: 'text' },
  salary_range: { width: 130, filter: 'text' },
  notes: { width: 240, filter: 'text' },
  job_link: { width: 70 },
  actions: { width: 84 },
}

const DEFAULT_HIDDEN: VisibilityState = { work_mode: false, contact_person: false, contact_info: false, salary_range: false, notes: false, last_updated: false }
const SEARCH_FIELDS = ['company', 'title', 'job_id', 'source', 'location', 'status', 'contact_person', 'contact_info', 'notes', 'salary_range'] as const
const VIS_KEY = 'applications.columnVisibility'

function loadVisibility(): VisibilityState {
  try {
    return { ...DEFAULT_HIDDEN, ...JSON.parse(localStorage.getItem(VIS_KEY) ?? '{}') }
  } catch {
    return DEFAULT_HIDDEN
  }
}

export function ApplicationsPage() {
  const { data: all, isLoading, error } = useApplications()
  const { data: settings } = useSettings()
  const statusOf = useStatusMap()
  const update = useUpdateApplication()
  const bulkStatus = useBulkStatus()
  const bulkDelete = useDeleteApplications()

  const [view, setView] = useState<View>('applications')
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [params] = useSearchParams()
  const [reviewOnly, setReviewOnly] = useState(() => params.get('review') === '1')
  const [sorting, setSorting] = useState<SortingState>([{ id: 'date_applied', desc: true }])
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(loadVisibility)
  const [editing, setEditing] = useState<Application | 'new' | null>(null)

  useEffect(() => {
    try {
      localStorage.setItem(VIS_KEY, JSON.stringify(columnVisibility))
    } catch {
      /* storage unavailable */
    }
  }, [columnVisibility])

  const counts = useMemo(() => {
    const wishlist = all.filter((a) => statusOf(a.status).kind === 'wishlist').length
    return { applications: all.length - wishlist, wishlist, all: all.length, review: all.filter((a) => a.flags.length).length }
  }, [all, statusOf])

  const data = useMemo(() => {
    return all.filter((a) => {
      const isWish = statusOf(a.status).kind === 'wishlist'
      if (view === 'applications' && isWish) return false
      if (view === 'wishlist' && !isWish) return false
      if (reviewOnly && !a.flags.length) return false
      if (!matchesSearch(a, search, SEARCH_FIELDS)) return false
      for (const [col, val] of Object.entries(filters)) {
        if (!val) continue
        const cell = a[col as keyof Application] as string | null
        const kind = COLS[col]?.filter
        if (kind === 'date') {
          if (!matchDatePreset(cell, val as DatePreset)) return false
        } else if (kind === 'text') {
          if (!String(cell ?? '').toLowerCase().includes(val.toLowerCase())) return false
        } else if (val === '__none__') {
          if (cell) return false
        } else if (cell !== val) return false
      }
      return true
    })
  }, [all, view, search, filters, reviewOnly, statusOf])

  const save = (app: Application, field: keyof ApplicationFields) => (value: string | null) =>
    update.mutate({ id: app.id, data: { [field]: value } })

  const columns = useMemo(() => {
    const sources = settings?.sources ?? []
    const text = (field: keyof ApplicationFields, header: string, extra?: { mono?: boolean; suggestions?: readonly string[] }) =>
      helper.accessor(field, {
        header,
        sortUndefined: 'last',
        cell: (info) => (
          <EditableCell
            value={info.getValue() as string | null}
            suggestions={extra?.suggestions}
            className={extra?.mono ? 'font-mono text-xs text-slate-500' : undefined}
            onSave={save(info.row.original, field)}
          />
        ),
      })
    const dateCol = (field: 'date_applied' | 'next_follow_up', header: string) =>
      helper.accessor(field, {
        header,
        sortUndefined: 'last',
        sortFn: 'alphanumeric',
        cell: (info) => {
          const flags = info.row.original.flags.filter((f) => f.startsWith(`${field}:`))
          const v = info.getValue()
          const overdue = field === 'next_follow_up' && v && v < todayIso()
          return (
            <EditableCell
              kind="date"
              value={v}
              onSave={save(info.row.original, field)}
              display={
                <span className={clsx('inline-flex items-center gap-1', overdue && 'font-medium text-red-600')}>
                  {v ? formatDate(v) : <span className="text-slate-300 dark:text-slate-600">—</span>}
                  {flags.length > 0 && (
                    <span title={flags.map(describeFlag).join('\n')} className="text-amber-500">
                      <AlertTriangle size={14} aria-label={flags.map(describeFlag).join(', ')} />
                    </span>
                  )}
                </span>
              }
            />
          )
        },
      })

    return helper.columns([
      helper.display({
        id: 'select',
        header: ({ table }) => (
          <input
            type="checkbox"
            aria-label="Select all"
            checked={table.getIsAllRowsSelected()}
            ref={(el) => {
              if (el) el.indeterminate = table.getIsSomeRowsSelected()
            }}
            onChange={table.getToggleAllRowsSelectedHandler()}
          />
        ),
        cell: ({ row }) => (
          <input type="checkbox" aria-label="Select row" checked={row.getIsSelected()} onChange={row.getToggleSelectedHandler()} />
        ),
      }),
      helper.accessor('company', {
        header: 'Company',
        sortFn: 'text',
        cell: (info) => (
          <EditableCell value={info.getValue()} className="font-semibold" onSave={(v) => v && save(info.row.original, 'company')(v)} />
        ),
      }),
      text('title', 'Job title / role'),
      text('job_id', 'Job ID', { mono: true }),
      dateCol('date_applied', 'Applied'),
      text('source', 'Source', { suggestions: sources }),
      text('location', 'Location'),
      helper.accessor('work_mode', {
        header: 'Work mode',
        sortUndefined: 'last',
        cell: (info) => (
          <EditableCell kind="select" options={WORK_MODES} value={info.getValue()} onSave={save(info.row.original, 'work_mode')} />
        ),
      }),
      helper.accessor('status', {
        header: 'Status',
        cell: (info) => <StatusSelect value={info.getValue()} onChange={(s) => save(info.row.original, 'status')(s)} />,
      }),
      helper.accessor('last_updated', {
        header: 'Last updated',
        cell: (info) => <span className="text-xs text-slate-500">{formatDateTime(info.getValue())}</span>,
      }),
      dateCol('next_follow_up', 'Follow-up'),
      text('contact_person', 'Contact person'),
      text('contact_info', 'Contact email / LinkedIn'),
      text('salary_range', 'Salary range'),
      text('notes', 'Notes'),
      helper.accessor('job_link', {
        header: 'Link',
        enableSorting: false,
        cell: (info) => {
          const url = info.getValue()
          return url ? (
            <a href={url} target="_blank" rel="noreferrer" title={url} className="inline-flex items-center gap-1 rounded-md bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-700 hover:bg-indigo-100 dark:bg-indigo-500/10 dark:text-indigo-300">
              <ExternalLink size={12} /> Open
            </a>
          ) : (
            <span className="text-slate-300 dark:text-slate-600">—</span>
          )
        },
      }),
      helper.display({
        id: 'actions',
        header: '',
        cell: ({ row }) => (
          <div className="flex gap-1">
            <button className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800" aria-label="Edit" onClick={() => setEditing(row.original)}>
              <Pencil size={15} />
            </button>
            <button
              className="rounded p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10"
              aria-label="Delete"
              onClick={() => confirm(`Delete ${row.original.company}${row.original.title ? ` – ${row.original.title}` : ''}?`) && bulkDelete.mutate([row.original.id])}
            >
              <Trash2 size={15} />
            </button>
          </div>
        ),
      }),
    ])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings])

  const table = useTable({
    features,
    columns,
    data,
    getRowId: (row) => String(row.id),
    state: { sorting, columnVisibility },
    onSortingChange: setSorting,
    onColumnVisibilityChange: setColumnVisibility,
  })

  const rows = table.getRowModel().rows
  const visibleIds = new Set(rows.map((r) => r.id))
  const selectedIds = Object.keys(table.state.rowSelection ?? {}).filter((id) => visibleIds.has(id)).map(Number)
  const leafColumns = table.getVisibleLeafColumns()
  const totalWidth = leafColumns.reduce((sum, c) => sum + (COLS[c.id]?.width ?? 150), 0)

  const scrollRef = useRef<HTMLDivElement>(null)
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 49,
    getItemKey: (i) => rows[i].id,
    overscan: 10,
  })

  const activeFilters = Object.values(filters).filter(Boolean).length + (search ? 1 : 0) + (reviewOnly ? 1 : 0)
  const clearFilters = () => {
    setFilters({})
    setSearch('')
    setReviewOnly(false)
  }

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-center gap-3 p-4">
        <div className="flex rounded-lg bg-slate-100 p-1 text-sm dark:bg-slate-800">
          {(['applications', 'wishlist', 'all'] as View[]).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={clsx('rounded-md px-3 py-1.5 font-medium capitalize', view === v ? 'bg-white text-indigo-700 shadow-sm dark:bg-slate-900 dark:text-indigo-300' : 'text-slate-500')}
            >
              {v} ({counts[v]})
            </button>
          ))}
        </div>
        <label className="relative min-w-48 flex-1">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input className="input pl-9" placeholder="Search company, role, notes…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search" />
        </label>
        {counts.review > 0 && (
          <button
            onClick={() => setReviewOnly((r) => !r)}
            className={clsx('btn ring-1 ring-inset', reviewOnly ? 'bg-amber-100 text-amber-800 ring-amber-300 dark:bg-amber-500/20 dark:text-amber-200' : 'text-amber-700 ring-amber-200 hover:bg-amber-50 dark:text-amber-300 dark:ring-amber-500/30')}
          >
            <AlertTriangle size={15} /> Needs review ({counts.review})
          </button>
        )}
        <ColumnMenu table={table} />
        <ExportMenu ids={rows.map((r) => r.original.id)} fields={leafColumns.map((c) => c.id).filter((id) => id !== 'select' && id !== 'actions')} />
        <button className="btn-primary" onClick={() => setEditing('new')}>
          <Plus size={16} /> Add
        </button>
      </div>

      {selectedIds.length > 0 && (
        <div className="card flex flex-wrap items-center gap-3 border-indigo-200 bg-indigo-50 px-4 py-2.5 text-sm dark:border-indigo-500/30 dark:bg-indigo-500/10">
          <span className="font-medium">{selectedIds.length} selected</span>
          <select
            className="input-sm w-auto"
            value=""
            aria-label="Change status of selected"
            onChange={(e) => e.target.value && bulkStatus.mutate({ ids: selectedIds, status: e.target.value }, { onSuccess: () => table.resetRowSelection() })}
          >
            <option value="">Set status…</option>
            {settings?.statuses.map((s) => <option key={s.name}>{s.name}</option>)}
          </select>
          <button
            className="btn-ghost text-red-600"
            onClick={() => confirm(`Delete ${selectedIds.length} records?`) && bulkDelete.mutate(selectedIds, { onSuccess: () => table.resetRowSelection() })}
          >
            <Trash2 size={15} /> Delete
          </button>
          <button className="btn-ghost ml-auto" onClick={() => table.resetRowSelection()}>
            Clear selection
          </button>
        </div>
      )}

      {(update.error || bulkStatus.error || bulkDelete.error) && (
        <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
          {(update.error ?? bulkStatus.error ?? bulkDelete.error)?.message}
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="flex items-center justify-between px-4 py-2.5 text-xs text-slate-500">
          <span>
            Showing {rows.length} of {counts[view]} {view === 'wishlist' ? 'wishlist companies' : 'records'}
          </span>
          {activeFilters > 0 && (
            <button className="inline-flex items-center gap-1 text-indigo-600 hover:underline dark:text-indigo-400" onClick={clearFilters}>
              <X size={12} /> Clear {activeFilters} filter{activeFilters > 1 ? 's' : ''}
            </button>
          )}
        </div>
        <div ref={scrollRef} className="relative h-[calc(100vh-300px)] min-h-96 overflow-auto border-t border-slate-200 dark:border-slate-800">
          <table className="grid text-sm" style={{ width: totalWidth }}>
            <thead className="sticky top-0 z-10 grid bg-slate-50 dark:bg-slate-900">
              {table.getHeaderGroups().map((group) => (
                <tr key={group.id} className="flex">
                  {group.headers.map((header) => {
                    const sorted = header.column.getIsSorted()
                    return (
                      <th key={header.id} style={{ width: COLS[header.id]?.width }} className="flex items-center px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                        {header.column.getCanSort() ? (
                          <button className="inline-flex items-center gap-1 uppercase hover:text-slate-800 dark:hover:text-slate-200" onClick={header.column.getToggleSortingHandler()}>
                            <table.FlexRender header={header} />
                            {sorted === 'asc' && <ArrowUp size={12} />}
                            {sorted === 'desc' && <ArrowDown size={12} />}
                          </button>
                        ) : (
                          <table.FlexRender header={header} />
                        )}
                      </th>
                    )
                  })}
                </tr>
              ))}
              <tr className="flex border-b border-slate-200 dark:border-slate-800">
                {leafColumns.map((col) => (
                  <th key={col.id} style={{ width: COLS[col.id]?.width }} className="px-2 pb-2 font-normal">
                    <ColumnFilter
                      kind={COLS[col.id]?.filter}
                      label={String(col.columnDef.header ?? col.id)}
                      value={filters[col.id] ?? ''}
                      onChange={(v) => setFilters((f) => ({ ...f, [col.id]: v }))}
                      statuses={settings?.statuses.map((s) => s.name) ?? []}
                      sources={[...new Set(all.map((a) => a.source).filter(Boolean) as string[])].sort()}
                    />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="relative grid" style={{ height: virtualizer.getTotalSize() }}>
              {virtualizer.getVirtualItems().map((item) => {
                const row = rows[item.index]
                return (
                  <tr
                    key={row.id}
                    data-index={item.index}
                    ref={virtualizer.measureElement}
                    className={clsx('absolute flex w-full items-center border-b border-slate-100 hover:bg-slate-50/70 dark:border-slate-800/70 dark:hover:bg-slate-800/40', row.getIsSelected() && 'bg-indigo-50/60 dark:bg-indigo-500/10')}
                    style={{ transform: `translateY(${item.start}px)` }}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} style={{ width: COLS[cell.column.id]?.width }} className="overflow-hidden px-2 py-2">
                        <table.FlexRender cell={cell} />
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
          {!isLoading && rows.length === 0 && (
            <p className="py-16 text-center text-sm text-slate-500">{error ? `Couldn't load data: ${error.message}` : 'No records match these filters.'}</p>
          )}
          {isLoading && <p className="py-16 text-center text-sm text-slate-500">Loading…</p>}
        </div>
      </div>

      {editing && <ApplicationForm app={editing === 'new' ? undefined : editing} initial={view === 'wishlist' ? { status: 'Wishlist' } : undefined} onClose={() => setEditing(null)} />}
    </div>
  )
}

function ColumnFilter({ kind, label, value, onChange, statuses, sources }: {
  kind?: FilterKind
  label: string
  value: string
  onChange: (v: string) => void
  statuses: string[]
  sources: string[]
}) {
  const aria = `Filter ${label}`
  if (!kind) return null
  if (kind === 'text') return <input className="input-sm" placeholder="Filter…" value={value} onChange={(e) => onChange(e.target.value)} aria-label={aria} />
  const options: [string, string][] =
    kind === 'date' ? Object.entries(DATE_PRESETS)
    : kind === 'status' ? statuses.map((s) => [s, s])
    : kind === 'source' ? [...sources.map((s): [string, string] => [s, s]), ['__none__', 'Not set']]
    : [...WORK_MODES.map((m): [string, string] => [m, m]), ['__none__', 'Not set']]
  return (
    <select className="input-sm" value={value} onChange={(e) => onChange(e.target.value)} aria-label={aria}>
      <option value="">All</option>
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )
}

function useDismiss(open: boolean, setOpen: (o: boolean) => void) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open, setOpen])
  return ref
}

function ExportMenu({ ids, fields }: { ids: number[]; fields: string[] }) {
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ref = useDismiss(open, setOpen)
  const view = (format: 'csv' | 'xlsx') => {
    setOpen(false)
    api.exportView(ids, fields, format).catch((e: Error) => setError(e.message))
  }
  const item = 'flex w-full items-start gap-2 rounded px-2 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800'
  return (
    <div className="relative" ref={ref}>
      <button className="btn-ghost ring-1 ring-inset ring-slate-200 dark:ring-slate-700" onClick={() => setOpen((o) => !o)} aria-expanded={open} title={error ?? undefined}>
        <Download size={16} /> Export
      </button>
      {open && (
        <div className="card absolute right-0 z-20 mt-2 w-72 p-2">
          <a className={item} href="/api/export/xlsx" download onClick={() => setOpen(false)}>
            <FileSpreadsheet size={16} className="mt-0.5 text-emerald-600" />
            <span><span className="font-medium">Full workbook (.xlsx)</span><span className="block text-xs text-slate-500">All records, live-formula dashboard, charts, dropdowns</span></span>
          </a>
          <button className={item} onClick={() => view('xlsx')} disabled={!ids.length}>
            <Download size={16} className="mt-0.5 text-slate-400" />
            <span><span className="font-medium">Current view (.xlsx)</span><span className="block text-xs text-slate-500">{ids.length} rows, visible columns, current sort</span></span>
          </button>
          <button className={item} onClick={() => view('csv')} disabled={!ids.length}>
            <Download size={16} className="mt-0.5 text-slate-400" />
            <span><span className="font-medium">Current view (.csv)</span><span className="block text-xs text-slate-500">{ids.length} rows, visible columns</span></span>
          </button>
        </div>
      )}
    </div>
  )
}

function ColumnMenu({ table }: { table: ReturnType<typeof useTable<typeof features, Application>> }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])
  return (
    <div className="relative" ref={ref}>
      <button className="btn-ghost ring-1 ring-inset ring-slate-200 dark:ring-slate-700" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Columns3 size={16} /> Columns
      </button>
      {open && (
        <div className="card absolute right-0 z-20 mt-2 w-56 p-2">
          {table.getAllLeafColumns().filter((c) => !['select', 'actions'].includes(c.id)).map((c) => (
            <label key={c.id} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800">
              <input type="checkbox" checked={c.getIsVisible()} onChange={c.getToggleVisibilityHandler()} />
              {String(c.columnDef.header)}
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

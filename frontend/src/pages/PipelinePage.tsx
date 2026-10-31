import { useMemo, useState } from 'react'
import clsx from 'clsx'
import {
  DndContext, DragOverlay, KeyboardSensor, PointerSensor, TouchSensor, useDraggable, useDroppable, useSensor, useSensors,
  type DragEndEvent, type DragStartEvent,
} from '@dnd-kit/core'
import { AlertTriangle, ExternalLink, GripVertical, Pencil, Search } from 'lucide-react'
import type { Application, StatusDef } from '../lib/api'
import { matchesSearch } from '../lib/filters'
import { daysBetween, describeFlag, formatDate, statusStyle, todayIso } from '../lib/format'
import { useApplications, useQuickUpdate, useSettings } from '../lib/hooks'
import { ApplicationForm } from '../components/ApplicationForm'

const DOT: Record<string, string> = {
  amber: 'bg-amber-400', blue: 'bg-blue-500', violet: 'bg-violet-500', green: 'bg-emerald-500', red: 'bg-red-500', gray: 'bg-slate-400',
}

export function PipelinePage() {
  const { data: apps, isLoading } = useApplications()
  const { data: settings } = useSettings()
  const move = useQuickUpdate()
  const [query, setQuery] = useState('')
  const [showWishlist, setShowWishlist] = useState(false)
  const [showClosed, setShowClosed] = useState(true)
  const [dragging, setDragging] = useState<Application | null>(null)
  const [editing, setEditing] = useState<Application | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 6 } }),
    useSensor(KeyboardSensor),
  )

  const columns = useMemo(() => (settings?.statuses ?? []).filter((s) =>
    (showWishlist || s.kind !== 'wishlist') && (showClosed || (s.kind !== 'rejected' && s.kind !== 'closed'))), [settings, showWishlist, showClosed])

  const byStatus = useMemo(() => {
    const map = new Map<string, Application[]>()
    for (const a of apps) {
      if (!matchesSearch(a, query, ['company', 'title', 'location', 'source', 'notes'])) continue
      map.set(a.status, [...(map.get(a.status) ?? []), a])
    }
    // Most recently moved first.
    for (const list of map.values()) list.sort((a, b) => (b.status_since ?? b.last_updated).localeCompare(a.status_since ?? a.last_updated))
    return map
  }, [apps, query])

  const onDragStart = (e: DragStartEvent) => setDragging(apps.find((a) => a.id === e.active.id) ?? null)
  const onDragEnd = (e: DragEndEvent) => {
    setDragging(null)
    const target = e.over?.id as string | undefined
    const app = apps.find((a) => a.id === e.active.id)
    if (app && target && target !== app.status) move.mutate(app.id, { status: target })
  }

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-center gap-3 p-4">
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold">Pipeline</h2>
          <p className="text-xs text-slate-500">Drag a card to another column to change its status; every move is logged in the history.</p>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={showWishlist} onChange={(e) => setShowWishlist(e.target.checked)} /> Wishlist</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} /> Closed</label>
        <label className="relative w-64 max-w-full">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input className="input pl-9" placeholder="Filter cards…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Filter cards" />
        </label>
      </div>

      {move.error && <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">Couldn't move: {move.error.message}</div>}
      {isLoading && <p className="py-12 text-center text-sm text-slate-500">Loading…</p>}

      <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd} onDragCancel={() => setDragging(null)}>
        <div className="-mx-4 flex gap-3 overflow-x-auto px-4 pb-4 sm:-mx-6 sm:px-6">
          {columns.map((s) => (
            <Column key={s.name} status={s} apps={byStatus.get(s.name) ?? []} onEdit={setEditing} />
          ))}
        </div>
        <DragOverlay dropAnimation={null}>{dragging && <Card app={dragging} overlay />}</DragOverlay>
      </DndContext>

      {editing && <ApplicationForm app={editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

function Column({ status, apps, onEdit }: { status: StatusDef; apps: Application[]; onEdit: (a: Application) => void }) {
  const { setNodeRef, isOver } = useDroppable({ id: status.name })
  return (
    <section
      ref={setNodeRef}
      aria-label={`${status.name} column`}
      className={clsx('flex max-h-[calc(100vh-260px)] min-h-64 w-72 shrink-0 flex-col rounded-2xl border bg-slate-100/70 transition dark:bg-slate-900/60',
        isOver ? 'border-indigo-400 ring-2 ring-indigo-400/30' : 'border-slate-200 dark:border-slate-800')}
    >
      <header className="flex items-center gap-2 px-3 py-3">
        <span className={clsx('h-2.5 w-2.5 rounded-full', DOT[status.color] ?? DOT.gray)} />
        <h3 className="text-sm font-semibold">{status.name}</h3>
        <span className={clsx('ml-auto rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset', statusStyle(status.color))}>{apps.length}</span>
      </header>
      <div className="flex-1 space-y-2 overflow-y-auto px-2 pb-2">
        {apps.map((a) => <DraggableCard key={a.id} app={a} onEdit={onEdit} />)}
        {apps.length === 0 && <p className="rounded-lg border border-dashed border-slate-300 px-3 py-6 text-center text-xs text-slate-400 dark:border-slate-700">Drop here</p>}
      </div>
    </section>
  )
}

function DraggableCard({ app, onEdit }: { app: Application; onEdit: (a: Application) => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: app.id })
  return (
    <div ref={setNodeRef} {...attributes} {...listeners} className={clsx('touch-manipulation outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded-xl', isDragging && 'opacity-30')}
      aria-label={`${app.company}${app.title ? `, ${app.title}` : ''}. Press space to pick up, arrow keys to move, space to drop.`}>
      <Card app={app} onEdit={onEdit} />
    </div>
  )
}

function Card({ app, onEdit, overlay }: { app: Application; onEdit?: (a: Application) => void; overlay?: boolean }) {
  const since = app.status_since ?? app.last_updated
  const days = daysBetween(since.slice(0, 10), todayIso())  // negative for future-dated (flagged) records
  return (
    <article className={clsx('group cursor-grab rounded-xl border border-slate-200 bg-white p-3 shadow-sm dark:border-slate-700 dark:bg-slate-800', overlay && 'rotate-2 cursor-grabbing shadow-xl')}>
      <div className="flex items-start gap-1">
        <GripVertical size={14} className="mt-0.5 shrink-0 text-slate-300 dark:text-slate-600" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{app.company}</p>
          <p className="truncate text-xs text-slate-500">{app.title ?? 'Role not set'}</p>
        </div>
        {onEdit && (
          <button
            className="rounded p-1 text-slate-400 opacity-0 hover:bg-slate-100 hover:text-slate-700 focus:opacity-100 group-hover:opacity-100 dark:hover:bg-slate-700"
            aria-label={`Edit ${app.company}`}
            onPointerDown={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
            onClick={() => onEdit(app)}
          >
            <Pencil size={13} />
          </button>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        {app.date_applied && <span>Applied {formatDate(app.date_applied)}</span>}
        {app.location && <span className="truncate">{app.location}</span>}
      </div>
      <div className="mt-2 flex items-center gap-2 text-xs">
        {days >= 0 && (
          <span className={clsx('rounded px-1.5 py-0.5', days >= 14 ? 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300' : 'bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-300')}>
            {days === 0 ? 'moved today' : `${days}d in stage`}
          </span>
        )}
        {app.flags.length > 0 && <span title={app.flags.map(describeFlag).join('\n')}><AlertTriangle size={13} className="text-amber-500" aria-label="Needs review" /></span>}
        {app.job_link && (
          <a href={app.job_link} target="_blank" rel="noreferrer" className="ml-auto text-indigo-600 hover:underline dark:text-indigo-400"
            onPointerDown={(e) => e.stopPropagation()} aria-label={`Open job listing for ${app.company}`}>
            <ExternalLink size={13} />
          </a>
        )}
      </div>
    </article>
  )
}

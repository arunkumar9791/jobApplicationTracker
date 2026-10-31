import { useMemo, useState } from 'react'
import { Check, Pencil, Plus, Search, Target, Trash2, Zap } from 'lucide-react'
import type { Application } from '../lib/api'
import { matchesSearch } from '../lib/filters'
import { todayIso } from '../lib/format'
import { useApplications, useCreateApplication, useDeleteApplications, useQuickUpdate, useStatusMap } from '../lib/hooks'
import { ApplicationForm } from '../components/ApplicationForm'

export function WishlistPage() {
  const { data: apps, isLoading } = useApplications()
  const statusOf = useStatusMap()
  const update = useQuickUpdate()
  const create = useCreateApplication()
  const remove = useDeleteApplications()
  const [query, setQuery] = useState('')
  const [newCompany, setNewCompany] = useState('')
  const [editing, setEditing] = useState<Application | null>(null)
  const [applied, setApplied] = useState<Application | null>(null)

  const wishlist = useMemo(() => apps
    .filter((a) => statusOf(a.status).kind === 'wishlist' && matchesSearch(a, query, ['company', 'notes', 'location']))
    .sort((a, b) => a.company.localeCompare(b.company, undefined, { sensitivity: 'base' })), [apps, statusOf, query])
  const total = useMemo(() => apps.filter((a) => statusOf(a.status).kind === 'wishlist').length, [apps, statusOf])
  const tracked = useMemo(() => new Set(apps.map((a) => a.company.trim().toLowerCase())), [apps])

  const markApplied = (a: Application) => {
    update.mutate(a.id, { status: 'Applied', date_applied: todayIso() })
    setApplied(a)
  }
  const add = (e: React.FormEvent) => {
    e.preventDefault()
    const name = newCompany.trim()
    if (!name) return
    create.mutate({ company: name, status: 'Wishlist' }, { onSuccess: () => setNewCompany('') })
  }
  const duplicate = newCompany.trim() && tracked.has(newCompany.trim().toLowerCase())

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-center gap-3 p-4">
        <Target className="text-amber-500" />
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold">Target companies <span className="font-normal text-slate-500">({total})</span></h2>
          <p className="text-xs text-slate-500">Companies you plan to apply to. "Mark applied" moves one into your applications, dated today.</p>
        </div>
        <label className="relative w-64 max-w-full">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input className="input pl-9" placeholder="Search companies…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search wishlist" />
        </label>
        <form onSubmit={add} className="flex items-center gap-2">
          <input className="input w-48" placeholder="Add a company" value={newCompany} onChange={(e) => setNewCompany(e.target.value)} aria-label="New wishlist company" />
          <button className="btn-primary" disabled={!newCompany.trim() || create.isPending}><Plus size={16} /> Add</button>
        </form>
      </div>
      {duplicate && <p className="text-xs text-amber-700 dark:text-amber-300">"{newCompany.trim()}" is already in your tracker – adding it again creates a duplicate.</p>}

      {applied && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg bg-emerald-50 px-4 py-2.5 text-sm text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-200" role="status">
          <Check size={16} /> <span><strong>{applied.company}</strong> marked as applied today.</span>
          <button className="font-medium underline" onClick={() => { setEditing(apps.find((a) => a.id === applied.id) ?? applied); setApplied(null) }}>Add role details</button>
          <button className="ml-auto text-xs opacity-70 hover:opacity-100" onClick={() => setApplied(null)}>Dismiss</button>
        </div>
      )}
      {(update.error || create.error || remove.error) && (
        <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">{(update.error ?? create.error ?? remove.error)?.message}</div>
      )}

      {isLoading ? <p className="py-12 text-center text-sm text-slate-500">Loading…</p> : wishlist.length === 0 ? (
        <div className="card px-6 py-16 text-center text-sm text-slate-500">{query ? 'No companies match.' : 'Your wishlist is empty. Add a company above.'}</div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-6">
          {wishlist.map((a) => (
            <article key={a.id} className="card flex flex-col p-4">
              <div className="flex items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-sm font-bold uppercase text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300">
                  {a.company.trim()[0]}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold" title={a.company}>{a.company}</p>
                  <p className="truncate text-xs text-slate-500">{a.notes?.split('\n')[0] || a.location || 'Wishlist lead'}</p>
                </div>
              </div>
              <div className="mt-4 flex items-center gap-1 border-t border-slate-100 pt-3 dark:border-slate-800">
                <button className="btn flex-1 justify-center bg-indigo-50 py-1.5 text-indigo-700 hover:bg-indigo-100 dark:bg-indigo-500/10 dark:text-indigo-300 dark:hover:bg-indigo-500/20" onClick={() => markApplied(a)}>
                  <Zap size={14} /> Mark applied
                </button>
                <button className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800" aria-label={`Edit ${a.company}`} onClick={() => setEditing(a)}><Pencil size={14} /></button>
                <button className="rounded p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10" aria-label={`Remove ${a.company}`}
                  onClick={() => confirm(`Remove ${a.company} from your wishlist?`) && remove.mutate([a.id])}><Trash2 size={14} /></button>
              </div>
            </article>
          ))}
        </div>
      )}

      {editing && <ApplicationForm app={editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

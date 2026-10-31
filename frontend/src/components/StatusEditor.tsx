import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowDown, ArrowUp, Lock, Plus, Trash2, X } from 'lucide-react'
import { api, type Settings, type StatusDef, type StatusKind } from '../lib/api'
import { statusStyle } from '../lib/format'

const KINDS: { value: StatusKind; label: string }[] = [
  { value: 'wishlist', label: 'Wishlist (not applied)' },
  { value: 'applied', label: 'Applied (awaiting reply)' },
  { value: 'interview', label: 'Interview stage' },
  { value: 'offer', label: 'Offer' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'closed', label: 'Closed (withdrawn, ghosted)' },
]
const COLORS = ['amber', 'blue', 'violet', 'green', 'red', 'gray']
const CORE = new Set(['Wishlist', 'Applied'])

type Row = StatusDef & { original?: string; key: number }

/** Edit the status pipeline: rename (records follow), reorder (funnel order), change kind/colour, add, remove. */
export function StatusEditor({ settings }: { settings: Settings }) {
  const qc = useQueryClient()
  const fresh = () => settings.statuses.map((s, i) => ({ ...s, original: s.name, key: i }))
  const [rows, setRows] = useState<Row[]>(fresh)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [saving, setSaving] = useState(false)

  const set = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const moveBy = (i: number, d: number) => setRows((rs) => {
    const next = [...rs]
    ;[next[i], next[i + d]] = [next[i + d], next[i]]
    return next
  })
  const names = rows.map((r) => r.name.trim())
  const invalid = names.some((n) => !n) || new Set(names).size !== names.length
  const dirty = JSON.stringify(rows.map(({ name, kind, color }) => ({ name, kind, color }))) !== JSON.stringify(settings.statuses)

  const save = async () => {
    setSaving(true)
    setMsg(null)
    try {
      const renames = Object.fromEntries(rows.filter((r) => r.original && r.original !== r.name.trim()).map((r) => [r.original!, r.name.trim()]))
      const s = await api.putStatuses(rows.map(({ name, kind, color }) => ({ name: name.trim(), kind, color })), renames)
      qc.setQueryData(['settings'], s)
      await qc.invalidateQueries({ queryKey: ['applications'] })
      await qc.invalidateQueries({ queryKey: ['dashboard'] })
      setRows(s.statuses.map((x, i) => ({ ...x, original: x.name, key: i })))
      setMsg({ ok: true, text: Object.keys(renames).length ? 'Saved. Renamed statuses were updated on every record and in the history.' : 'Saved.' })
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <p className="text-sm text-slate-500">
        Order sets the board columns and the funnel. <strong>Kind</strong> decides how a status counts in KPIs. Renaming updates existing records; a status still in use can't be removed.
      </p>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="w-20 py-2" /><th className="py-2 pr-3">Name</th><th className="py-2 pr-3">Kind</th><th className="py-2 pr-3">Colour</th><th className="w-10" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {rows.map((r, i) => {
              const core = !!r.original && CORE.has(r.original)
              return (
                <tr key={r.key}>
                  <td className="py-1.5">
                    <div className="flex">
                      <button className="rounded p-1 text-slate-400 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800" disabled={i === 0} onClick={() => moveBy(i, -1)} aria-label={`Move ${r.name} up`}><ArrowUp size={14} /></button>
                      <button className="rounded p-1 text-slate-400 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800" disabled={i === rows.length - 1} onClick={() => moveBy(i, 1)} aria-label={`Move ${r.name} down`}><ArrowDown size={14} /></button>
                    </div>
                  </td>
                  <td className="py-1.5 pr-3">
                    <div className="flex items-center gap-2">
                      <input className="input-sm" value={r.name} disabled={core} onChange={(e) => set(r.key, { name: e.target.value })} aria-label="Status name" />
                      {core && <span title="Core status: used for new records and imports"><Lock size={13} className="text-slate-400" /></span>}
                    </div>
                  </td>
                  <td className="py-1.5 pr-3">
                    <select className="input-sm" value={r.kind} disabled={core} onChange={(e) => set(r.key, { kind: e.target.value as StatusKind })} aria-label={`Kind of ${r.name}`}>
                      {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                    </select>
                  </td>
                  <td className="py-1.5 pr-3">
                    <div className="flex gap-1" role="radiogroup" aria-label={`Colour of ${r.name}`}>
                      {COLORS.map((c) => (
                        <button key={c} role="radio" aria-checked={r.color === c} aria-label={c} onClick={() => set(r.key, { color: c })}
                          className={clsx('h-6 w-6 rounded-md ring-1 ring-inset', statusStyle(c), r.color === c && 'outline outline-2 outline-offset-1 outline-indigo-500')} />
                      ))}
                    </div>
                  </td>
                  <td className="py-1.5">
                    {!core && <button className="rounded p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10" onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))} aria-label={`Remove ${r.name}`}><Trash2 size={14} /></button>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button className="btn-ghost ring-1 ring-inset ring-slate-200 dark:ring-slate-700" onClick={() => setRows((rs) => [...rs, { name: '', kind: 'interview', color: 'violet', key: Date.now() }])}>
          <Plus size={15} /> Add status
        </button>
        <button className="btn-primary" disabled={!dirty || invalid || saving} onClick={save}>{saving ? 'Saving…' : 'Save statuses'}</button>
        {dirty && <button className="btn-ghost" onClick={() => { setRows(fresh()); setMsg(null) }}><X size={15} /> Discard</button>}
        {invalid && <span className="text-xs text-red-600">Names must be filled in and unique.</span>}
        {msg && <span className={clsx('text-sm', msg.ok ? 'text-emerald-600' : 'text-red-600')}>{msg.text}</span>}
      </div>
    </div>
  )
}

/** Edit the Application Source dropdown list. */
export function SourceEditor({ settings }: { settings: Settings }) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const save = async (sources: string[]) => {
    try {
      setError(null)
      qc.setQueryData(['settings'], await api.putSettings({ sources }))
    } catch (e) {
      setError((e as Error).message)
    }
  }
  const add = (e: React.FormEvent) => {
    e.preventDefault()
    const v = draft.trim()
    if (!v || settings.sources.some((s) => s.toLowerCase() === v.toLowerCase())) return
    save([...settings.sources, v]).then(() => setDraft(''))
  }
  return (
    <div>
      <p className="text-sm text-slate-500">Suggested in the form and as the dropdown in the Excel export. Any other value can still be typed.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {settings.sources.map((s) => (
          <span key={s} className="inline-flex items-center gap-1 rounded-full bg-slate-100 py-1 pl-3 pr-1 text-sm dark:bg-slate-800">
            {s}
            <button className="rounded-full p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700 dark:hover:bg-slate-700" onClick={() => save(settings.sources.filter((x) => x !== s))} aria-label={`Remove ${s}`}><X size={13} /></button>
          </span>
        ))}
      </div>
      <form onSubmit={add} className="mt-3 flex gap-2">
        <input className="input max-w-xs" placeholder="Add a source" value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="New source" />
        <button className="btn-primary" disabled={!draft.trim()}><Plus size={15} /> Add</button>
      </form>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  )
}

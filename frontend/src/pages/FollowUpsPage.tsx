import { useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { CalendarCheck, CalendarClock, ChevronDown, Ghost, Hourglass, Mail, Pencil } from 'lucide-react'
import { api, type Application } from '../lib/api'
import { addDays, daysBetween, formatDate, todayIso } from '../lib/format'
import { useApplications, useQuickUpdate, useSettings, useStatusMap } from '../lib/hooks'
import { StatusBadge } from '../components/StatusBadge'
import { ApplicationForm } from '../components/ApplicationForm'

export function FollowUpsPage() {
  const { data: apps } = useApplications()
  const { data: settings } = useSettings()
  const statusOf = useStatusMap()
  const update = useQuickUpdate()
  const qc = useQueryClient()
  const [editing, setEditing] = useState<Application | null>(null)
  const today = todayIso()
  const staleDays = settings?.stale_days ?? 14

  // Same definitions as the dashboard KPIs: closed records (rejected / withdrawn / ghosted) never need a follow-up.
  const groups = useMemo(() => {
    const open = apps.filter((a) => !['rejected', 'closed'].includes(statusOf(a.status).kind))
    const withDate = open.filter((a) => a.next_follow_up).sort((a, b) => a.next_follow_up!.localeCompare(b.next_follow_up!))
    const weekEnd = addDays(today, 6)
    return {
      overdue: withDate.filter((a) => a.next_follow_up! < today),
      week: withDate.filter((a) => a.next_follow_up! >= today && a.next_follow_up! <= weekEnd),
      later: withDate.filter((a) => a.next_follow_up! > weekEnd),
      stale: open
        .filter((a) => statusOf(a.status).kind === 'applied' && daysBetween(a.last_updated.slice(0, 10), today) >= staleDays)
        .sort((a, b) => a.last_updated.localeCompare(b.last_updated)),
    }
  }, [apps, statusOf, today, staleDays])

  const setStale = async (n: number) => {
    if (!Number.isInteger(n) || n < 1) return
    qc.setQueryData(['settings'], await api.putSettings({ stale_days: n }))
  }
  const reschedule = (a: Application, date: string | null) => update.mutate(a.id, { next_follow_up: date })

  const followUpActions = (a: Application) => (
    <>
      <button className="btn-ghost py-1 text-xs ring-1 ring-inset ring-slate-200 dark:ring-slate-700" onClick={() => reschedule(a, addDays(today, 7))} title="Followed up – next reminder in a week">
        <CalendarCheck size={14} /> Done, +7 days
      </button>
      <input type="date" className="input-sm w-36" value={a.next_follow_up ?? ''} onChange={(e) => reschedule(a, e.target.value || null)} aria-label={`Follow-up date for ${a.company}`} />
      <button className="text-xs text-slate-500 hover:underline" onClick={() => reschedule(a, null)}>Clear</button>
    </>
  )

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-center gap-3 p-4">
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold">Follow-ups</h2>
          <p className="text-xs text-slate-500">Reminders from "Next follow-up date", plus applications that have gone quiet.</p>
        </div>
        <Chip tone="red">{groups.overdue.length} overdue</Chip>
        <Chip tone="indigo">{groups.week.length} due this week</Chip>
        <Chip tone="amber">{groups.stale.length} stale</Chip>
      </div>

      {update.error && <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">{update.error.message}</div>}

      <Section icon={CalendarClock} title="Overdue" tone="red" empty="Nothing overdue." items={groups.overdue}
        meta={(a) => <span className="font-medium text-red-600">{plural(daysBetween(a.next_follow_up!, today), 'day')} overdue · {formatDate(a.next_follow_up)}</span>}
        actions={followUpActions} onEdit={setEditing} />

      <Section icon={CalendarClock} title="Due this week" tone="indigo" empty="Nothing due in the next 7 days." items={groups.week}
        meta={(a) => <span>{a.next_follow_up === today ? 'Today' : `In ${plural(daysBetween(today, a.next_follow_up!), 'day')}`} · {formatDate(a.next_follow_up)}</span>}
        actions={followUpActions} onEdit={setEditing} />

      <Section
        icon={Hourglass}
        title="Stale applications"
        tone="amber"
        subtitle={
          <span className="inline-flex items-center gap-1.5">
            Applied with no update for
            <input type="number" min={1} className="input-sm w-16" defaultValue={staleDays} key={staleDays}
              onBlur={(e) => setStale(Number(e.target.value))} onKeyDown={(e) => e.key === 'Enter' && setStale(Number((e.target as HTMLInputElement).value))} aria-label="Stale after days" />
            days or more
          </span>
        }
        empty="No stale applications."
        items={groups.stale}
        meta={(a) => <span>Last update {plural(daysBetween(a.last_updated.slice(0, 10), today), 'day')} ago · applied {formatDate(a.date_applied) || '—'}</span>}
        actions={(a) => (
          <>
            <button className="btn-ghost py-1 text-xs ring-1 ring-inset ring-slate-200 dark:ring-slate-700" onClick={() => reschedule(a, today)}>
              <CalendarClock size={14} /> Follow up today
            </button>
            <button className="btn-ghost py-1 text-xs ring-1 ring-inset ring-slate-200 dark:ring-slate-700" onClick={() => update.mutate(a.id, { status: 'Ghosted' })} disabled={!settings?.statuses.some((s) => s.name === 'Ghosted')}>
              <Ghost size={14} /> Mark ghosted
            </button>
          </>
        )}
        onEdit={setEditing}
      />

      {groups.later.length > 0 && (
        <Section icon={CalendarClock} title="Scheduled later" tone="slate" empty="" items={groups.later} collapsed
          meta={(a) => <span>{formatDate(a.next_follow_up)}</span>} actions={followUpActions} onEdit={setEditing} />
      )}

      {editing && <ApplicationForm app={editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

const TONES = {
  red: 'bg-red-50 text-red-700 ring-red-200 dark:bg-red-500/10 dark:text-red-300 dark:ring-red-500/30',
  indigo: 'bg-indigo-50 text-indigo-700 ring-indigo-200 dark:bg-indigo-500/10 dark:text-indigo-300 dark:ring-indigo-500/30',
  amber: 'bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30',
  slate: 'bg-slate-100 text-slate-600 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700',
}

function Chip({ tone, children }: { tone: keyof typeof TONES; children: ReactNode }) {
  return <span className={clsx('rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset', TONES[tone])}>{children}</span>
}

function Section({ icon: Icon, title, subtitle, tone, empty, items, meta, actions, onEdit, collapsed }: {
  icon: typeof CalendarClock; title: string; subtitle?: ReactNode; tone: keyof typeof TONES; empty: string; items: Application[]
  meta: (a: Application) => ReactNode; actions: (a: Application) => ReactNode; onEdit: (a: Application) => void; collapsed?: boolean
}) {
  const [open, setOpen] = useState(!collapsed)
  return (
    <section className="card">
      <div className="flex flex-wrap items-center gap-3 px-5 py-4">
        <span className={clsx('flex h-8 w-8 items-center justify-center rounded-lg ring-1 ring-inset', TONES[tone])}><Icon size={16} /></span>
        <button className="flex items-center gap-2 font-semibold" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {title} <span className="text-sm font-normal text-slate-500">({items.length})</span>
          <ChevronDown size={16} className={clsx('text-slate-400 transition', open && 'rotate-180')} />
        </button>
        {subtitle && <span className="text-sm text-slate-500">{subtitle}</span>}
      </div>
      {open && (
        <div className="border-t border-slate-100 dark:border-slate-800">
          {items.length === 0 ? <p className="px-5 py-6 text-sm text-slate-500">{empty}</p> : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {items.map((a) => (
                <li key={a.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
                  <div className="min-w-48 flex-1">
                    <p className="font-medium">{a.company} <span className="font-normal text-slate-500">{a.title && `· ${a.title}`}</span></p>
                    <p className="text-xs text-slate-500">{meta(a)}</p>
                    {(a.contact_person || a.contact_info) && (
                      <p className="mt-0.5 flex items-center gap-1 text-xs text-slate-500">
                        <Mail size={12} /> {[a.contact_person, a.contact_info].filter(Boolean).join(' · ')}
                      </p>
                    )}
                  </div>
                  <StatusBadge status={a.status} />
                  <div className="flex flex-wrap items-center gap-2">
                    {actions(a)}
                    <button className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800" aria-label={`Edit ${a.company}`} onClick={() => onEdit(a)}>
                      <Pencil size={14} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

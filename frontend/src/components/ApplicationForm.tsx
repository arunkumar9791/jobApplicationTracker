import { useEffect, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, History, X } from 'lucide-react'
import { api, WORK_MODES, type Application, type ApplicationFields } from '../lib/api'
import { describeFlag, formatDateTime, todayIso } from '../lib/format'
import { useCreateApplication, useSettings, useUpdateApplication } from '../lib/hooks'
import { StatusBadge } from './StatusBadge'

type FormValues = Record<keyof ApplicationFields, string>

const FIELDS: (keyof ApplicationFields)[] = [
  'company', 'title', 'job_id', 'date_applied', 'source', 'job_link', 'location', 'work_mode',
  'status', 'next_follow_up', 'contact_person', 'contact_info', 'salary_range', 'notes',
]

function toForm(app?: Partial<Application>): FormValues {
  const v = {} as FormValues
  for (const f of FIELDS) v[f] = (app?.[f] as string | null | undefined) ?? ''
  if (!app?.status) v.status = 'Applied'
  if (!app?.id && !app?.date_applied && v.status !== 'Wishlist') v.date_applied = todayIso()
  return v
}

function validate(v: FormValues): { errors: Partial<FormValues>; warnings: string[] } {
  const errors: Partial<FormValues> = {}
  const warnings: string[] = []
  if (!v.company.trim()) errors.company = 'Company name is required'
  if (v.job_link.trim() && !/^https?:\/\/\S+$/i.test(v.job_link.trim())) errors.job_link = 'Must be a full URL starting with http:// or https://'
  if (v.contact_info.includes('@') && !v.contact_info.includes('linkedin') && !/^\S+@\S+\.\S+$/.test(v.contact_info.trim()))
    errors.contact_info = 'Looks like an invalid email address'
  const today = todayIso()
  if (v.date_applied && v.date_applied > today) warnings.push('Date applied is in the future')
  if (v.date_applied && v.next_follow_up && v.next_follow_up < v.date_applied) warnings.push('Follow-up date is before the applied date')
  if (v.status !== 'Wishlist' && !v.date_applied) warnings.push('No applied date set')
  return { errors, warnings }
}

interface Props {
  app?: Application
  initial?: Partial<ApplicationFields>
  onClose: () => void
}

export function ApplicationForm({ app, initial, onClose }: Props) {
  const { data: settings } = useSettings()
  const [values, setValues] = useState<FormValues>(() => toForm(app ?? initial))
  const [touched, setTouched] = useState(false)
  const create = useCreateApplication()
  const update = useUpdateApplication()
  const mutation = app ? update : create
  const { errors, warnings } = validate(values)
  const hasErrors = Object.keys(errors).length > 0

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const set = (field: keyof ApplicationFields) => (e: { target: { value: string } }) =>
    setValues((v) => ({ ...v, [field]: e.target.value }))

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setTouched(true)
    if (hasErrors) return
    const payload: Partial<ApplicationFields> = {}
    for (const f of FIELDS) {
      const val = values[f].trim() || null
      // On edit, send only changed fields so Last Updated and history reflect real changes.
      if (!app || val !== (app[f] ?? null)) (payload as Record<string, string | null>)[f] = val
    }
    if (app && Object.keys(payload).length === 0) return onClose()
    const onSuccess = () => onClose()
    if (app) update.mutate({ id: app.id, data: payload }, { onSuccess })
    else create.mutate(payload, { onSuccess })
  }

  const err = (f: keyof FormValues) => (touched || values[f] ? errors[f] : undefined)

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4 backdrop-blur-sm sm:p-8" onMouseDown={onClose}>
      <form
        onSubmit={submit}
        onMouseDown={(e) => e.stopPropagation()}
        className="card w-full max-w-3xl"
        aria-label={app ? 'Edit application' : 'Add application'}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <div>
            <h2 className="text-lg font-semibold">{app ? 'Edit application' : 'Add application'}</h2>
            {app && <p className="text-xs text-slate-500">Last updated {formatDateTime(app.last_updated)}</p>}
          </div>
          <button type="button" className="btn-ghost" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <div className="grid gap-4 px-6 py-5 sm:grid-cols-2">
          {app && app.flags.length > 0 && (
            <div className="flex gap-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-800 sm:col-span-2 dark:bg-amber-500/10 dark:text-amber-200">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <div>
                <p className="font-medium">Needs review</p>
                <ul className="list-disc pl-4">
                  {app.flags.map((f) => <li key={f}>{describeFlag(f)}</li>)}
                </ul>
                <p className="mt-1 text-xs">Editing the field clears its flag.</p>
              </div>
            </div>
          )}

          <Field label="Company name *" error={err('company')}>
            <input className="input" value={values.company} onChange={set('company')} autoFocus />
          </Field>
          <Field label="Job title / role">
            <input className="input" value={values.title} onChange={set('title')} />
          </Field>
          <Field label="Status">
            <select className="input" value={values.status} onChange={set('status')}>
              {settings?.statuses.map((s) => <option key={s.name}>{s.name}</option>)}
              {settings && !settings.statuses.some((s) => s.name === values.status) && <option>{values.status}</option>}
            </select>
          </Field>
          <Field label="Application source">
            <input className="input" list="source-options" value={values.source} onChange={set('source')} placeholder="Pick or type" />
            <datalist id="source-options">
              {settings?.sources.map((s) => <option key={s} value={s} />)}
            </datalist>
          </Field>
          <Field label="Date applied">
            <input type="date" className="input" value={values.date_applied} onChange={set('date_applied')} />
          </Field>
          <Field label="Next follow-up date">
            <input type="date" className="input" value={values.next_follow_up} onChange={set('next_follow_up')} />
          </Field>
          <Field label="Job ID">
            <input className="input font-mono" value={values.job_id} onChange={set('job_id')} />
          </Field>
          <Field label="Salary range">
            <input className="input" value={values.salary_range} onChange={set('salary_range')} />
          </Field>
          <Field label="Location">
            <input className="input" value={values.location} onChange={set('location')} />
          </Field>
          <Field label="Work mode">
            <select className="input" value={values.work_mode} onChange={set('work_mode')}>
              <option value="">Not specified</option>
              {WORK_MODES.map((m) => <option key={m}>{m}</option>)}
            </select>
          </Field>
          <Field label="Job link" error={err('job_link')} wide>
            <input className="input" type="url" value={values.job_link} onChange={set('job_link')} placeholder="https://" />
          </Field>
          <Field label="Contact person">
            <input className="input" value={values.contact_person} onChange={set('contact_person')} />
          </Field>
          <Field label="Contact email / LinkedIn" error={err('contact_info')}>
            <input className="input" value={values.contact_info} onChange={set('contact_info')} />
          </Field>
          <Field label="Notes" wide>
            <textarea className="input min-h-24" value={values.notes} onChange={set('notes')} />
          </Field>

          {warnings.length > 0 && (
            <ul className="space-y-1 text-xs text-amber-700 sm:col-span-2 dark:text-amber-300">
              {warnings.map((w) => <li key={w} className="flex items-center gap-1.5"><AlertTriangle size={12} />{w}</li>)}
            </ul>
          )}
          {app && <StatusTimeline id={app.id} />}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-6 py-4 dark:border-slate-800">
          {mutation.error && <p className="mr-auto text-sm text-red-600">{mutation.error.message}</p>}
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={mutation.isPending || (touched && hasErrors)}>
            {mutation.isPending ? 'Saving…' : app ? 'Save changes' : 'Add application'}
          </button>
        </div>
      </form>
    </div>
  )
}

function Field({ label, error, wide, children }: { label: string; error?: string; wide?: boolean; children: ReactNode }) {
  return (
    <label className={wide ? 'sm:col-span-2' : undefined}>
      <span className="label">{label}</span>
      {children}
      {error && <span className="mt-1 block text-xs text-red-600">{error}</span>}
    </label>
  )
}

function StatusTimeline({ id }: { id: number }) {
  const { data } = useQuery({ queryKey: ['history', id], queryFn: () => api.history(id) })
  if (!data?.length) return null
  return (
    <div className="sm:col-span-2">
      <p className="label flex items-center gap-1"><History size={12} /> Status history</p>
      <ol className="space-y-1.5 border-l border-slate-200 pl-4 dark:border-slate-700">
        {data.map((h) => (
          <li key={h.id} className="flex items-center gap-2 text-sm">
            <StatusBadge status={h.to_status} />
            <span className="text-xs text-slate-500">{formatDateTime(h.changed_at)}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

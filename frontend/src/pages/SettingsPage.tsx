import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Download, Upload } from 'lucide-react'
import { api } from '../lib/api'
import { useSettings } from '../lib/hooks'
import { SourceEditor, StatusEditor } from '../components/StatusEditor'

export function SettingsPage() {
  const { data: settings } = useSettings()
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [staleDays, setStaleDays] = useState<string>('')

  const restore = async (file: File) => {
    try {
      const data = JSON.parse(await file.text())
      if (!confirm(`Replace ALL current data with the backup "${file.name}"? This cannot be undone.`)) return
      const res = await api.restore(data)
      await qc.invalidateQueries()
      setMessage({ ok: true, text: `Restored ${res.applications} records and ${res.status_history} history entries.` })
    } catch (e) {
      setMessage({ ok: false, text: `Restore failed: ${(e as Error).message}` })
    }
  }

  const saveStale = async () => {
    const n = Number(staleDays)
    if (!Number.isInteger(n) || n < 1) return setMessage({ ok: false, text: 'Stale days must be a whole number above 0.' })
    const s = await api.putSettings({ stale_days: n })
    qc.setQueryData(['settings'], s)
    setStaleDays('')
    setMessage({ ok: true, text: `Applications are now considered stale after ${n} days.` })
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className="card p-6">
        <h2 className="text-base font-semibold">Backup & restore</h2>
        <p className="mt-1 text-sm text-slate-500">A full JSON snapshot: every record, its status history and these settings. The Excel workbook also re-imports without loss (Import → Replace all).</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <a className="btn-primary" href="/api/backup" download>
            <Download size={16} /> Download backup
          </a>
          <a className="btn-ghost ring-1 ring-inset ring-slate-200 dark:ring-slate-700" href="/api/export/xlsx" download>
            <Download size={16} /> Excel workbook
          </a>
          <button className="btn-ghost ring-1 ring-inset ring-slate-200 dark:ring-slate-700" onClick={() => fileRef.current?.click()}>
            <Upload size={16} /> Restore from file…
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) restore(f)
              e.target.value = ''
            }}
          />
        </div>
        {message && <p className={`mt-3 text-sm ${message.ok ? 'text-emerald-600' : 'text-red-600'}`}>{message.text}</p>}
      </section>

      <section className="card p-6">
        <h2 className="text-base font-semibold">Follow-ups</h2>
        <label className="mt-3 block max-w-xs">
          <span className="label">Mark "Applied" as stale after (days)</span>
          <div className="flex gap-2">
            <input className="input" type="number" min={1} placeholder={String(settings?.stale_days ?? 14)} value={staleDays} onChange={(e) => setStaleDays(e.target.value)} />
            <button className="btn-primary" disabled={!staleDays} onClick={saveStale}>Save</button>
          </div>
        </label>
      </section>

      <section className="card p-6 lg:col-span-2">
        <h2 className="text-base font-semibold">Status pipeline</h2>
        {settings && <StatusEditor settings={settings} />}
      </section>

      <section className="card p-6 lg:col-span-2">
        <h2 className="text-base font-semibold">Application sources</h2>
        {settings && <SourceEditor settings={settings} />}
      </section>
    </div>
  )
}

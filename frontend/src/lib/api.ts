export type StatusKind = 'wishlist' | 'applied' | 'interview' | 'offer' | 'rejected' | 'closed'

export interface StatusDef {
  name: string
  kind: StatusKind
  color: string
}

export interface Settings {
  statuses: StatusDef[]
  sources: string[]
  stale_days: number
}

export const WORK_MODES = ['Onsite', 'Hybrid', 'Remote'] as const

export interface ApplicationFields {
  company: string
  title: string | null
  job_id: string | null
  date_applied: string | null // YYYY-MM-DD
  source: string | null
  job_link: string | null
  location: string | null
  work_mode: string | null
  status: string
  next_follow_up: string | null
  contact_person: string | null
  contact_info: string | null
  salary_range: string | null
  notes: string | null
}

export interface Application extends ApplicationFields {
  id: number
  created_at: string
  last_updated: string
  flags: string[]
  /** When the current status was entered (latest history entry). */
  status_since: string | null
}

export interface HistoryEntry {
  id: number
  application_id: number
  from_status: string | null
  to_status: string
  changed_at: string
}

export interface UploadResult {
  token: string
  filename: string
  sheets: { name: string; rows: number }[]
}

export interface ImportOptions {
  token: string
  sheet?: string | null
  header_row?: number | null
  mapping?: Record<string, string | null> | null
  mode: 'replace' | 'merge'
  /** null = server defaults (approve all / merge all; for this app's own exports: change nothing). */
  declined: string[] | null
  keep_duplicates: string[] | null
  date_fixes: Record<string, string>
}

export type RowAction = 'add' | 'update' | 'unchanged' | 'skip' | 'merged'

export interface ImportAnalysis {
  sheets: string[]
  sheet: string
  header_row: number
  mode: 'replace' | 'merge'
  headers: { index: number; text: string; field: string | null; samples: string[] }[]
  mapping: Record<string, string | null>
  fields: { key: string; label: string }[]
  suggestions: { key: string; field: string; source: string; target: string; count: number; reason: 'alias' | 'case' | 'typo'; approved: boolean }[]
  duplicates: { id: string; kind: 'same_job' | 'wishlist'; label: string; rows: number[]; keep: boolean }[]
  issues: { row: number; company: string | null; field: string | null; level: 'error' | 'warning'; message: string; fix: { type: 'date'; value: string; label: string } | null }[]
  rows: {
    row: number; action: RowAction; note: string | null; company: string | null; title: string | null; job_id: string | null
    date_applied: string | null; status: string | null; source: string | null; location: string | null; flags: string[]; changes: string[]
  }[]
  counts: Record<'rows' | 'blank' | 'applications' | 'wishlist' | 'companies' | 'add' | 'update' | 'unchanged' | 'skipped' | 'flagged' | 'errors' | 'warnings' | 'existing', number>
}

export interface ImportSummary {
  added: number
  updated: number
  unchanged: number
  skipped: number
  flagged: number
}

export interface Dashboard {
  kpis: {
    applications: number; applications_this_week: number; applications_this_month: number; companies: number; wishlist: number
    active: number; awaiting_response: number; interviews: number; offers: number; rejections: number; responded: number
    response_rate: number | null; interview_rate: number | null; offer_rate: number | null; avg_days_to_response: number | null
    follow_ups_overdue: number; follow_ups_due_this_week: number; future_dated: number; undated: number
  }
  weekly: { week: string; applications: number; responded: number }[]
  funnel: { status: string; count: number }[]
  by_status: { status: string; kind: StatusKind; count: number }[]
  by_source: { source: string; applications: number; responded: number; response_rate: number | null }[]
  by_location: { location: string; applications: number }[]
  by_work_mode: { work_mode: string; applications: number }[]
  options: { sources: string[]; locations: string[] }
}

export interface DashboardFilters {
  start?: string
  end?: string
  source?: string
  location?: string
}

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: typeof init?.body === 'string' ? { 'Content-Type': 'application/json' } : undefined,
  })
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail))
        message = body.detail.map((d: { loc: string[]; msg: string }) => `${d.loc.at(-1)}: ${d.msg.replace(/^Value error, /, '')}`).join('; ')
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(message)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) })

export const api = {
  listApplications: () => request<Application[]>('/applications'),
  createApplication: (data: Partial<ApplicationFields>) => request<Application>('/applications', json('POST', data)),
  updateApplication: (id: number, data: Partial<ApplicationFields> & { flags?: string[] }) =>
    request<Application>(`/applications/${id}`, json('PATCH', data)),
  deleteApplication: (id: number) => request<void>(`/applications/${id}`, { method: 'DELETE' }),
  history: (id: number) => request<HistoryEntry[]>(`/applications/${id}/history`),
  bulkStatus: (ids: number[], status: string) => request<{ changed: number }>('/applications/bulk/status', json('POST', { ids, status })),
  bulkDelete: (ids: number[]) => request<{ deleted: number }>('/applications/bulk/delete', json('POST', { ids })),
  dashboard: (f: DashboardFilters) => {
    const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v) as [string, string][])
    return request<Dashboard>(`/dashboard${q.size ? `?${q}` : ''}`)
  },
  getSettings: () => request<Settings>('/settings'),
  putSettings: (data: Partial<Omit<Settings, 'statuses'>>) => request<Settings>('/settings', json('PUT', data)),
  putStatuses: (statuses: StatusDef[], renames: Record<string, string>) => request<Settings>('/settings/statuses', json('PUT', { statuses, renames })),
  importUpload: (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<UploadResult>('/import/upload', { method: 'POST', body })
  },
  importAnalyze: (opts: ImportOptions) => request<ImportAnalysis>('/import/analyze', json('POST', opts)),
  importCommit: (opts: ImportOptions) => request<ImportSummary>('/import/commit', json('POST', opts)),
  /** Download the filtered table (in on-screen order) as CSV or a plain .xlsx. */
  exportView: async (ids: number[], fields: string[], format: 'csv' | 'xlsx') => {
    const res = await fetch('/api/export/view', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids, fields, format }) })
    if (!res.ok) throw new ApiError(`Export failed (${res.status})`)
    const name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '')?.[1] ?? `applications.${format}`
    const url = URL.createObjectURL(await res.blob())
    const a = Object.assign(document.createElement('a'), { href: url, download: name })
    a.click()
    URL.revokeObjectURL(url)
  },
  restore: (data: unknown) => request<{ applications: number; status_history: number }>('/restore', json('POST', data)),
}

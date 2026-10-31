import { daysBetween, todayIso } from './format'

export const DATE_PRESETS = {
  week: 'Last 7 days',
  month: 'Last 30 days',
  overdue: 'Overdue (before today)',
  upcoming: 'Next 7 days',
  future: 'In the future',
  missing: 'Not set',
} as const

export type DatePreset = keyof typeof DATE_PRESETS

export function matchDatePreset(value: string | null, preset: DatePreset, today = todayIso()): boolean {
  if (preset === 'missing') return !value
  if (!value) return false
  const diff = daysBetween(today, value) // >0 means after today
  switch (preset) {
    case 'week': return diff <= 0 && diff > -7
    case 'month': return diff <= 0 && diff > -30
    case 'overdue': return diff < 0
    case 'upcoming': return diff >= 0 && diff <= 7
    case 'future': return diff > 0
  }
}

/** Case-insensitive search across the given fields. */
export function matchesSearch(record: object, query: string, fields: readonly string[]): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  const r = record as Record<string, unknown>
  return fields.some((f) => String(r[f] ?? '').toLowerCase().includes(q))
}

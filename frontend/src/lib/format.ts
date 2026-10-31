const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** '2026-10-22' -> '22 Oct 2026'. Parsed by hand so the browser's timezone can't shift the day. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  if (!y || !m || !d) return iso
  return `${d} ${MONTHS[m - 1]} ${y}`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const time = iso.slice(11, 16)
  return time && time !== '00:00' ? `${formatDate(iso)}, ${time}` : formatDate(iso)
}

/** Today as YYYY-MM-DD in local time. */
export function todayIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** ISO date plus n calendar days. */
export function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10)
}

export function daysBetween(fromIso: string, toIso: string): number {
  const ms = Date.UTC(...ymd(toIso)) - Date.UTC(...ymd(fromIso))
  return Math.round(ms / 86_400_000)
}

function ymd(iso: string): [number, number, number] {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return [y, m - 1, d]
}

const FLAG_TEXT: Record<string, string> = {
  future: 'is in the future',
  old: 'is more than a year old',
  missing: 'is missing',
}

const FIELD_TEXT: Record<string, string> = {
  date_applied: 'Date applied',
  next_follow_up: 'Follow-up date',
  last_updated: 'Last updated',
}

/** 'date_applied:future' -> 'Date applied is in the future' */
export function describeFlag(flag: string): string {
  const [field, reason] = flag.split(':')
  return `${FIELD_TEXT[field] ?? field} ${FLAG_TEXT[reason] ?? reason}`
}

/** Tailwind classes per status colour. Listed in full so Tailwind's scanner picks them up. */
export const STATUS_STYLES: Record<string, string> = {
  amber: 'bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30',
  blue: 'bg-blue-50 text-blue-700 ring-blue-200 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-500/30',
  violet: 'bg-violet-50 text-violet-700 ring-violet-200 dark:bg-violet-500/10 dark:text-violet-300 dark:ring-violet-500/30',
  green: 'bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/30',
  red: 'bg-red-50 text-red-700 ring-red-200 dark:bg-red-500/10 dark:text-red-300 dark:ring-red-500/30',
  gray: 'bg-slate-100 text-slate-600 ring-slate-200 dark:bg-slate-500/10 dark:text-slate-300 dark:ring-slate-500/30',
}

export const statusStyle = (color: string) => STATUS_STYLES[color] ?? STATUS_STYLES.gray

import clsx from 'clsx'
import { statusStyle } from '../lib/format'
import { useSettings, useStatusMap } from '../lib/hooks'

export function StatusBadge({ status }: { status: string }) {
  const def = useStatusMap()(status)
  return (
    <span className={clsx('inline-flex rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset', statusStyle(def.color))}>
      {status}
    </span>
  )
}

/** A select styled as a status badge, for changing status in place. */
export function StatusSelect({ value, onChange, disabled }: { value: string; onChange: (s: string) => void; disabled?: boolean }) {
  const { data } = useSettings()
  const def = useStatusMap()(value)
  const names = data?.statuses.map((s) => s.name) ?? []
  return (
    <select
      aria-label="Status"
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      className={clsx(
        'w-full cursor-pointer rounded-md py-1 pl-2 pr-6 text-xs font-semibold ring-1 ring-inset outline-none focus:ring-2',
        statusStyle(def.color),
      )}
    >
      {names.map((n) => <option key={n}>{n}</option>)}
      {!names.includes(value) && <option>{value}</option>}
    </select>
  )
}

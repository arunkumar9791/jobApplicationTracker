import { useEffect, useId, useRef, useState } from 'react'
import clsx from 'clsx'

type Kind = 'text' | 'date' | 'select'

interface Props {
  value: string | null
  kind?: Kind
  options?: readonly string[]
  /** Suggestions for free-text fields (rendered as a datalist). */
  suggestions?: readonly string[]
  display?: React.ReactNode
  onSave: (value: string | null) => void
  className?: string
}

/** Shows a value; double-click (or Enter when focused) to edit. Enter/blur saves, Escape cancels. */
export function EditableCell({ value, kind = 'text', options, suggestions, display, onSave, className }: Props) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value ?? '')
  const ref = useRef<HTMLInputElement & HTMLSelectElement>(null)
  const listId = useId()

  useEffect(() => {
    if (editing) {
      ref.current?.focus()
      if (kind === 'text') ref.current?.select()
    }
  }, [editing, kind])

  const start = () => {
    setDraft(value ?? '')
    setEditing(true)
  }
  const commit = (next = draft) => {
    setEditing(false)
    const cleaned = next.trim() || null
    if (cleaned !== (value ?? null)) onSave(cleaned)
  }
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') commit()
    if (e.key === 'Escape') setEditing(false)
  }

  if (editing) {
    if (kind === 'select')
      return (
        <select ref={ref} className="input-sm" value={draft} onChange={(e) => commit(e.target.value)} onBlur={() => setEditing(false)} onKeyDown={onKeyDown}>
          <option value="">—</option>
          {options?.map((o) => <option key={o}>{o}</option>)}
        </select>
      )
    return (
      <>
        <input
          ref={ref}
          type={kind === 'date' ? 'date' : 'text'}
          className="input-sm"
          value={draft}
          list={suggestions ? listId : undefined}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => commit()}
          onKeyDown={onKeyDown}
        />
        {suggestions && (
          <datalist id={listId}>
            {suggestions.map((s) => <option key={s} value={s} />)}
          </datalist>
        )}
      </>
    )
  }

  return (
    <div
      tabIndex={0}
      title="Double-click to edit"
      onDoubleClick={start}
      onKeyDown={(e) => e.key === 'Enter' && start()}
      className={clsx('min-h-6 w-full cursor-text truncate rounded px-1 py-0.5 outline-none hover:bg-slate-100 focus:ring-2 focus:ring-indigo-500/40 dark:hover:bg-slate-800', className)}
    >
      {display ?? (value || <span className="text-slate-300 dark:text-slate-600">—</span>)}
    </div>
  )
}

import { useMemo, useState } from 'react'
import { BrowserRouter, Navigate, NavLink, Route, Routes } from 'react-router'
import clsx from 'clsx'
import { BarChart3, Briefcase, CalendarClock, Columns3, Layers, Moon, Plus, Settings, Sun, Target, Upload } from 'lucide-react'
import { useApplications, useStatusMap } from './lib/hooks'
import { addDays, todayIso } from './lib/format'
import { ApplicationsPage } from './pages/ApplicationsPage'
import { SettingsPage } from './pages/SettingsPage'
import { ImportPage } from './pages/ImportPage'
import { DashboardPage } from './pages/DashboardPage'
import { PipelinePage } from './pages/PipelinePage'
import { FollowUpsPage } from './pages/FollowUpsPage'
import { WishlistPage } from './pages/WishlistPage'
import { ApplicationForm } from './components/ApplicationForm'

const NAV = [
  { to: '/dashboard', label: 'Dashboard', icon: BarChart3 },
  { to: '/pipeline', label: 'Pipeline', icon: Columns3 },
  { to: '/applications', label: 'Applications', icon: Layers },
  { to: '/follow-ups', label: 'Follow-ups', icon: CalendarClock },
  { to: '/wishlist', label: 'Wishlist', icon: Target },
  { to: '/import', label: 'Import', icon: Upload },
  { to: '/settings', label: 'Settings', icon: Settings },
]

function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  const toggle = () => {
    const next = !dark
    document.documentElement.classList.toggle('dark', next)
    try {
      localStorage.setItem('theme', next ? 'dark' : 'light')
    } catch {
      /* storage unavailable */
    }
    setDark(next)
  }
  return { dark, toggle }
}

function Header() {
  const { data } = useApplications()
  const statusOf = useStatusMap()
  const { dark, toggle } = useTheme()
  const [adding, setAdding] = useState(false)

  const stats = useMemo(() => {
    const apps = data.filter((a) => statusOf(a.status).kind !== 'wishlist')
    const weekEndIso = addDays(todayIso(), 6)
    const followUps = data.filter((a) => a.next_follow_up && a.next_follow_up <= weekEndIso && !['rejected', 'closed'].includes(statusOf(a.status).kind)).length
    return { apps: apps.length, companies: new Set(apps.map((a) => a.company.toLowerCase())).size, wishlist: data.length - apps.length, followUps }
  }, [data, statusOf])

  return (
    <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <div className="mx-auto flex max-w-[1600px] items-center gap-3 px-4 py-4 sm:gap-4 sm:px-6">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-md shadow-indigo-600/30">
          <Briefcase size={22} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-bold tracking-tight sm:text-xl">Job Application Tracker</h1>
            <span className="whitespace-nowrap rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-semibold text-indigo-700 ring-1 ring-inset ring-indigo-200 dark:bg-indigo-500/10 dark:text-indigo-300 dark:ring-indigo-500/30">
              {stats.apps} Applications ({stats.companies} Companies)
            </span>
            <span className="whitespace-nowrap rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {stats.wishlist} Target Leads
            </span>
          </div>
        </div>
        <button className="btn-ghost" onClick={toggle} aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}>
          {dark ? <Sun size={18} /> : <Moon size={18} />}
        </button>
        <button className="btn-primary shrink-0" onClick={() => setAdding(true)} aria-label="Add Application">
          <Plus size={16} /> <span className="hidden sm:inline">Add Application</span>
        </button>
      </div>
      <nav className="mx-auto flex max-w-[1600px] gap-1 overflow-x-auto px-4 sm:px-6">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              clsx(
                'mb-2 inline-flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium',
                isActive ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800',
              )
            }
          >
            <Icon size={16} /> {label}
            {to === '/follow-ups' && stats.followUps > 0 && (
              <span className="rounded-full bg-red-500 px-1.5 text-[11px] font-semibold text-white" aria-label={`${stats.followUps} due`}>{stats.followUps}</span>
            )}
          </NavLink>
        ))}
      </nav>
      {adding && <ApplicationForm onClose={() => setAdding(false)} />}
    </header>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Header />
      <main className="mx-auto max-w-[1600px] px-4 py-6 sm:px-6">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/applications" element={<ApplicationsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/pipeline" element={<PipelinePage />} />
          <Route path="/follow-ups" element={<FollowUpsPage />} />
          <Route path="/wishlist" element={<WishlistPage />} />
          <Route path="*" element={<Navigate to="/applications" replace />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}

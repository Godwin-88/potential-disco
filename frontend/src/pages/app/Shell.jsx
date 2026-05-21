import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { healthCheck } from '../../api/scraper'

const NAV = [
  { to: '/app/qa',         icon: '💬', label: 'Q&A Assistant' },
  { to: '/app/compliance', icon: '🛡', label: 'Compliance Checker' },
  { to: '/app/predictor',  icon: '⚖', label: 'Ruling Predictor' },
]

const PAGE_TITLES = {
  '/app/qa':         'Q&A Assistant',
  '/app/compliance': 'Compliance Checker',
  '/app/predictor':  'Ruling Predictor',
  '/app/graph':      'Knowledge Graph',
}

function usePageTitle() {
  const path = window.location.pathname
  for (const [k, v] of Object.entries(PAGE_TITLES)) {
    if (path.startsWith(k)) return v
  }
  return 'Lex Kenya'
}

export default function Shell() {
  const { user, signOut } = useAuth()
  const navigate          = useNavigate()
  const [kgOnline, setKgOnline]   = useState(null)
  const [mobileOpen, setMobileOpen] = useState(false)
  const pageTitle = usePageTitle()

  useEffect(() => {
    healthCheck()
      .then(d => setKgOnline(d.status === 'ok'))
      .catch(() => setKgOnline(false))
  }, [])

  async function handleLogout() {
    await signOut()
    navigate('/login')
  }

  const displayName = user?.user_metadata?.full_name || user?.email?.split('@')[0] || 'User'

  const SidebarContent = () => (
    <>
      {/* Logo */}
      <div className="px-5 py-5 border-b border-slate-800">
        <div className="text-white font-bold text-base tracking-tight">Lex Kenya</div>
        <div className="text-emerald-400 text-xs mt-0.5">Legal Intelligence Platform</div>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-3 space-y-0.5">
        <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest px-3 py-2">Research</div>
        {NAV.map(n => (
          <NavLink key={n.to} to={n.to}
            onClick={() => setMobileOpen(false)}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors
               ${isActive
                 ? 'bg-emerald-900/40 text-emerald-400'
                 : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}`
            }>
            <span>{n.icon}</span>
            {n.label}
          </NavLink>
        ))}

        <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest px-3 py-2 mt-3">System</div>
        <NavLink to="/app/graph"
          onClick={() => setMobileOpen(false)}
          className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors
             ${isActive
               ? 'bg-emerald-900/40 text-emerald-400'
               : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}`
          }>
          <span>🗂</span>
          Knowledge Graph
        </NavLink>
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-slate-800 space-y-3">
        <div className="flex items-center gap-2 text-xs">
          <span className={`w-2 h-2 rounded-full ${kgOnline === null ? 'bg-slate-500' : kgOnline ? 'bg-emerald-400' : 'bg-red-400'}`} />
          <span className="text-slate-400">{kgOnline === null ? 'Checking…' : kgOnline ? 'KG Online' : 'KG Offline'}</span>
        </div>
        <div className="flex items-center justify-between">
          <div className="text-xs text-slate-400 truncate max-w-[140px]" title={user?.email}>{displayName}</div>
          <button onClick={handleLogout}
            className="text-xs text-slate-500 hover:text-red-400 transition-colors">
            Logout
          </button>
        </div>
      </div>
    </>
  )

  return (
    <div className="flex h-screen bg-slate-50">

      {/* ── Desktop sidebar ── */}
      <aside className="hidden md:flex w-60 bg-slate-900 flex-col shrink-0">
        <SidebarContent />
      </aside>

      {/* ── Mobile sidebar overlay ── */}
      {mobileOpen && (
        <div className="md:hidden fixed inset-0 z-40 flex">
          <div className="absolute inset-0 bg-black/50" onClick={() => setMobileOpen(false)} />
          <aside className="relative w-60 bg-slate-900 flex flex-col h-full shadow-2xl">
            <SidebarContent />
          </aside>
        </div>
      )}

      {/* ── Main ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Topbar */}
        <header className="bg-white border-b border-slate-200 h-14 flex items-center px-4 shrink-0 gap-3">
          <button className="md:hidden text-slate-500 hover:text-slate-800 text-xl"
            onClick={() => setMobileOpen(true)}>☰</button>
          <span className="font-semibold text-slate-800 text-sm">{pageTitle}</span>
          <div className="ml-auto flex items-center gap-3">
            <span className="text-xs text-slate-400 hidden sm:block">{user?.email}</span>
            <div className="w-8 h-8 bg-emerald-100 text-emerald-700 rounded-full flex items-center justify-center font-semibold text-sm">
              {displayName[0]?.toUpperCase()}
            </div>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>

    </div>
  )
}

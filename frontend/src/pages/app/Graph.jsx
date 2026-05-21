import { useEffect, useRef, useState } from 'react'
import { graphStats, runScraper, scraperCourts, scraperHistory, scraperStatus } from '../../api/scraper'
import LiveLog from '../../components/LiveLog'
import { useToast } from '../../components/Toast'

const COURT_KEYS = {
  kesc:   'Supreme Court',
  keca:   'Court of Appeal',
  kehc:   'High Court',
  keelrc: 'Employment & Labour Relations',
  keelc:  'Environment & Land',
}

function CourtCard({ name, count }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4 space-y-1 text-center hover:border-emerald-200 transition-colors">
      <div className="text-2xl font-bold text-slate-800">{count ?? '—'}</div>
      <div className="text-xs text-slate-500">{name}</div>
      <div className="text-xs text-slate-400">cases</div>
    </div>
  )
}

function RelBar({ label, count, max }) {
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="w-36 text-slate-600 font-mono shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
        <div className="h-full bg-emerald-500 rounded-full transition-all duration-500"
          style={{ width: max ? `${(count / max) * 100}%` : '0%' }} />
      </div>
      <span className="w-12 text-right text-slate-500">{count?.toLocaleString()}</span>
    </div>
  )
}

export default function Graph() {
  const toast = useToast()
  const [tab, setTab]             = useState('scraper')
  const [courts, setCourts]       = useState({})
  const [history, setHistory]     = useState([])
  const [stats, setStats]         = useState(null)
  const [runCourt, setRunCourt]   = useState('')
  const [maxCases, setMaxCases]   = useState(200)
  const [maxPages, setMaxPages]   = useState(10)
  const [running, setRunning]     = useState(false)
  const [logLines, setLogLines]   = useState([])
  const pollRef = useRef(null)

  useEffect(() => {
    scraperCourts().then(setCourts).catch(() => {})
    scraperHistory().then(setHistory).catch(() => {})
    graphStats().then(setStats).catch(() => {})
    // Check if already running
    scraperStatus().then(d => { if (d.status === 'running') startPolling() }).catch(() => {})
  }, [])

  function startPolling() {
    setRunning(true)
    pollRef.current = setInterval(async () => {
      try {
        const d = await scraperStatus()
        setLogLines(d.log || [])
        if (d.status !== 'running') {
          clearInterval(pollRef.current)
          setRunning(false)
          scraperCourts().then(setCourts)
          scraperHistory().then(setHistory)
          toast(d.status === 'complete' ? 'Scrape complete.' : 'Scrape ended.', d.status === 'complete' ? 'success' : 'warning')
        }
      } catch {
        clearInterval(pollRef.current)
        setRunning(false)
      }
    }, 3000)
  }

  async function handleRun() {
    try {
      await runScraper({ court: runCourt || undefined, max_cases: maxCases, max_pages: maxPages })
      setLogLines([])
      startPolling()
    } catch (e) {
      if (e.response?.status === 409) {
        toast('A scrape is already running.', 'warning')
      } else {
        toast(e.response?.data?.detail || 'Could not start scrape.', 'error')
      }
    }
  }

  // Stats helpers
  const nodeList = stats?.nodes || []
  const relList  = (stats?.relationships || []).slice(0, 20)
  const maxRel   = relList[0]?.count || 1

  const nodeMap = {}
  nodeList.forEach(n => {
    if (n.labels) Object.assign(nodeMap, n.labels)
    else if (n.label) nodeMap[n.label] = n.count
  })
  const totalNodes = Object.values(nodeMap).reduce((a, b) => a + (b || 0), 0)

  const courtCounts = Object.entries(COURT_KEYS).map(([key, name]) => ({
    name, count: courts[key] ?? courts[name] ?? null,
  }))

  return (
    <div className="p-4 md:p-6 h-full overflow-y-auto scrollbar-thin">
      <div className="max-w-4xl mx-auto space-y-5">

        <div>
          <h1 className="text-lg font-semibold text-slate-800">Knowledge Graph</h1>
          <p className="text-sm text-slate-500 mt-0.5">Manage graph data and monitor system state.</p>
        </div>

        {/* Sub-tabs */}
        <div className="flex gap-1 bg-slate-100 rounded-xl p-1 w-fit">
          {['scraper', 'stats'].map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors
                ${tab === t ? 'bg-white shadow-sm text-slate-800' : 'text-slate-500 hover:text-slate-700'}`}>
              {t === 'scraper' ? '🕷 Scraper' : '📊 Stats'}
            </button>
          ))}
        </div>

        {/* ── SCRAPER TAB ── */}
        {tab === 'scraper' && (
          <div className="space-y-4">
            {/* Court coverage */}
            <div className="bg-white border border-slate-200 rounded-2xl p-5">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-4">Court coverage</div>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                {courtCounts.map(c => <CourtCard key={c.name} name={c.name} count={c.count} />)}
              </div>
            </div>

            {/* Run scraper */}
            <div className="bg-white border border-slate-200 rounded-2xl p-5 space-y-4">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest">Run scraper</div>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">Court filter</label>
                  <select value={runCourt} onChange={e => setRunCourt(e.target.value)}
                    className="w-full text-sm rounded-lg border-slate-300 focus:border-emerald-500 focus:ring-emerald-500">
                    <option value="">All courts</option>
                    {Object.entries(COURT_KEYS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">Max cases</label>
                  <input type="number" value={maxCases} onChange={e => setMaxCases(Number(e.target.value))}
                    min={1} max={1000}
                    className="w-full text-sm rounded-lg border-slate-300 focus:border-emerald-500 focus:ring-emerald-500" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">Max pages</label>
                  <input type="number" value={maxPages} onChange={e => setMaxPages(Number(e.target.value))}
                    min={1} max={50}
                    className="w-full text-sm rounded-lg border-slate-300 focus:border-emerald-500 focus:ring-emerald-500" />
                </div>
              </div>
              <button onClick={handleRun} disabled={running}
                className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 text-white font-semibold px-5 py-2.5 rounded-lg text-sm transition-colors flex items-center gap-2">
                {running
                  ? <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Running…</>
                  : '▶ Start scrape'}
              </button>
            </div>

            {/* Live log */}
            <div className="bg-white border border-slate-200 rounded-2xl p-5 space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest">Live log</div>
                {running && (
                  <div className="flex items-center gap-1.5 text-xs text-emerald-600 font-medium">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" /> Running
                  </div>
                )}
              </div>
              <LiveLog lines={logLines} running={running} />
            </div>

            {/* History */}
            {history.length > 0 && (
              <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden">
                <div className="px-5 py-3 border-b border-slate-100">
                  <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest">History</div>
                </div>
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-xs text-slate-500">
                    <tr>
                      {['Date', 'Cases added', 'Duration', 'Status'].map(h => (
                        <th key={h} className="text-left px-5 py-2.5 font-semibold uppercase tracking-wide">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {history.map((h, i) => (
                      <tr key={i} className="hover:bg-slate-50">
                        <td className="px-5 py-3 text-slate-600">{h.date || h.started_at || '—'}</td>
                        <td className="px-5 py-3 font-medium text-slate-800">{h.cases_added ?? '—'}</td>
                        <td className="px-5 py-3 text-slate-500">{h.duration || '—'}</td>
                        <td className="px-5 py-3">
                          <span className={`text-xs px-2 py-0.5 rounded-full font-medium
                            ${h.status === 'complete' ? 'bg-emerald-50 text-emerald-700'
                              : h.status === 'error' ? 'bg-red-50 text-red-700'
                              : 'bg-amber-50 text-amber-700'}`}>
                            {h.status === 'complete' ? '✓ Complete' : h.status === 'error' ? '✕ Error' : '⚠ ' + (h.status || 'Unknown')}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ── STATS TAB ── */}
        {tab === 'stats' && (
          <div className="space-y-4">
            {/* Node counts */}
            <div className="bg-white border border-slate-200 rounded-2xl p-5 space-y-4">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest">Node counts</div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(nodeMap).map(([label, count]) => (
                  <div key={label} className="bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-center min-w-[90px]">
                    <div className="text-lg font-bold text-slate-800">{(count || 0).toLocaleString()}</div>
                    <div className="text-xs text-slate-500">{label}</div>
                  </div>
                ))}
              </div>
              {totalNodes > 0 && (
                <div className="text-sm text-slate-500 border-t border-slate-100 pt-3">
                  Total: <span className="font-semibold text-slate-700">{totalNodes.toLocaleString()} nodes</span>
                </div>
              )}
            </div>

            {/* Relationship counts */}
            {relList.length > 0 && (
              <div className="bg-white border border-slate-200 rounded-2xl p-5 space-y-3">
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest">Relationships (top 20)</div>
                <div className="space-y-2">
                  {relList.map((r, i) => (
                    <RelBar key={i} label={r.rel || r.type} count={r.count} max={maxRel} />
                  ))}
                </div>
              </div>
            )}

            {/* System */}
            <div className="bg-white border border-slate-200 rounded-2xl p-5 space-y-3">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest">System</div>
              <div className="space-y-2 text-sm">
                {[
                  ['Neo4j', stats ? '● Online' : '● Checking…', stats ? 'text-emerald-600' : 'text-slate-400'],
                  ['Embedding', 'local · BAAI/bge-m3 · 1024 dim', 'text-slate-600'],
                  ['LLM', 'openai_compatible · qwen/qwen3-32b', 'text-slate-600'],
                  ['Vector index', 'legal_embeddings · cosine', 'text-slate-600'],
                ].map(([k, v, cls]) => (
                  <div key={k} className="flex items-center gap-3">
                    <span className="w-28 text-slate-400 text-xs shrink-0">{k}</span>
                    <span className={`text-xs font-medium ${cls}`}>{v}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

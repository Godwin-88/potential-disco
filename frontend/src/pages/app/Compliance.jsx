import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { checkCompliance } from '../../api/compliance'
import RiskBadge from '../../components/RiskBadge'
import { useToast } from '../../components/Toast'

const ACTION_TYPES = [
  'Director conflict of interest / related-party transaction',
  'Share buyback by private company',
  'Foreign investor acquiring stake (>25%)',
  'Employee share option scheme (ESOP)',
  'Dividend declaration without distributable profits',
  'Director removal or resignation',
  'Cross-border capital transfer',
  'Change of company name or objects',
  'Voluntary winding up',
]

const COMPANY_TYPES = [
  '', 'Private limited company', 'Public limited company',
  'Sole proprietorship', 'Partnership', 'NGO / Company limited by guarantee',
]

const HISTORY_KEY = 'lk_compliance_history'

function loadHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]') }
  catch { return [] }
}

function saveHistory(entry) {
  const hist = [entry, ...loadHistory()].slice(0, 5)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(hist))
}

function parseObligations(text) {
  if (!text) return []
  const lines = text.split('\n').filter(l => l.match(/^[-•*\d]/))
  return lines.length ? lines.map(l => l.replace(/^[-•*\d.]\s*/, '')) : []
}

export default function Compliance() {
  const toast    = useToast()
  const navigate = useNavigate()

  const [actionType, setActionType]   = useState(ACTION_TYPES[0])
  const [description, setDescription] = useState('')
  const [companyType, setCompanyType] = useState('')
  const [loading, setLoading]         = useState(false)
  const [result, setResult]           = useState(null)
  const [history, setHistory]         = useState(loadHistory)

  async function runCheck() {
    if (!description.trim()) { toast('Please describe the action.', 'warning'); return }
    setLoading(true)
    setResult(null)
    try {
      const data = await checkCompliance(actionType, description, companyType)
      setResult(data)
      const entry = { actionType, risk: data.risk_level || 'medium', ts: new Date().toLocaleString() }
      saveHistory(entry)
      setHistory(loadHistory())
    } catch (e) {
      toast(e.response?.data?.detail || 'Compliance check failed.', 'error')
    } finally {
      setLoading(false)
    }
  }

  function askQA() {
    navigate(`/app/qa?q=${encodeURIComponent(`Legal obligations for: ${actionType} — ${description}`)}`)
  }

  const obligations = result ? parseObligations(result.obligations || result.answer || '') : []
  const riskLevel   = result?.risk_level?.toLowerCase() || 'medium'

  return (
    <div className="p-4 md:p-6 h-full">
      <div className="max-w-6xl mx-auto h-full flex flex-col gap-4 lg:flex-row">

        {/* ── Form (left) ── */}
        <div className="lg:w-96 shrink-0 space-y-4">
          <div>
            <h1 className="text-lg font-semibold text-slate-800">Compliance Checker</h1>
            <p className="text-sm text-slate-500 mt-0.5">Assess any corporate action against Kenyan law.</p>
          </div>

          <div className="bg-white border border-slate-200 rounded-2xl p-5 space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1.5">Action type</label>
              <select value={actionType} onChange={e => setActionType(e.target.value)}
                className="w-full text-sm rounded-lg border-slate-300 focus:border-emerald-500 focus:ring-emerald-500">
                {ACTION_TYPES.map(t => <option key={t}>{t}</option>)}
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1.5">Describe the specific action</label>
              <textarea value={description} onChange={e => setDescription(e.target.value)}
                rows={4} placeholder="e.g. ABC Ltd wishes to appoint its CEO's spouse as sole IT supplier at Ksh 8M/year without a board resolution…"
                className="w-full text-sm rounded-lg border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 resize-none" />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1.5">Entity type <span className="font-normal text-slate-400">(optional)</span></label>
              <select value={companyType} onChange={e => setCompanyType(e.target.value)}
                className="w-full text-sm rounded-lg border-slate-300 focus:border-emerald-500 focus:ring-emerald-500">
                <option value="">Select entity type…</option>
                {COMPANY_TYPES.filter(Boolean).map(t => <option key={t}>{t}</option>)}
              </select>
            </div>

            <button onClick={runCheck} disabled={loading}
              className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 text-white font-semibold py-2.5 rounded-lg text-sm transition-colors flex items-center justify-center gap-2">
              {loading ? (<><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Checking…</>) : '▶ Run compliance check'}
            </button>
          </div>

          {/* Recent checks */}
          {history.length > 0 && (
            <div className="bg-white border border-slate-200 rounded-2xl p-4">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-3">Recent checks</div>
              {history.map((h, i) => (
                <div key={i} className="flex items-center justify-between py-2 border-b border-slate-100 last:border-0 gap-2">
                  <span className="text-xs text-slate-600 truncate flex-1">{h.actionType.split('/')[0].trim()}</span>
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full shrink-0
                    ${h.risk === 'high' ? 'bg-red-50 text-red-700'
                      : h.risk === 'medium' ? 'bg-amber-50 text-amber-700'
                      : 'bg-emerald-50 text-emerald-700'}`}>
                    {h.risk}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── Result (right) ── */}
        <div className="flex-1 min-w-0">
          {!result && !loading && (
            <div className="h-full flex items-center justify-center">
              <div className="text-center space-y-2 text-slate-400">
                <div className="text-4xl">🛡</div>
                <p className="text-sm">Fill in the form and run a compliance check.<br />Results will appear here.</p>
              </div>
            </div>
          )}

          {loading && (
            <div className="h-full flex items-center justify-center">
              <div className="text-center space-y-3">
                <div className="w-10 h-10 border-2 border-emerald-200 border-t-emerald-600 rounded-full animate-spin mx-auto" />
                <p className="text-sm text-slate-500">Analysing against the knowledge graph…</p>
              </div>
            </div>
          )}

          {result && !loading && (
            <div className="bg-white border border-slate-200 rounded-2xl p-6 space-y-5 h-full overflow-y-auto scrollbar-thin">
              <RiskBadge level={riskLevel} />

              {/* Summary */}
              {result.answer && (
                <div>
                  <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-2">Summary</div>
                  <p className="text-sm text-slate-700 leading-relaxed">{result.answer}</p>
                </div>
              )}

              {/* Obligations */}
              {obligations.length > 0 && (
                <div>
                  <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-2">Obligations</div>
                  <ul className="space-y-1.5">
                    {obligations.map((o, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-slate-700">
                        <input type="checkbox" className="mt-0.5 accent-emerald-600 shrink-0" />
                        <span>{o}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Sources */}
              {result.sources?.length > 0 && (
                <div>
                  <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-2">Sources</div>
                  <div className="flex flex-wrap gap-1.5">
                    {result.sources.map((s, i) => (
                      <span key={i} className={`text-xs px-2 py-1 rounded-lg border font-medium
                        ${s.label === 'Case' ? 'bg-violet-50 text-violet-800 border-violet-200'
                          : s.label === 'Article' ? 'bg-blue-50 text-blue-800 border-blue-200'
                          : 'bg-emerald-50 text-emerald-800 border-emerald-200'}`}>
                        {s.citation_tag || s.title}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <button onClick={askQA}
                className="flex items-center gap-2 text-sm text-emerald-600 hover:text-emerald-700 font-medium border border-emerald-200 hover:border-emerald-300 px-4 py-2 rounded-lg transition-colors">
                ↗ Ask Q&A about this
              </button>

              <p className="text-xs text-slate-400 border-t border-slate-100 pt-4">
                AI-assisted analysis — not legal advice. Consult a qualified Kenyan advocate.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

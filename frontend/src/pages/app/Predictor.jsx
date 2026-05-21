import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { predictOutcome } from '../../api/predictor'
import OutcomeBar from '../../components/OutcomeBar'
import SlideOver from '../../components/SlideOver'
import { useToast } from '../../components/Toast'

const COURTS = [
  'Supreme Court', 'Court of Appeal',
  'High Court (Commercial Division)', 'High Court (General)',
  'Environment & Land Court', 'Employment & Labour Relations Court',
]

const DISPUTE_TYPES = [
  'Shareholder oppression', 'Director fiduciary breach', 'Wrongful dismissal',
  'Unfair termination', 'Commercial contract breach', 'Land title dispute',
  'Insolvency / winding up', 'Regulatory enforcement (CMA)', 'Constitutional petition', 'Defamation',
]

const CLAIMANT_TYPES = [
  'Minority shareholder', 'Employee', 'Creditor',
  'Regulator (CMA/CBK)', 'Landowner', 'Business partner', 'Consumer',
]

const REMEDIES = [
  'Damages', 'Injunction', 'Winding up', 'Share buyout order',
  'Reinstatement', 'Declaration', 'Specific performance',
]

function parseOutcomes(result) {
  if (result.outcome_distribution) return result.outcome_distribution
  // Heuristic: extract percentages from answer text
  const text = result.analysis || result.answer || ''
  const matches = [...text.matchAll(/(\d+)%[^,\n]*(succeeds?|dismissed|partial)/gi)]
  if (matches.length) {
    return matches.map(m => ({ label: m[0].replace(/\d+%\s*/,'').slice(0,30), percent: parseInt(m[1]) }))
  }
  return []
}

function parsePrecedents(result) {
  return result.precedents || result.sources || []
}

export default function Predictor() {
  const toast    = useToast()
  const navigate = useNavigate()

  const [court, setCourt]             = useState(COURTS[0])
  const [disputeType, setDisputeType] = useState(DISPUTE_TYPES[0])
  const [claimant, setClaimant]       = useState(CLAIMANT_TYPES[0])
  const [remedy, setRemedy]           = useState(REMEDIES[0])
  const [facts, setFacts]             = useState('')
  const [loading, setLoading]         = useState(false)
  const [result, setResult]           = useState(null)
  const [caseDetail, setCaseDetail]   = useState(null)
  const [sortCol, setSortCol]         = useState('year')
  const [sortAsc, setSortAsc]         = useState(false)
  const [showAll, setShowAll]         = useState(false)

  async function predict() {
    setLoading(true)
    setResult(null)
    try {
      const data = await predictOutcome(court, disputeType, claimant, remedy, facts)
      setResult(data)
    } catch (e) {
      toast(e.response?.data?.detail || 'Prediction failed.', 'error')
    } finally {
      setLoading(false)
    }
  }

  function toggleSort(col) {
    if (sortCol === col) setSortAsc(a => !a)
    else { setSortCol(col); setSortAsc(false) }
  }

  const precedents = result ? parsePrecedents(result) : []
  const outcomes   = result ? parseOutcomes(result) : []

  const sorted = [...precedents].sort((a, b) => {
    const va = a[sortCol] ?? ''
    const vb = b[sortCol] ?? ''
    return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va))
  })

  const visible = showAll ? sorted : sorted.slice(0, 5)

  return (
    <div className="p-4 md:p-6 space-y-6 overflow-y-auto h-full scrollbar-thin">
      <div className="max-w-4xl mx-auto space-y-6">

        <div>
          <h1 className="text-lg font-semibold text-slate-800">Ruling Predictor</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Profile a dispute to see how similar cases have been decided in Kenyan courts.
          </p>
        </div>

        {/* ── Case profile form ── */}
        <div className="bg-white border border-slate-200 rounded-2xl p-5 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            {[
              ['Court', court, setCourt, COURTS],
              ['Dispute type', disputeType, setDisputeType, DISPUTE_TYPES],
              ['Claimant type', claimant, setClaimant, CLAIMANT_TYPES],
              ['Remedy sought', remedy, setRemedy, REMEDIES],
            ].map(([label, val, setter, opts]) => (
              <div key={label}>
                <label className="block text-xs font-semibold text-slate-600 mb-1.5">{label}</label>
                <select value={val} onChange={e => setter(e.target.value)}
                  className="w-full text-sm rounded-lg border-slate-300 focus:border-emerald-500 focus:ring-emerald-500">
                  {opts.map(o => <option key={o}>{o}</option>)}
                </select>
              </div>
            ))}
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1.5">
              Additional facts <span className="font-normal text-slate-400">(optional)</span>
            </label>
            <textarea value={facts} onChange={e => setFacts(e.target.value)}
              rows={3} placeholder="Describe the key facts of the dispute…"
              className="w-full text-sm rounded-lg border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 resize-none" />
          </div>

          <button onClick={predict} disabled={loading}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 text-white font-semibold px-6 py-2.5 rounded-lg text-sm transition-colors flex items-center gap-2">
            {loading ? (<><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Predicting…</>) : '▶ Predict likely outcome'}
          </button>
        </div>

        {/* ── Results ── */}
        {result && (
          <>
            {/* Outcome bars */}
            <div className="bg-white border border-slate-200 rounded-2xl p-5 space-y-4">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest">Outcome distribution</div>

              {outcomes.length > 0 ? (
                <div className="space-y-3">
                  {outcomes.map((o, i) => (
                    <OutcomeBar key={i} label={o.label} percent={o.percent ?? o.pct ?? 0} />
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-500">No structured outcome data — see analysis below.</p>
              )}

              {precedents.length > 0 && (
                <p className="text-xs text-slate-400">
                  Based on {precedents.length} comparable precedents in the knowledge graph.
                </p>
              )}

              {(result.analysis || result.answer) && (
                <div className="border-t border-slate-100 pt-4">
                  <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-2">Analysis</div>
                  <p className="text-sm text-slate-700 leading-relaxed">{result.analysis || result.answer}</p>
                </div>
              )}
            </div>

            {/* Precedent table */}
            {precedents.length > 0 && (
              <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden">
                <div className="px-5 py-3 border-b border-slate-200">
                  <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest">
                    Relevant precedents from graph
                  </div>
                </div>

                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-xs text-slate-500">
                    <tr>
                      {['Case', 'court', 'year', 'outcome'].map(col => (
                        <th key={col} onClick={() => col !== 'Case' && toggleSort(col)}
                          className={`text-left px-5 py-2.5 font-semibold uppercase tracking-wide
                            ${col !== 'Case' ? 'cursor-pointer hover:text-slate-700' : ''}`}>
                          {col === 'Case' ? 'Case' : col.charAt(0).toUpperCase() + col.slice(1)}
                          {sortCol === col && <span className="ml-1">{sortAsc ? '↑' : '↓'}</span>}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {visible.map((p, i) => (
                      <tr key={i}
                        onClick={() => setCaseDetail(p)}
                        className="hover:bg-emerald-50 cursor-pointer transition-colors">
                        <td className="px-5 py-3 font-medium text-slate-800">{p.title || p.citation_tag || `Case ${i + 1}`}</td>
                        <td className="px-5 py-3 text-slate-500">{p.court || '—'}</td>
                        <td className="px-5 py-3 text-slate-500">{p.year || '—'}</td>
                        <td className="px-5 py-3">
                          <span className={`text-xs px-2 py-0.5 rounded-full font-medium
                            ${(p.outcome || '').toLowerCase().includes('success') || (p.outcome || '').toLowerCase().includes('granted')
                              ? 'bg-emerald-50 text-emerald-700'
                              : (p.outcome || '').toLowerCase().includes('partial')
                              ? 'bg-amber-50 text-amber-700'
                              : 'bg-slate-100 text-slate-600'}`}>
                            {p.outcome || '—'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {precedents.length > 5 && (
                  <div className="px-5 py-3 border-t border-slate-100">
                    <button onClick={() => setShowAll(s => !s)}
                      className="text-sm text-emerald-600 hover:text-emerald-700 font-medium">
                      {showAll ? 'Show less ↑' : `Show ${precedents.length - 5} more ↓`}
                    </button>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* Case detail slide-over */}
      <SlideOver open={!!caseDetail} onClose={() => setCaseDetail(null)} title="Case detail">
        {caseDetail && (
          <div className="space-y-4 text-sm">
            <div>
              <h3 className="font-semibold text-slate-800">{caseDetail.title || caseDetail.citation_tag}</h3>
              {caseDetail.citation && (
                <p className="font-mono text-xs bg-slate-50 border px-2 py-1 rounded mt-1">{caseDetail.citation}</p>
              )}
            </div>
            <div className="flex gap-4 text-slate-500">
              {caseDetail.court && <span>🏛 {caseDetail.court}</span>}
              {caseDetail.year  && <span>📅 {caseDetail.year}</span>}
            </div>
            {caseDetail.outcome && (
              <div>
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-1">Outcome</div>
                <p className="text-slate-700">{caseDetail.outcome}</p>
              </div>
            )}
            {(caseDetail.summary || caseDetail.headnote) && (
              <div>
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-1">Summary</div>
                <p className="text-slate-600 leading-relaxed">{caseDetail.summary || caseDetail.headnote}</p>
              </div>
            )}
            <button
              onClick={() => { navigate(`/app/qa?q=${encodeURIComponent(`Tell me about ${caseDetail.title || caseDetail.citation}`)}`) }}
              className="flex items-center gap-2 text-sm text-emerald-600 hover:text-emerald-700 font-medium border border-emerald-200 px-4 py-2 rounded-lg transition-colors">
              ↗ Ask Q&A about this case
            </button>
          </div>
        )}
      </SlideOver>
    </div>
  )
}

import { useRef, useState } from 'react'
import { askQuestion, suggestQuestions, traceAnswer } from '../../api/qa'
import { parseAnswer } from '../../components/CitationChip'
import CitationGraph from '../../components/CitationGraph'
import SlideOver from '../../components/SlideOver'
import { useToast } from '../../components/Toast'

function TypingIndicator() {
  return (
    <div className="flex gap-3 items-start msg-enter">
      <div className="w-8 h-8 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center font-bold text-xs shrink-0">LK</div>
      <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-sm px-4 py-3">
        <div className="dot-pulse flex gap-1"><span /><span /><span /></div>
      </div>
    </div>
  )
}

function Message({ msg, onViewGraph }) {
  const [showStats, setShowStats] = useState(false)
  const isUser = msg.role === 'user'

  return (
    <div className={`flex gap-3 items-start msg-enter ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-xs shrink-0
        ${isUser ? 'bg-blue-100 text-blue-700' : 'bg-emerald-100 text-emerald-700'}`}>
        {isUser ? 'U' : 'LK'}
      </div>

      <div className={`max-w-[85%] space-y-2 ${isUser ? 'items-end' : 'items-start'} flex flex-col`}>
        <div className={`px-4 py-3 rounded-2xl text-sm leading-relaxed
          ${isUser
            ? 'bg-blue-600 text-white rounded-tr-sm'
            : 'bg-white border border-slate-200 text-slate-700 rounded-tl-sm'}`}>
          {isUser
            ? msg.content
            : <p className="whitespace-pre-wrap">{parseAnswer(msg.content, msg.sources)}</p>
          }
        </div>

        {/* Answer footer */}
        {!isUser && msg.answerId && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            {msg.consensusLevel && (
              <span className={`px-2 py-0.5 rounded-full border font-medium
                ${msg.consensusLevel === 'high' ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                  : msg.consensusLevel === 'medium' ? 'bg-amber-50 text-amber-700 border-amber-200'
                  : 'bg-red-50 text-red-700 border-red-200'}`}>
                Consensus: {msg.consensusLevel}
              </span>
            )}
            <button onClick={() => onViewGraph(msg.answerId)}
              className="text-slate-400 hover:text-slate-600 underline underline-offset-2">
              View citation graph
            </button>
            {msg.retrieval_stats && (
              <button onClick={() => setShowStats(s => !s)}
                className="text-slate-400 hover:text-slate-600 underline underline-offset-2">
                {showStats ? 'Hide' : 'Show'} retrieval details
              </button>
            )}
          </div>
        )}

        {/* Retrieval stats accordion */}
        {!isUser && showStats && msg.retrieval_stats && (
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-600 space-y-1 w-full">
            {Object.entries(msg.retrieval_stats).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span className="text-slate-400">{k.replace(/_/g, ' ')}</span>
                <span className="font-medium">{String(v)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function QA() {
  const toast = useToast()
  const [messages, setMessages]       = useState([{
    role: 'assistant', content: 'Hello. I can answer questions about Kenyan constitutional law, corporate acts, and case law from all five major courts. What would you like to know?',
  }])
  const [input, setInput]             = useState('')
  const [maxCitations, setMaxCitations] = useState(8)
  const [loading, setLoading]         = useState(false)
  const [suggestions, setSuggestions] = useState([])
  const [graphOpen, setGraphOpen]     = useState(false)
  const [graphData, setGraphData]     = useState({ nodes: [], edges: [] })
  const [sources, setSources]         = useState([])
  const bottomRef = useRef(null)

  function scrollBottom() {
    setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
  }

  async function send(question) {
    const q = (question || input).trim()
    if (!q || loading) return
    setInput('')
    setMessages(m => [...m, { role: 'user', content: q }])
    setLoading(true)
    setSuggestions([])
    scrollBottom()

    try {
      const [result] = await Promise.all([
        askQuestion(q, maxCitations),
        suggestQuestions(q).then(d => setSuggestions(d.suggestions || [])).catch(() => {}),
      ])

      const aiMsg = {
        role: 'assistant',
        content: result.answer,
        sources: result.sources || [],
        answerId: result.answer_id,
        consensusLevel: result.consensus_level,
        retrieval_stats: result.retrieval_stats,
      }
      setMessages(m => [...m, aiMsg])
      setSources(result.sources || [])
    } catch (e) {
      toast(e.response?.data?.detail || 'Request failed. Please try again.', 'error')
      setMessages(m => [...m, { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' }])
    } finally {
      setLoading(false)
      scrollBottom()
    }
  }

  async function viewGraph(answerId) {
    try {
      const data = await traceAnswer(answerId)
      setGraphData({ nodes: data.graph_nodes || [], edges: data.graph_edges || [] })
      setGraphOpen(true)
    } catch {
      toast('Could not load citation graph.', 'error')
    }
  }

  const lastSources = sources

  return (
    <div className="h-full flex">

      {/* ── Chat (left 60%) ── */}
      <div className="flex-1 flex flex-col min-w-0 p-4">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto space-y-4 scrollbar-thin pr-1 pb-4">
          {messages.map((m, i) => (
            <Message key={i} msg={m} onViewGraph={viewGraph} />
          ))}
          {loading && <TypingIndicator />}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="border-t border-slate-200 pt-3 space-y-2 bg-slate-50">
          <div className="flex gap-2">
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
              placeholder="Ask about Kenyan law…"
              className="flex-1 rounded-xl border-slate-300 text-sm focus:border-emerald-500 focus:ring-emerald-500 bg-white"
              disabled={loading}
            />
            <select value={maxCitations} onChange={e => setMaxCitations(Number(e.target.value))}
              className="text-xs rounded-xl border-slate-300 bg-white text-slate-600 focus:border-emerald-500 focus:ring-emerald-500 pr-6">
              {[4, 6, 8, 10, 12].map(n => <option key={n} value={n}>{n} sources</option>)}
            </select>
            <button onClick={() => send()} disabled={loading || !input.trim()}
              className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white px-4 py-2 rounded-xl text-sm font-medium transition-colors">
              Send
            </button>
          </div>
        </div>
      </div>

      {/* ── Source panel (right 40%) ── */}
      <div className="hidden lg:flex w-72 xl:w-80 flex-col border-l border-slate-200 bg-white p-4 space-y-4 overflow-y-auto scrollbar-thin shrink-0">

        {/* Sources */}
        <div>
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-2">
            Sources {lastSources.length > 0 && `(${lastSources.length})`}
          </div>
          {lastSources.length === 0 ? (
            <p className="text-slate-400 text-xs">Sources will appear here after your first question.</p>
          ) : lastSources.map((s, i) => (
            <div key={i} className="border border-slate-200 rounded-xl p-3 mb-2 space-y-1.5 hover:border-emerald-200 transition-colors">
              <div className="flex items-start justify-between gap-2">
                <span className={`text-xs px-1.5 py-0.5 rounded font-medium
                  ${s.label === 'Case' ? 'bg-violet-50 text-violet-700'
                    : s.label === 'Article' ? 'bg-blue-50 text-blue-700'
                    : 'bg-emerald-50 text-emerald-700'}`}>
                  {s.label}
                </span>
                {s.overruled_by && <span className="text-xs text-amber-600">⚠ overruled</span>}
              </div>
              <p className="text-xs font-medium text-slate-700 leading-tight">{s.title}</p>
              {s.act && <p className="text-xs text-slate-400">{s.act}</p>}
              {s.citation && <p className="text-xs font-mono text-slate-500">{s.citation}</p>}
              <div className="space-y-1">
                {[['Authority', s.authority_score], ['Relevance', s.relevance_score]].map(([lbl, val]) => (
                  <div key={lbl} className="flex items-center gap-2">
                    <span className="text-xs text-slate-400 w-14">{lbl}</span>
                    <div className="flex-1 h-1 bg-slate-100 rounded-full overflow-hidden">
                      <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${Math.round((val || 0) * 100)}%` }} />
                    </div>
                    <span className="text-xs text-slate-500 w-8 text-right">{val?.toFixed(2) ?? '—'}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Follow-up suggestions */}
        {suggestions.length > 0 && (
          <div>
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-2">Follow-ups</div>
            {suggestions.map((s, i) => (
              <button key={i} onClick={() => send(s)}
                className="w-full text-left text-xs text-slate-600 hover:text-emerald-700 border border-slate-200 hover:border-emerald-200 rounded-lg px-3 py-2 mb-1.5 transition-colors">
                ▸ {s}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Citation graph slide-over */}
      <SlideOver open={graphOpen} onClose={() => setGraphOpen(false)} title="Citation graph">
        <CitationGraph nodes={graphData.nodes} edges={graphData.edges} />
      </SlideOver>
    </div>
  )
}

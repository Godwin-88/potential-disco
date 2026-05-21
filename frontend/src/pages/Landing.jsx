import { Link } from 'react-router-dom'

const COURTS = [
  'Supreme Court', 'Court of Appeal', 'High Court',
  'Environment & Land Court', 'Employment & Labour Relations Court',
]

const PROBLEMS = [
  {
    problem: 'Legal research in Kenya is slow — manually searching through Acts, judgments, and regulations takes hours.',
    solution: 'Ask in plain English. Get a cited answer in seconds, traced to the exact section or judgment in our knowledge graph.',
    icon: '💬',
  },
  {
    problem: 'Compliance risk is invisible until a dispute. Directors rarely know which sections impose personal liability.',
    solution: 'The Compliance Checker maps any corporate action to applicable Acts, risk level, and specific legal obligations.',
    icon: '🛡',
  },
  {
    problem: 'Junior advocates assess precedent manually — reading dozens of judgments to find analogous fact patterns.',
    solution: 'The Ruling Predictor surfaces structurally similar cases from the graph and shows historical outcome distribution.',
    icon: '⚖',
  },
]

const STATS = [
  { value: '5,500+', label: 'Legal nodes' },
  { value: '19',     label: 'Corporate Acts' },
  { value: '997+',   label: 'Judgments' },
  { value: '5',      label: 'Courts' },
]

const MODULES = [
  {
    id: 'qa',
    title: 'Q&A Assistant',
    desc: 'Ask any question about Kenyan corporate law. The GraphRAG pipeline retrieves semantically similar sections and cases, expands the citation graph, and generates an answer grounded in real legal sources.',
    badge: 'Most popular',
    demo: {
      q: 'Can a director vote on a matter where they have a personal interest?',
      a: 'Under the Companies Act 2015, a director who has a direct or indirect interest in a contract or proposed contract must declare that interest at a board meeting. The director may not vote on the matter — failure to disclose constitutes a breach of fiduciary duty.',
      chips: ['§ 142', '§ 143', '⚖ Oluoch v Nairobi Finance 2021'],
    },
  },
  {
    id: 'compliance',
    title: 'Compliance Checker',
    desc: 'Describe a corporate action and get a structured risk assessment — applicable Acts and sections, risk classification, specific obligations, and director exposure.',
    badge: 'For in-house counsel',
    demo: {
      action: 'Director appointing spouse as sole supplier without board approval',
      risk: 'high',
      items: ['Board approval required under § 142', 'Director must declare interest', 'Shareholder disclosure within 30 days'],
    },
  },
  {
    id: 'predictor',
    title: 'Ruling Predictor',
    desc: 'Profile a dispute by court, type, and claimant. The graph surfaces historically similar cases and shows how courts have ruled — outcome distribution grounded in real precedents.',
    badge: 'For litigation teams',
    demo: {
      profile: 'Court of Appeal · Shareholder oppression · Minority shareholder',
      outcomes: [{ label: 'Claimant succeeds', pct: 68 }, { label: 'Partial remedy', pct: 22 }, { label: 'Dismissed', pct: 10 }],
    },
  },
]

function ModuleDemo({ module }) {
  if (module.id === 'qa') {
    return (
      <div className="bg-slate-50 rounded-xl p-4 space-y-3 text-sm">
        <div className="flex gap-2">
          <div className="w-7 h-7 rounded-full bg-slate-200 flex items-center justify-center text-xs font-bold shrink-0">U</div>
          <div className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-slate-700">{module.demo.q}</div>
        </div>
        <div className="flex gap-2">
          <div className="w-7 h-7 rounded-full bg-emerald-100 flex items-center justify-center text-xs font-bold text-emerald-700 shrink-0">LK</div>
          <div className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-slate-700 space-y-2">
            <p>{module.demo.a}</p>
            <div className="flex flex-wrap gap-1">
              {module.demo.chips.map(c => (
                <span key={c} className={`text-xs px-1.5 py-0.5 rounded border font-medium
                  ${c.startsWith('⚖') ? 'bg-violet-50 text-violet-800 border-violet-200' : 'bg-emerald-50 text-emerald-800 border-emerald-200'}`}>
                  {c}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (module.id === 'compliance') {
    const riskColours = { high: 'bg-red-50 border-red-300 text-red-800', medium: 'bg-amber-50 border-amber-200 text-amber-800', low: 'bg-emerald-50 border-emerald-200 text-emerald-800' }
    return (
      <div className="bg-slate-50 rounded-xl p-4 space-y-3 text-sm">
        <div className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-slate-600 text-xs">{module.demo.action}</div>
        <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border font-semibold text-sm ${riskColours[module.demo.risk]}`}>
          <span>●</span> High compliance risk
        </div>
        <ul className="space-y-1">
          {module.demo.items.map(item => (
            <li key={item} className="flex items-start gap-2 text-slate-600 text-xs">
              <span className="text-emerald-500 mt-0.5">✓</span> {item}
            </li>
          ))}
        </ul>
      </div>
    )
  }

  if (module.id === 'predictor') {
    return (
      <div className="bg-slate-50 rounded-xl p-4 space-y-3 text-sm">
        <div className="text-xs text-slate-500 bg-white border border-slate-200 rounded px-2 py-1">{module.demo.profile}</div>
        <div className="space-y-2">
          {module.demo.outcomes.map(o => (
            <div key={o.label} className="flex items-center gap-3 text-xs">
              <span className="w-32 text-slate-600">{o.label}</span>
              <div className="flex-1 h-2 bg-slate-200 rounded-full">
                <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${o.pct}%` }} />
              </div>
              <span className="font-bold text-slate-700">{o.pct}%</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return null
}

export default function Landing() {
  return (
    <div className="bg-white min-h-screen">

      {/* ── NAV ── */}
      <nav className="fixed top-0 inset-x-0 z-30 bg-[#0B1120]/95 backdrop-blur-sm border-b border-white/10">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div>
            <span className="text-white font-bold text-lg tracking-tight">Lex Kenya</span>
            <span className="text-emerald-400 text-xs ml-2 font-medium">Legal Intelligence</span>
          </div>
          <div className="flex items-center gap-3">
            <Link to="/login"
              className="text-slate-300 hover:text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors">
              Log in
            </Link>
            <Link to="/signup"
              className="bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors">
              Sign up →
            </Link>
          </div>
        </div>
      </nav>

      {/* ── HERO ── */}
      <section className="bg-[#0B1120] pt-32 pb-24 px-6">
        <div className="max-w-4xl mx-auto text-center space-y-6">
          <div className="inline-flex items-center gap-2 bg-emerald-900/40 border border-emerald-700/50 rounded-full px-4 py-1.5 text-emerald-400 text-sm font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            Knowledge graph active — 5,500+ verified legal nodes
          </div>

          <h1 className="text-5xl md:text-6xl font-extrabold text-white leading-tight tracking-tight">
            The first AI legal intelligence<br />
            <span className="text-emerald-400">platform for Kenyan law.</span>
          </h1>

          <p className="text-xl text-slate-400 max-w-2xl mx-auto leading-relaxed">
            Our proprietary knowledge graph maps the Constitution, 19 corporate Acts,
            and case law from five courts. Every answer traces back to a specific legal source.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 pt-2">
            <Link to="/signup"
              className="w-full sm:w-auto bg-emerald-600 hover:bg-emerald-500 text-white font-semibold px-8 py-3.5 rounded-xl text-base transition-colors shadow-lg shadow-emerald-900/30">
              Get started free →
            </Link>
            <a href="#how-it-works"
              className="w-full sm:w-auto border border-white/20 hover:border-white/40 text-slate-300 hover:text-white font-medium px-8 py-3.5 rounded-xl text-base transition-colors">
              See how it works ↓
            </a>
          </div>

          {/* Court badges */}
          <div className="pt-8 border-t border-white/10">
            <p className="text-slate-500 text-xs uppercase tracking-widest mb-4 font-medium">
              Verified sources from Kenya's five courts
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              {COURTS.map(c => (
                <span key={c}
                  className="bg-white/5 border border-white/10 text-slate-400 text-xs px-3 py-1.5 rounded-full">
                  {c}
                </span>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── STATS BAR ── */}
      <section className="bg-emerald-600">
        <div className="max-w-4xl mx-auto px-6 py-5 grid grid-cols-2 sm:grid-cols-4 gap-6 text-center">
          {STATS.map(s => (
            <div key={s.label}>
              <div className="text-2xl font-bold text-white">{s.value}</div>
              <div className="text-emerald-200 text-sm">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── PROBLEMS → SOLUTIONS ── */}
      <section className="bg-slate-50 py-20 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl font-bold text-slate-900">Legal research, redesigned.</h2>
            <p className="text-slate-500 mt-2">Three problems. Three modules. One knowledge graph.</p>
          </div>
          <div className="grid md:grid-cols-3 gap-6">
            {PROBLEMS.map(p => (
              <div key={p.icon} className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 space-y-4">
                <div className="w-10 h-10 bg-emerald-50 rounded-xl flex items-center justify-center text-xl">{p.icon}</div>
                <div>
                  <p className="text-slate-400 text-sm line-through mb-2">{p.problem}</p>
                  <p className="text-slate-700 text-sm font-medium">{p.solution}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── HOW IT WORKS ── */}
      <section id="how-it-works" className="bg-white py-20 px-6">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl font-bold text-slate-900">How GraphRAG works</h2>
            <p className="text-slate-500 mt-2">Graph traversal + semantic retrieval — grounded answers every time.</p>
          </div>
          <div className="grid md:grid-cols-3 gap-6 relative">
            {[
              { step: '1', title: 'You ask a question', desc: '"Can a director vote on a related-party transaction?" — plain English, any corporate law topic.' },
              { step: '2', title: 'Graph + semantic search', desc: 'Traverses 5,500+ nodes across Acts, judgments, and constitutional articles. Ranks by authority and relevance.' },
              { step: '3', title: 'Cited answer', desc: 'Every claim is tagged to the exact section or case. You see the source, the authority score, and the citation path.' },
            ].map((s, i) => (
              <div key={i} className="relative">
                <div className="bg-slate-900 rounded-2xl p-6 text-white h-full">
                  <div className="w-8 h-8 bg-emerald-600 rounded-lg flex items-center justify-center text-sm font-bold mb-4">{s.step}</div>
                  <h3 className="font-semibold mb-2">{s.title}</h3>
                  <p className="text-slate-400 text-sm leading-relaxed">{s.desc}</p>
                </div>
                {i < 2 && (
                  <div className="hidden md:block absolute top-1/2 -right-3 z-10 text-slate-400 text-lg">→</div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── MODULE SHOWCASE ── */}
      <section className="bg-slate-50 py-20 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl font-bold text-slate-900">Three modules. One platform.</h2>
            <p className="text-slate-500 mt-2">Every module is powered by the same knowledge graph.</p>
          </div>
          <div className="grid md:grid-cols-3 gap-6">
            {MODULES.map(m => (
              <div key={m.id} className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
                <div className="p-6 flex-1 space-y-3">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-semibold text-slate-900">{m.title}</h3>
                    <span className="text-xs bg-emerald-50 text-emerald-700 border border-emerald-200 px-2 py-0.5 rounded-full whitespace-nowrap">{m.badge}</span>
                  </div>
                  <p className="text-slate-500 text-sm leading-relaxed">{m.desc}</p>
                  <ModuleDemo module={m} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── GRAPH CREDENTIAL ── */}
      <section className="bg-slate-900 py-20 px-6">
        <div className="max-w-3xl mx-auto text-center space-y-5">
          <div className="inline-flex items-center gap-2 bg-emerald-900/40 border border-emerald-700/50 rounded-full px-4 py-1.5 text-emerald-400 text-sm font-medium mb-2">
            Proprietary knowledge graph
          </div>
          <h2 className="text-3xl font-bold text-white">
            Built on verified Kenyan legal sources — not the open internet.
          </h2>
          <p className="text-slate-400 text-lg leading-relaxed">
            Unlike general-purpose AI tools that hallucinate statute references, Lex Kenya answers
            are generated against a structured graph of verified legal sources. Every citation is a
            real node — cross-linked with <span className="text-emerald-400">CITES</span>,{' '}
            <span className="text-emerald-400">PART_OF</span>,{' '}
            <span className="text-emerald-400">INTERPRETS</span>, and{' '}
            <span className="text-emerald-400">DERIVES_AUTHORITY_FROM</span> relationships.
          </p>
          {/* Simple node diagram */}
          <div className="flex items-center justify-center gap-3 pt-4 flex-wrap">
            {['Case', '→ CITES →', 'Section', '→ PART_OF →', 'Act'].map((n, i) => (
              <span key={i} className={i % 2 === 0
                ? 'bg-white/10 border border-white/20 text-white text-xs px-3 py-1.5 rounded-full font-medium'
                : 'text-emerald-400 text-xs font-mono'}>
                {n}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA STRIP ── */}
      <section className="bg-emerald-600 py-16 px-6">
        <div className="max-w-2xl mx-auto text-center space-y-4">
          <h2 className="text-3xl font-bold text-white">Start your free legal research today.</h2>
          <p className="text-emerald-100">No credit card. No setup. Instant access to the knowledge graph.</p>
          <Link to="/signup"
            className="inline-block bg-white text-emerald-700 font-bold px-8 py-3.5 rounded-xl text-base hover:bg-emerald-50 transition-colors shadow-lg">
            Create free account →
          </Link>
        </div>
      </section>

      {/* ── FOOTER ── */}
      <footer className="bg-slate-900 text-slate-400 py-12 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8 mb-8">
            <div>
              <div className="text-white font-bold mb-3">Product</div>
              {['Q&A Assistant', 'Compliance Checker', 'Ruling Predictor', 'Knowledge Graph'].map(l => (
                <Link key={l} to="/signup" className="block text-sm hover:text-white mb-1.5 transition-colors">{l}</Link>
              ))}
            </div>
            <div>
              <div className="text-white font-bold mb-3">Legal Sources</div>
              {['Constitution of Kenya 2010', 'Companies Act 2015', 'Capital Markets Act', 'Employment Act'].map(l => (
                <div key={l} className="text-sm mb-1.5">{l}</div>
              ))}
            </div>
            <div>
              <div className="text-white font-bold mb-3">Courts</div>
              {COURTS.map(c => (
                <div key={c} className="text-sm mb-1.5">{c}</div>
              ))}
            </div>
            <div>
              <div className="text-white font-bold mb-3">Company</div>
              {['About', 'Pricing', 'Contact'].map(l => (
                <div key={l} className="text-sm mb-1.5">{l}</div>
              ))}
              <div className="mt-4 text-xs bg-amber-900/40 border border-amber-700/40 text-amber-300 p-3 rounded-lg">
                AI-assisted legal research — not legal advice.
              </div>
            </div>
          </div>
          <div className="border-t border-white/10 pt-6 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs">
            <span>© 2026 Lex Kenya. AI-assisted legal research — not legal advice.</span>
            <span>Purpose-built for Kenyan corporate law.</span>
          </div>
        </div>
      </footer>

    </div>
  )
}

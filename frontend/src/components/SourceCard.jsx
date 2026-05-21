import SlideOver from './SlideOver'

function ScoreBar({ label, value }) {
  const pct = Math.round((value || 0) * 100)
  return (
    <div className="mb-2">
      <div className="flex justify-between text-xs text-slate-500 mb-1">
        <span>{label}</span><span>{value?.toFixed(2) ?? '—'}</span>
      </div>
      <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function SourceCard({ open, onClose, source }) {
  if (!source) return null

  const label = source.label || ''

  return (
    <SlideOver open={open} onClose={onClose} title={source.title || 'Source detail'}>
      <div className="space-y-4 text-sm">

        {/* Label badge */}
        <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-600">
          {label}
        </span>

        {/* Section / Clause */}
        {(label === 'Section' || label === 'Clause') && (
          <div className="space-y-1">
            {source.act && <p className="text-slate-500">{source.act} {source.act_year ? `(${source.act_year})` : ''}</p>}
            {source.section_number && <p className="font-medium text-slate-700">Section {source.section_number}</p>}
            {source.chapter && <p className="text-slate-500 text-xs">Chapter: {source.chapter}</p>}
          </div>
        )}

        {/* Article */}
        {label === 'Article' && (
          <div className="space-y-1">
            <p className="text-slate-500">Constitution of Kenya 2010</p>
            {source.article_number && <p className="font-medium text-slate-700">Article {source.article_number}</p>}
          </div>
        )}

        {/* Case */}
        {label === 'Case' && (
          <div className="space-y-1">
            {source.citation && <p className="font-mono text-xs bg-slate-50 px-2 py-1 rounded border">{source.citation}</p>}
            <div className="flex flex-wrap gap-3 text-slate-500">
              {source.court && <span>🏛 {source.court}</span>}
              {source.year  && <span>📅 {source.year}</span>}
            </div>
            {source.outcome && (
              <p className={`text-xs font-medium px-2 py-1 rounded inline-block ${
                source.outcome.toLowerCase().includes('appeal') || source.outcome.toLowerCase().includes('success')
                  ? 'bg-emerald-50 text-emerald-700'
                  : 'bg-slate-50 text-slate-600'
              }`}>
                Outcome: {source.outcome}
              </p>
            )}
            {source.overruled_by && (
              <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded p-2">
                <span className="text-amber-500 mt-0.5">⚠</span>
                <p className="text-amber-700 text-xs">Overruled by: {source.overruled_by}</p>
              </div>
            )}
          </div>
        )}

        <div className="border-t border-slate-100 pt-3">
          <ScoreBar label="Authority score" value={source.authority_score} />
          <ScoreBar label="Relevance score" value={source.relevance_score} />
        </div>
      </div>
    </SlideOver>
  )
}

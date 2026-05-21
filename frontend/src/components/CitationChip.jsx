import { useState } from 'react'
import SourceCard from './SourceCard'

const STYLES = {
  section: 'bg-emerald-50 text-emerald-800 border-emerald-200 hover:bg-emerald-100',
  article: 'bg-blue-50 text-blue-800 border-blue-200 hover:bg-blue-100',
  case:    'bg-violet-50 text-violet-800 border-violet-200 hover:bg-violet-100',
  overruled: 'bg-amber-50 text-amber-800 border-amber-300 hover:bg-amber-100',
}

export default function CitationChip({ type = 'section', label, sourceData, overruled = false }) {
  const [open, setOpen] = useState(false)
  const style = overruled ? STYLES.overruled : (STYLES[type] || STYLES.section)

  return (
    <>
      <button
        onClick={() => sourceData && setOpen(true)}
        className={`inline-flex items-center gap-1 text-xs font-medium px-1.5 py-0.5 rounded border mx-0.5 transition-colors ${style} ${sourceData ? 'cursor-pointer' : 'cursor-default'}`}
        title={overruled ? 'This case may have been overruled' : undefined}
      >
        {overruled && <span className="text-amber-500">⚠</span>}
        {label}
      </button>

      {sourceData && (
        <SourceCard open={open} onClose={() => setOpen(false)} source={sourceData} />
      )}
    </>
  )
}

// Parses an answer string and wraps citation patterns in CitationChip components
export function parseAnswer(text, sources = []) {
  if (!text) return null

  const sourceMap = {}
  sources.forEach(s => {
    if (s.citation_tag) sourceMap[s.citation_tag] = s
    if (s.section_number) sourceMap[`§ ${s.section_number}`] = s
  })

  // Split on citation patterns: [§ X], [Art. N], [⚖ Name Year]
  const parts = text.split(/(\[(?:§[^\]]+|Art\.[^\]]+|⚖[^\]]+)\])/g)

  return parts.map((part, i) => {
    const chipMatch = part.match(/^\[(.+)\]$/)
    if (!chipMatch) return part

    const label = chipMatch[1]
    let type = 'section'
    if (label.startsWith('Art.')) type = 'article'
    else if (label.startsWith('⚖')) type = 'case'

    const src = sourceMap[label] || sourceMap[label.replace(/^\[|\]$/g, '')] || null

    return (
      <CitationChip
        key={i}
        type={type}
        label={label}
        sourceData={src}
        overruled={src?.overruled_by ? true : false}
      />
    )
  })
}

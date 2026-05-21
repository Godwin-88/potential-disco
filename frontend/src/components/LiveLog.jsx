import { useEffect, useRef } from 'react'

export default function LiveLog({ lines = [], running = false }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  return (
    <div className="bg-slate-900 rounded-lg p-3 font-mono text-xs text-emerald-400 h-48 overflow-y-auto scrollbar-thin">
      {lines.length === 0 && !running && (
        <span className="text-slate-500">No activity yet. Start a scrape to see live output.</span>
      )}
      {lines.map((line, i) => (
        <div key={i} className="leading-5">{line}</div>
      ))}
      {running && (
        <div className="flex items-center gap-1 text-emerald-500 mt-1">
          <span>›</span>
          <div className="dot-pulse flex gap-0.5">
            <span /><span /><span />
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  )
}

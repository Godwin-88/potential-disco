import { useEffect, useRef, useState } from 'react'

const COLOURS = {
  'Claimant succeeds': 'bg-emerald-500',
  'Partial remedy':    'bg-amber-400',
  'Dismissed':         'bg-red-400',
}

function getColour(label) {
  for (const [k, v] of Object.entries(COLOURS)) {
    if (label.toLowerCase().includes(k.toLowerCase().split(' ')[0])) return v
  }
  return 'bg-slate-400'
}

export default function OutcomeBar({ label, percent }) {
  const [width, setWidth] = useState(0)
  const ref = useRef(null)

  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setTimeout(() => setWidth(percent), 50)
        observer.disconnect()
      }
    })
    if (ref.current) observer.observe(ref.current)
    return () => observer.disconnect()
  }, [percent])

  return (
    <div ref={ref} className="flex items-center gap-3 text-sm" role="meter" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
      <span className="w-40 text-slate-600 shrink-0">{label}</span>
      <div className="flex-1 h-3 bg-slate-100 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ease-out ${getColour(label)}`}
          style={{ width: `${width}%` }}
        />
      </div>
      <span className="w-10 text-right font-semibold text-slate-700">{percent}%</span>
    </div>
  )
}

const CONFIG = {
  low:    { bg: 'bg-emerald-50 border-emerald-300 text-emerald-800', icon: '✓', text: 'Low compliance risk' },
  medium: { bg: 'bg-amber-50 border-amber-300 text-amber-800',       icon: '⚠', text: 'Medium compliance risk' },
  high:   { bg: 'bg-red-50 border-red-300 text-red-800',             icon: '●', text: 'High compliance risk' },
}

export default function RiskBadge({ level = 'low' }) {
  const c = CONFIG[level] || CONFIG.low
  return (
    <div className={`flex items-center gap-2 px-4 py-2.5 rounded-lg border font-semibold text-sm ${c.bg}`}>
      <span>{c.icon}</span>
      <span>{c.text}</span>
    </div>
  )
}

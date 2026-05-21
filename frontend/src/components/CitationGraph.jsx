import { useEffect, useRef } from 'react'
import * as d3 from 'd3'

const NODE_COLOUR = {
  Section:      '#10b981',
  Case:         '#8b5cf6',
  Article:      '#3b82f6',
  Act:          '#64748b',
  Clause:       '#14b8a6',
  Provision:    '#f59e0b',
}

function colour(label) {
  return NODE_COLOUR[label] || '#94a3b8'
}

export default function CitationGraph({ nodes = [], edges = [] }) {
  const svgRef = useRef(null)

  useEffect(() => {
    if (!nodes.length) return

    const el   = svgRef.current
    const W    = el.clientWidth  || 380
    const H    = el.clientHeight || 340

    d3.select(el).selectAll('*').remove()

    const svg = d3.select(el)
      .attr('viewBox', `0 0 ${W} ${H}`)

    // Arrow marker
    svg.append('defs').append('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -4 8 8')
      .attr('refX', 14).attr('refY', 0)
      .attr('markerWidth', 6).attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path').attr('d', 'M0,-4L8,0L0,4').attr('fill', '#94a3b8')

    const simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(edges).id(d => d.id).distance(90))
      .force('charge', d3.forceManyBody().strength(-180))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collision', d3.forceCollide(24))

    const link = svg.append('g').selectAll('line')
      .data(edges).join('line')
      .attr('stroke', '#cbd5e1').attr('stroke-width', 1.5)
      .attr('marker-end', 'url(#arrow)')

    const linkLabel = svg.append('g').selectAll('text')
      .data(edges).join('text')
      .attr('font-size', 8).attr('fill', '#94a3b8').attr('text-anchor', 'middle')
      .text(d => d.type || '')

    const node = svg.append('g').selectAll('circle')
      .data(nodes).join('circle')
      .attr('r', d => 8 + (d.score || 0.5) * 8)
      .attr('fill', d => colour(d.label))
      .attr('opacity', 0.85)
      .call(d3.drag()
        .on('start', (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
        .on('drag',  (event, d) => { d.fx = event.x; d.fy = event.y })
        .on('end',   (event, d) => { if (!event.active) simulation.alphaTarget(0);    d.fx = null; d.fy = null })
      )

    const label = svg.append('g').selectAll('text')
      .data(nodes).join('text')
      .attr('font-size', 9).attr('fill', '#1e293b').attr('text-anchor', 'middle').attr('dy', '0.3em')
      .text(d => (d.title || d.id || '').substring(0, 18))

    simulation.on('tick', () => {
      link
        .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y)

      linkLabel
        .attr('x', d => (d.source.x + d.target.x) / 2)
        .attr('y', d => (d.source.y + d.target.y) / 2)

      node.attr('cx', d => d.x).attr('cy', d => d.y)
      label.attr('x', d => d.x).attr('y', d => d.y + 20)
    })

    return () => simulation.stop()
  }, [nodes, edges])

  if (!nodes.length) {
    return (
      <div className="flex items-center justify-center h-40 text-slate-400 text-sm">
        No graph data available.
      </div>
    )
  }

  return (
    <div>
      <svg ref={svgRef} className="w-full h-72 rounded-lg bg-slate-50 border border-slate-200" />
      <div className="flex flex-wrap gap-2 mt-3">
        {Object.entries(NODE_COLOUR).map(([label, col]) => (
          <div key={label} className="flex items-center gap-1 text-xs text-slate-500">
            <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: col }} />
            {label}
          </div>
        ))}
      </div>
    </div>
  )
}

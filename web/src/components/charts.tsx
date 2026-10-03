// Hand-built SVG charts, following the prototype's lecSVG() and histSVG().
// The data (curve points and histogram bins) comes from the API.

import type { CurvePoint, Histogram } from '../types'
import { money, pct } from '../lib/format'

export const SERIES_COLORS = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)']

function niceMax(v: number): number {
  if (!(v > 0)) return 1
  const e = Math.pow(10, Math.floor(Math.log10(v)))
  const f = v / e
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * e
}

export interface CurveSeries {
  name: string
  color: string
  points: CurvePoint[]
}

/** Loss exceedance curve(s): chance that annual loss exceeds x. */
export function LecChart({ series, threshold, label }: { series: CurveSeries[]; threshold: number | null; label: string }) {
  if (!series.length || series.every((s) => s.points.every((p) => p.y === 0))) {
    return <p className="muted">No losses were simulated, so there is no curve to draw.</p>
  }
  const multi = series.length > 1
  const W = 640, H = 306, l = 58, rt = 24, t = 14, b = 44
  const pw = W - l - rt, ph = H - t - b
  const xmax = Math.max(...series.map((s) => s.points[s.points.length - 1]?.x ?? 0)) || 1
  const ytop = Math.max(...series.map((s) => s.points[0]?.y ?? 0))
  const ymax = Math.min(1, niceMax(ytop * 1.05))
  const X = (x: number) => l + (x / xmax) * pw
  const Y = (y: number) => t + ph - (y / ymax) * ph
  const ticks = [0, 1, 2, 3, 4, 5]

  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        {ticks.map((i) => {
          const yv = (ymax * i) / 5
          return (
            <g key={`y${i}`}>
              <line className="gl" x1={l} x2={W - rt} y1={Y(yv)} y2={Y(yv)} />
              <text x={l - 6} y={Y(yv) + 4} textAnchor="end">{pct(yv)}</text>
            </g>
          )
        })}
        {ticks.map((i) => {
          const xv = (xmax * i) / 5
          return <text key={`x${i}`} x={X(xv)} y={t + ph + 16} textAnchor="middle">{money(xv)}</text>
        })}
        <line className="ax" x1={l} x2={W - rt} y1={t + ph} y2={t + ph} />
        <line className="ax" x1={l} x2={l} y1={t} y2={t + ph} />
        <text x={l + pw / 2} y={t + ph + 38} textAnchor="middle">Annual loss</text>
        {series.map((s, i) => (
          <path
            key={i}
            d={'M' + s.points.map((p) => `${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join(' L')}
            fill="none"
            stroke={s.color}
            strokeWidth={2.5}
            strokeLinejoin="round"
          />
        ))}
        {threshold != null && threshold > 0 && threshold <= xmax && (
          <>
            <line x1={X(threshold)} x2={X(threshold)} y1={t} y2={t + ph} stroke="var(--red)" strokeWidth={1.5} strokeDasharray="5 4" />
            <text x={X(threshold) + 5} y={t + 12} className="thr">threshold {money(threshold)}</text>
          </>
        )}
      </svg>
      {multi && (
        // An HTML legend wraps on narrow screens, where an in-SVG one would collide.
        <ul className="chart-legend" aria-label="Legend">
          {series.map((s, i) => (
            <li key={i}>
              <span className="sw" style={{ background: s.color }} />
              {s.name}
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

/** Histogram of the cost of one loss event, as a share of simulated events. */
export function HistChart({ hist }: { hist: Histogram | null }) {
  if (!hist || hist.total === 0) return <p className="muted">No loss events were simulated.</p>
  const W = 640, H = 246, l = 46, rt = 24, t = 10, b = 46
  const pw = W - l - rt, ph = H - t - b, B = hist.bins.length
  const ymax = niceMax(Math.max(...hist.bins.map((x) => x.share)))
  const bw = pw / B
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Histogram of single loss event cost">
      {[0, 1, 2, 3, 4].map((i) => {
        const yv = (ymax * i) / 4
        const y = t + ph - (yv / ymax) * ph
        return (
          <g key={`y${i}`}>
            <line className="gl" x1={l} x2={W - rt} y1={y} y2={y} />
            <text x={l - 6} y={y + 4} textAnchor="end">{pct(yv)}</text>
          </g>
        )
      })}
      {hist.bins.map((bin, i) => {
        const h = (bin.share / ymax) * ph
        return (
          <rect
            key={i}
            x={(l + i * bw + 1).toFixed(1)}
            y={(t + ph - h).toFixed(1)}
            width={(bw - 2).toFixed(1)}
            height={h.toFixed(1)}
            fill="var(--s1)"
            opacity={i === B - 1 ? 0.55 : 0.9}
          >
            <title>{`${money(bin.x0)}–${money(bin.x1)}${i === B - 1 ? '+' : ''}: ${pct(bin.share)} of events`}</title>
          </rect>
        )
      })}
      {[0, 1, 2, 3, 4].map((i) => (
        <text key={`x${i}`} x={l + (pw * i) / 4} y={t + ph + 16} textAnchor="middle">
          {money((hist.max * i) / 4)}
          {i === 4 ? '+' : ''}
        </text>
      ))}
      <line className="ax" x1={l} x2={W - rt} y1={t + ph} y2={t + ph} />
      <text x={l + pw / 2} y={t + ph + 38} textAnchor="middle">Cost of one loss event (share of events)</text>
    </svg>
  )
}

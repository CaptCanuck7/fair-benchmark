import { useState } from 'react'
import type { Conf, Dist } from '../types'
import { useContent } from '../content'
import { NUMBER_HINT } from '../lib/format'
import { distStatus, factorAnchor } from '../lib/model'
import { NumberInput } from './NumberInput'

const BOUNDS = [
  ['min', 'Minimum'],
  ['ml', 'Most likely'],
  ['max', 'Maximum'],
] as const

interface Props {
  factorKey: string // e.g. "tef" or "primary.response"
  dist: Dist
  onChange: (field: keyof Dist, value: unknown) => void
}

/** One factor estimate: min / most likely / max, confidence, help and rationale. */
export function FactorRow({ factorKey, dist, onChange }: Props) {
  const content = useContent()
  const f = content.factors[factorKey]
  const placeholders = content.placeholders[f.kind]
  const [bad, setBad] = useState<Record<string, boolean>>({})
  const anchor = factorAnchor(factorKey)

  const status = distStatus(dist, f.kind)
  const anyBad = Object.values(bad).some(Boolean)
  const message = anyBad ? NUMBER_HINT : status.state === 'error' ? status.msg : ''
  const msgId = `${anchor}-msg`

  return (
    <div className="dist" id={anchor} data-key={factorKey}>
      <div>
        <span className="dname">{f.label}</span>
        <span className="unit">{f.unit}</span>
      </div>
      <div className="dgrid">
        {BOUNDS.map(([k, label], j) => (
          <label className="fld" key={k}>
            <span>{label}</span>
            <NumberInput
              kind={f.kind}
              value={dist[k]}
              placeholder={placeholders[j]}
              aria-describedby={message ? msgId : undefined}
              onValue={(v, invalid) => {
                setBad((b) => ({ ...b, [k]: invalid }))
                onChange(k, v)
              }}
            />
          </label>
        ))}
        <label className="fld conf">
          <span>Confidence</span>
          <select value={dist.conf} onChange={(e) => onChange('conf', e.target.value as Conf)}>
            {(Object.keys(content.confidence) as Conf[]).map((c) => (
              <option key={c} value={c}>
                {content.confidence[c].label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="dmsg" id={msgId} role="status">
        {message}
      </div>
      <details className="more">
        <summary>What this means and where to get it</summary>
        <div className="body">
          <p>{f.help}</p>
          <p>
            <b>Where the data comes from:</b> {f.data}
          </p>
          <p className="muted">
            Confidence sets how tightly values cluster around your most likely value. Choose low when you know the range
            but not where in it the answer falls.
          </p>
        </div>
      </details>
      <label className="fld src">
        <span>Rationale and sources</span>
        <textarea
          rows={1}
          value={dist.src}
          placeholder="How you got these numbers and who you asked"
          onChange={(e) => onChange('src', e.target.value)}
        />
      </label>
    </div>
  )
}

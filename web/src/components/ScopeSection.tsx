import type { Scope } from '../types'
import { EFFECTS, THREAT_TYPES } from '../lib/model'

interface Props {
  scope: Scope
  onChange: (field: keyof Scope, value: string) => void
}

export function ScopeSection({ scope: s, onChange }: Props) {
  const text = (field: keyof Scope) => ({
    value: s[field],
    onChange: (e: { target: { value: string } }) => onChange(field, e.target.value),
  })
  // Keep an unknown value from an import selectable rather than silently replacing it.
  const threatTypes = THREAT_TYPES.includes(s.threatType) ? THREAT_TYPES : [...THREAT_TYPES, s.threatType]
  const effects = EFFECTS.includes(s.effect) ? EFFECTS : [...EFFECTS, s.effect]

  return (
    <section className="panel sec" id="sec-scope">
      <h2>
        <span className="n">1</span>Scope the scenario
      </h2>
      <p className="lede">
        A loss event scenario names a specific asset, a specific threat community, and the effect on the asset. If you
        can’t name all three, the scenario isn’t ready to quantify. The scope applies to every option you compare.
      </p>
      <div className="grid2">
        <label className="fld">
          <span>Asset at risk</span>
          <input {...text('asset')} placeholder="What is lost or harmed, e.g. customer PII in the payroll integration" />
        </label>
        <label className="fld">
          <span>Threat community</span>
          <input {...text('threatCommunity')} placeholder="Who or what acts, e.g. external cybercriminals" />
        </label>
        <label className="fld">
          <span>Threat type</span>
          <select {...text('threatType')}>
            {threatTypes.map((o) => (
              <option key={o}>{o}</option>
            ))}
          </select>
        </label>
        <label className="fld">
          <span>Effect</span>
          <select {...text('effect')}>
            {effects.map((o) => (
              <option key={o}>{o}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="grid2" style={{ marginTop: 12 }}>
        <label className="fld">
          <span>Condition or issue behind this risk</span>
          <textarea {...text('condition')} rows={2} placeholder="The weakness or change that prompted the analysis" />
        </label>
        <label className="fld">
          <span>Existing controls</span>
          <textarea
            {...text('controls')}
            rows={2}
            placeholder="Controls in place today, and which part of the scenario each one affects"
          />
        </label>
      </div>
      <label className="fld" style={{ marginTop: 12 }}>
        <span>Analyst notes and assumptions</span>
        <textarea {...text('notes')} rows={2} placeholder="Assumptions, people consulted, open questions" />
      </label>
      <details className="more">
        <summary>What makes a good scenario</summary>
        <div className="body">
          <p>
            Write it as a sentence: “<i>Threat community</i> causes <i>effect</i> to <i>asset</i> through{' '}
            <i>method</i>.” For example: “External criminals exfiltrate customer PII from the payroll integration by
            exploiting weak transport security.”
          </p>
          <p>
            Keep the condition (the weakness) separate from the risk. A missing control is not a risk by itself; it
            changes the frequency or magnitude of a loss scenario. Split scenarios that have different threat
            communities or effects, because their frequencies and losses behave differently.
          </p>
        </div>
      </details>
    </section>
  )
}

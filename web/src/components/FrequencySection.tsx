import type { Dist, LefInputs, LefMode, VulnMode } from '../types'
import { FactorRow } from './FactorRow'

interface Props {
  stateId: string
  lef: LefInputs
  onChange: (path: string, value: unknown) => void
}

const MODES: [LefMode, string, string][] = [
  ['tef_vuln', 'Threat event frequency × vulnerability', 'The usual choice: how often the threat acts, times the chance it succeeds.'],
  ['cf_poa', 'Contact frequency × probability of action × vulnerability', 'Use when contacts (scans, sessions, access) are easier to count than attempts.'],
  ['lef', 'Loss event frequency directly', 'Use when you have loss history for this scenario.'],
]

const VULN_MODES: [VulnMode, string, string][] = [
  ['direct', 'Estimate vulnerability as a percentage', 'The usual choice. Base it on how well the controls cover this attack path.'],
  ['tcap_rs', 'Derive it from threat capability and resistance strength', 'Compare how capable the attackers are with how strong the controls are, on a 0 to 100 scale.'],
]

function Choice<T extends string>({ name, value, options, onPick }: {
  name: string
  value: T
  options: [T, string, string][]
  onPick: (v: T) => void
}) {
  return (
    <div className="choice" role="radiogroup">
      {options.map(([v, title, desc]) => (
        <label className="opt" key={v}>
          <input type="radio" name={name} value={v} checked={value === v} onChange={() => onPick(v)} />
          <span>
            <b>{title}</b>
            <small>{desc}</small>
          </span>
        </label>
      ))}
    </div>
  )
}

export function FrequencySection({ stateId, lef, onChange }: Props) {
  const row = (key: keyof LefInputs & string) => (
    <FactorRow
      key={`${stateId}-${key}`}
      factorKey={key}
      dist={lef[key] as Dist}
      onChange={(field, v) => onChange(`lef.${key}.${field}`, v)}
    />
  )

  return (
    <section className="panel sec" id="sec-lef">
      <h2>
        <span className="n">2</span>Loss event frequency
      </h2>
      <p className="lede">
        How often the loss event is expected to happen in a year. You can estimate it directly or build it up from how
        often the threat acts and how often it succeeds.
      </p>
      <Choice name={`lefmode-${stateId}`} value={lef.mode} options={MODES} onPick={(v) => onChange('lef.mode', v)} />
      {lef.mode === 'lef' ? (
        row('lef')
      ) : (
        <>
          {lef.mode === 'cf_poa' ? (
            <>
              {row('cf')}
              {row('poa')}
            </>
          ) : (
            row('tef')
          )}
          <h3>Vulnerability</h3>
          <Choice
            name={`vulnmode-${stateId}`}
            value={lef.vulnMode}
            options={VULN_MODES}
            onPick={(v) => onChange('lef.vulnMode', v)}
          />
          {lef.vulnMode === 'tcap_rs' ? (
            <>
              {row('tcap')}
              {row('rs')}
            </>
          ) : (
            row('vuln')
          )}
        </>
      )}
    </section>
  )
}

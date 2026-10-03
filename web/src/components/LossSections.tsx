import type { Dist, State } from '../types'
import { useContent } from '../content'
import { FactorRow } from './FactorRow'

interface Props {
  state: State
  onChange: (path: string, value: unknown) => void
}

function Row({ state, path, onChange }: Props & { path: string }) {
  const d = path.split('.').reduce<unknown>((o, k) => (o as Record<string, unknown>)[k], state) as Dist
  return (
    <FactorRow
      key={`${state.id}-${path}`}
      factorKey={path}
      dist={d}
      onChange={(field, v) => onChange(`${path}.${field}`, v)}
    />
  )
}

export function PrimarySection({ state, onChange }: Props) {
  const { forms } = useContent()
  return (
    <section className="panel sec" id="sec-primary">
      <h2>
        <span className="n">3</span>Primary loss
      </h2>
      <p className="lede">
        What one loss event costs the organization directly. Estimate per event, not per year. Leave a form blank if it
        doesn’t apply; enter at least one.
      </p>
      {forms.primary.map(({ key }) => (
        <Row key={`${state.id}-${key}`} state={state} path={`primary.${key}`} onChange={onChange} />
      ))}
    </section>
  )
}

export function SecondarySection({ state, onChange }: Props) {
  const { forms } = useContent()
  return (
    <section className="panel sec" id="sec-secondary">
      <h2>
        <span className="n">4</span>Secondary loss
      </h2>
      <p className="lede">
        Losses that come from other stakeholders reacting to the event: customers, regulators, partners. First estimate
        how often they react, then what it costs when they do. Leave this section blank if secondary stakeholders
        wouldn’t be involved.
      </p>
      <Row key={`${state.id}-slef`} state={state} path="slef" onChange={onChange} />
      <h3>Secondary loss magnitude</h3>
      {forms.secondary.map(({ key }) => (
        <Row key={`${state.id}-${key}`} state={state} path={`secondary.${key}`} onChange={onChange} />
      ))}
    </section>
  )
}

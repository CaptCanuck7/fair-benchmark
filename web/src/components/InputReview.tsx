import type { FindingKind, State } from '../types'
import { useContent } from '../content'
import type { AnalysisAgent } from '../hooks/useAnalysisAgent'
import { DraftActions, DraftLabel } from './DraftControls'

const KIND: Record<FindingKind, string> = {
  no_rationale: 'No rationale',
  evidence_conflict: 'Conflicts with evidence',
  scope_drift: 'Scope drift',
  unexplained_change: 'Unexplained change',
  unit_mistake: 'Possible unit mistake',
  other: 'Other',
}

interface Props {
  agent: AnalysisAgent
  states: State[]
  /** Switch to an option and jump to one of its factors (or the option itself). */
  onGoto: (stateIndex: number, factor: string | null) => void
}

/** The agent's advisory review of the inputs (task 7). It never blocks a run. */
export function InputReview({ agent, states, onGoto }: Props) {
  const content = useContent()
  const draft = agent.view?.review ?? null
  const last = agent.view?.runs.find((r) => r.task === 'review')
  const working = last && (last.status === 'queued' || last.status === 'running')
  if (!draft && !last && !agent.error) return null

  const index = (stateId: string | null) => states.findIndex((s) => s.id === stateId)
  const label = (factor: string | null) =>
    factor === 'method' ? 'Frequency method' : factor ? (content.factors[factor]?.label ?? factor) : null

  return (
    <section className="panel sec" id="sec-review" aria-labelledby="review-h">
      <h2 id="review-h">Agent review of the inputs</h2>
      <p className="lede">
        Advisory findings beside the automatic checks. They never block a run: you decide what, if anything, to change.
      </p>
      {working && <p className="muted" role="status">The agent is reviewing the inputs…</p>}
      {agent.error && (
        <div className="check error" role="alert">
          {agent.error}
        </div>
      )}
      {last?.status === 'failed' && <div className="check error">The last review failed: {last.error}</div>}
      {draft && (
        <>
          <DraftLabel draft={draft} />
          {draft.stale && (
            <div className="check warn">The inputs changed after this review. Review them again to update the findings.</div>
          )}
          <p>{draft.effective.summary}</p>
          {draft.effective.findings.length === 0 ? (
            <p className="muted">No findings.</p>
          ) : (
            <ul className="findings">
              {draft.effective.findings.map((f, k) => {
                const i = index(f.state_id)
                return (
                  <li key={k} className="check info">
                    <b>{KIND[f.kind] ?? f.kind}</b>
                    {i >= 0 && <> · {states[i].name}</>}
                    {f.factor && <> · {label(f.factor)}</>}
                    <div>{f.message}</div>
                    {f.suggestion && <div className="muted">{f.suggestion}</div>}
                    {i >= 0 && (
                      <button type="button" className="btn quiet" onClick={() => onGoto(i, f.factor === 'method' ? null : f.factor)}>
                        Go to {f.factor && f.factor !== 'method' ? 'factor' : 'option'}
                      </button>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
          <DraftActions
            draft={draft}
            actions={['approve', 'reject']}
            busy={agent.busy}
            onAction={(a) => void agent.decide(draft.id, a)}
          />
        </>
      )}
    </section>
  )
}

import { useState } from 'react'
import type { AgentStatus, EvidenceItem, FactorGroup, RegisterRiskDetail } from '../types'
import { api, ApiError } from '../api/client'
import { useContent } from '../content'
import { dateTime } from '../lib/format'
import { TaskBar } from './DraftControls'

export const GROUPS: [FactorGroup, string, string][] = [
  ['frequency', 'Frequency', 'How often the threat acts or the loss event happens.'],
  ['susceptibility', 'Susceptibility', 'Whether an attempt succeeds against the controls.'],
  ['primary', 'Primary loss', 'What one event costs the organization directly.'],
  ['secondary', 'Secondary loss', 'Reactions from customers, regulators and partners, and what they cost.'],
]

interface Props {
  risk: RegisterRiskDetail
  agent: AgentStatus | null
  reload: () => void
  onShowRequests: () => void
}

/** Task 5: cited evidence for each factor group, with data requests for the gaps. */
export function EvidenceTab({ risk, agent, reload, onShowRequests }: Props) {
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const run = risk.evidenceRun
  const last = risk.runs[0]

  async function start() {
    setStarting(true)
    setError(null)
    try {
      await api.startRiskTask(risk.riskId, 'evidence')
      reload()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setStarting(false)
    }
  }

  const openRequests = (g: FactorGroup) => risk.dataRequests.filter((r) => r.groups.includes(g) && r.status === 'open')

  return (
    <div className="intake">
      <TaskBar
        label="Gather evidence"
        againLabel="Gather again"
        hasDraft={!!run}
        blocked={risk.blocked.evidence}
        running={risk.agent.state === 'running'}
        agentOff={agent && !agent.configured ? agent.reason : null}
        busy={starting}
        onRun={() => void start()}
      />
      {error && (
        <div className="check error" role="alert">
          {error}
        </div>
      )}
      {last?.task === 'evidence' && last.status === 'failed' && (
        <div className="check error">The last attempt failed: {last.error}</div>
      )}
      {!run && risk.evidence.length === 0 ? (
        <p className="muted">No evidence gathered yet.</p>
      ) : (
        <>
          {run && (
            <p className="muted small">
              Gathered {run.finishedAt ? dateTime(run.finishedAt) : ''}: {risk.evidence.length} item
              {risk.evidence.length === 1 ? '' : 's'} from {run.toolCalls ?? '?'} tool call
              {run.toolCalls === 1 ? '' : 's'}.{' '}
              {run.notes.cveLookupsOffered === false &&
                'No vulnerability-database lookups: they apply only to malicious threats with external sources on.'}
            </p>
          )}
          {run && run.rejected.length > 0 && (
            <details className="more">
              <summary>
                {run.rejected.length} item{run.rejected.length === 1 ? ' was' : 's were'} rejected because no tool
                returned the citation
              </summary>
              <ul className="gaps small">
                {run.rejected.map((r, i) => (
                  <li key={i}>
                    <span className="mono">{r.citation}</span> {r.summary && `: ${r.summary}`}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {GROUPS.map(([g, label, about]) => {
            const items = risk.evidence.filter((e) => e.groups.includes(g))
            const reqs = openRequests(g)
            return (
              <section key={g} className="evgroup" aria-labelledby={`ev-${g}`}>
                <h3 id={`ev-${g}`}>
                  {label} <span className="muted small">· {items.length} item{items.length === 1 ? '' : 's'}</span>
                </h3>
                <p className="cap">{about}</p>
                {items.length === 0 && (
                  <p className="muted small">
                    No evidence found.{' '}
                    {reqs.length > 0 && (
                      <button type="button" className="linkbtn" onClick={onShowRequests}>
                        {reqs.length} data request{reqs.length === 1 ? '' : 's'} raised
                      </button>
                    )}
                  </p>
                )}
                <ul className="evlist">
                  {items.map((e) => (
                    <EvidenceRow key={`${g}-${e.id}`} e={e} />
                  ))}
                </ul>
              </section>
            )
          })}
          <p className="cap">
            Each item cites a record or page a tool returned in this run; the agent can’t add a source of its own.
            Check them before estimates rely on them.
          </p>
        </>
      )}
    </div>
  )
}

function EvidenceRow({ e }: { e: EvidenceItem }) {
  const { factors } = useContent()
  const isUrl = e.citation.startsWith('https://')
  return (
    <li className="evitem">
      <div className="evhead">
        <b>{e.sourceName}</b>
        <span className={`tag ${e.origin === 'internal' ? 'ok' : ''}`}>{e.origin === 'internal' ? 'Internal' : 'External'}</span>
        {e.stale && (
          <span className="tag warn" title="Published more than 24 months ago">
            Stale
          </span>
        )}
        {e.fromDataRequest && <span className="tag">Data request answer</span>}
      </div>
      <p>{e.summary}</p>
      {e.value != null && (
        <p className="small">
          <b>{e.value.toLocaleString('en-US')}</b> {e.unit}
        </p>
      )}
      <div className="small muted">
        Informs: {e.factors.map((f) => factors[f]?.label ?? f).join(', ')}
        {e.publishedAt && ` · dated ${e.publishedAt}`}
      </div>
      <div className="small">
        Source:{' '}
        {isUrl ? (
          <a href={e.citation} target="_blank" rel="noreferrer noopener" className="mono">
            {e.citation}
          </a>
        ) : (
          <span className="mono">{e.citation}</span>
        )}
      </div>
    </li>
  )
}

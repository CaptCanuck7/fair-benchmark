import { useState } from 'react'
import type { AgentStatus, CoverageReason, EvidenceItem, FactorGroup, RegisterRiskDetail, SourceCoverage } from '../types'
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
          {run?.coverage && <SourcesChecked coverage={run.coverage} />}
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

/** "Value not found in source" when the agent's number isn't in the record it cites. */
export function ValueCheckTag({ e }: { e: EvidenceItem }) {
  if (e.valueCheck !== 'not_found') return null
  return (
    <span className="tag warn" title="The value may be derived (for example hours times a rate) or mistranscribed. Compare it with the source record.">
      Value not found in source
    </span>
  )
}

/** The cited record's fields, for internal items, to compare with the agent's summary and value. */
export function SourceRecord({ e }: { e: EvidenceItem }) {
  if (e.origin !== 'internal' || !e.sourceFields) return null
  return (
    <details className="more source">
      <summary>Source record</summary>
      <dl className="fields">
        {Object.entries(e.sourceFields).map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{typeof v === 'number' ? v.toLocaleString('en-US') : String(v)}</dd>
          </div>
        ))}
      </dl>
    </details>
  )
}

const SOURCES: [string, string[]][] = [
  ['Internal records', ['internal_records']],
  ['Reference library', ['library_lookup']],
  ['Vulnerability feeds (NVD, KEV, EPSS)', ['nvd_search', 'kev_check', 'epss_scores']],
  ['MITRE ATT&CK', ['attack_techniques']],
  ['Web search', ['web_search']],
  ['Page fetch', ['web_fetch']],
]
const REASONS: Record<CoverageReason, string> = {
  external_off: 'external sources are off',
  threat_type: 'not offered for this threat type',
  budget: 'the tool budget ran out',
  blocked: 'blocked by the outbound guard',
  failed: 'the source couldn’t be reached',
  not_called: 'a required lookup the agent didn’t make',
}

/** One line per source: checked (with lookups), checked with nothing found, or not checked and why. */
export function SourcesChecked({ coverage }: { coverage: SourceCoverage }) {
  return (
    <div className="sources">
      <h3 className="small">Sources checked</h3>
      <ul>
        {SOURCES.map(([label, names]) => {
          const ts = names.map((n) => coverage.tools[n]).filter(Boolean)
          if (!ts.length) return null
          const checks = ts.reduce((s, t) => s + t.checks, 0)
          const items = ts.reduce((s, t) => s + t.items, 0)
          const reason = ts.map((t) => t.reason).find((r) => r) ?? null
          const required = ts.some((t) => t.required)
          const lookups = `${checks} lookup${checks === 1 ? '' : 's'}`
          let status: string
          if (checks > 0 && names[0] === 'library_lookup' && coverage.libraryEmpty) {
            status = 'Checked, the library has no approved figures yet.'
          } else if (checks > 0) {
            status = items > 0 ? `Checked, ${lookups}` : `Checked, nothing found (${lookups})`
          } else {
            status = `Not checked${reason ? `: ${REASONS[reason]}` : ''}`
          }
          return (
            <li key={label} className={checks > 0 ? '' : 'notchecked'}>
              <b>{label}</b>
              {required && <span className="tag">Required</span>} <span>{status}</span>
            </li>
          )
        })}
      </ul>
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
        <ValueCheckTag e={e} />
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
      <SourceRecord e={e} />
    </li>
  )
}

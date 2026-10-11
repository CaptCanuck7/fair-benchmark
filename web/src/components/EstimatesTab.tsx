import { useState } from 'react'
import type { AgentStatus, Conf, EstimateFactor, EvidenceItem, Kind, RangeValue, RegisterRiskDetail } from '../types'
import { api, ApiError } from '../api/client'
import { useContent } from '../content'
import { dateTime, fmtVal } from '../lib/format'
import { distStatus } from '../lib/model'
import { TaskBar } from './DraftControls'
import { SourceRecord, ValueCheckTag } from './EvidenceTab'
import { NumberInput } from './NumberInput'

const METHOD: Record<string, string> = {
  tef_vuln: 'Threat event frequency × vulnerability',
  cf_poa: 'Contact frequency × probability of action × vulnerability',
  lef: 'Loss event frequency directly',
}
const BOUNDS = [
  ['min', 'Minimum'],
  ['ml', 'Most likely'],
  ['max', 'Maximum'],
] as const

interface Props {
  risk: RegisterRiskDetail
  agent: AgentStatus | null
  onRisk: (r: RegisterRiskDetail) => void
  reload: () => void
  navigate: (path: string) => void
}

/** Task 6 behind the anchoring guard: evidence and your range first, the agent's range on request. */
export function EstimatesTab({ risk, agent, onRisk, reload, navigate }: Props) {
  const est = risk.estimates
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // The create-analysis refusal for out-of-date estimates, offering "Create anyway".
  const [staleBlock, setStaleBlock] = useState<string | null>(null)
  const changed = est ? [est.stale.scenario && 'the scenario', est.stale.evidence && 'the evidence'].filter(Boolean).join(' and ') : ''

  async function create(acknowledgeStale: boolean) {
    setStaleBlock(null)
    await act(async () => {
      try {
        const r = await api.analysisFromRisk(risk.riskId, acknowledgeStale)
        navigate(`/analyses/${r.analysisId}`)
      } catch (e) {
        if (e instanceof ApiError && e.status === 409 && changed && !acknowledgeStale) setStaleBlock(e.message)
        else throw e
      }
    })
  }

  async function act(fn: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="intake">
      <TaskBar
        label="Draft estimates"
        againLabel="Draft again"
        hasDraft={!!est}
        blocked={risk.blocked.estimates}
        running={risk.agent.state === 'running'}
        agentOff={agent && !agent.configured ? agent.reason : null}
        busy={busy}
        onRun={() => void act(async () => { await api.startRiskTask(risk.riskId, 'estimates'); reload() })}
      />
      {risk.runs[0]?.task === 'estimates' && risk.runs[0].status === 'failed' && (
        <div className="check error">The last attempt failed: {risk.runs[0].error}</div>
      )}
      {error && (
        <div className="check error" role="alert">
          {error}
        </div>
      )}
      {!est ? (
        <p className="muted">No estimates yet.</p>
      ) : (
        <>
          <div className="method">
            <b>Recommended frequency method:</b> {METHOD[est.method.mode]}
            {est.method.mode !== 'lef' && (est.method.vuln_mode === 'direct' ? ', vulnerability estimated directly' :
              ', vulnerability from threat capability and resistance strength')}
            . <span className="muted">{est.method.reason}</span>
          </div>
          {changed && (
            <div className="check warn" role="status">
              <b>Out of date:</b> {changed} changed after these estimates were drafted
              {est.stale.evidence && ' (a new evidence run, or an answered data request)'}. Your decided ranges are kept
              and still usable.{' '}
              <button
                type="button"
                className="btn quiet"
                disabled={busy || !!risk.blocked.estimates || risk.agent.state === 'running'}
                onClick={() => void act(async () => { await api.startRiskTask(risk.riskId, 'estimates'); reload() })}
              >
                Draft estimates again
              </button>
            </div>
          )}
          <p className="cap">
            For each factor, read the evidence and enter your own range first. Then show the agent’s range if you want
            to compare. Only the ranges you decide are used when you create the analysis.
          </p>
          {est.factors.map((f) => (
            <FactorEstimate key={`${est.draftId}-${f.factor}`} risk={risk} f={f} busy={busy} act={act} onRisk={onRisk} />
          ))}

          <section className="create" aria-labelledby="create-h">
            <h3 id="create-h">Create analysis</h3>
            <p className="small">
              Uses the approved scenario as the scope and the {est.decided} factor{est.decided === 1 ? '' : 's'} you
              decided as the current state. Factors you haven’t decided stay empty. No treatment option is created: build
              the residual state from the mitigation plan in the workspace.
            </p>
            <div className="row">
              <button
                type="button"
                className="btn primary"
                disabled={busy}
                onClick={() => void create(false)}
              >
                Create analysis
              </button>
              {risk.analysisId && (
                <a
                  className="btn quiet"
                  href={`/analyses/${risk.analysisId}`}
                  onClick={(e) => {
                    e.preventDefault()
                    navigate(`/analyses/${risk.analysisId}`)
                  }}
                >
                  Open the last analysis created from this risk
                </a>
              )}
            </div>
            {staleBlock && (
              <div className="check warn" role="alert">
                {staleBlock}{' '}
                <button type="button" className="btn" disabled={busy} onClick={() => void create(true)}>
                  Create anyway
                </button>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}

const empty = (): RangeValue => ({ min: null, ml: null, max: null, conf: 'med' })

function FactorEstimate({
  risk,
  f,
  busy,
  act,
  onRisk,
}: {
  risk: RegisterRiskDetail
  f: EstimateFactor
  busy: boolean
  act: (fn: () => Promise<void>) => Promise<void>
  onRisk: (r: RegisterRiskDetail) => void
}) {
  const content = useContent()
  const info = content.factors[f.factor]
  const kind = info.kind as Kind
  const [mine, setMine] = useState<RangeValue>(() => f.reveal?.analystRange ?? empty())
  const [inputKey, setInputKey] = useState(0)
  const status = distStatus({ ...mine, src: '' }, kind)
  const evidence = risk.evidence.filter((e) => e.factors.includes(f.factor))
  const request = f.unestimated?.dataRequestId != null ? risk.dataRequests.find((r) => r.id === f.unestimated?.dataRequestId) : null
  const cited = (ids: number[]) => risk.evidence.filter((e) => ids.includes(e.id))
  const fmt = (r: { min: number | null; ml: number | null; max: number | null }) =>
    `${fmtVal(kind, r.min)} / ${fmtVal(kind, r.ml)} / ${fmtVal(kind, r.max)}`

  const useMine = () => void act(async () => onRisk(await api.decideEstimate(risk.riskId, f.factor, 'analyst', mine)))

  return (
    <section className="estimate" aria-labelledby={`est-${f.factor}`}>
      <h4 id={`est-${f.factor}`}>
        {info.label} <span className="unit">{info.unit}</span>
      </h4>

      <EvidenceList items={evidence} />
      {f.status === 'unestimated' && (
        <p className="small">
          <b>No agent range:</b> {f.unestimated?.reason ?? 'The agent didn’t propose a range for this factor.'}
          {request && (
            <>
              {' '}Data request to {request.team}: “{request.question}”
              {request.status === 'answered' && ' (answered)'}
            </>
          )}
        </p>
      )}

      {f.decision ? (
        <div className="decided">
          <span className="draftlabel ok">
            {f.decision.choice === 'agent' ? 'Agent’s range' : 'Your range'}, approved by {f.decision.by} on{' '}
            {dateTime(f.decision.at)}
          </span>{' '}
          <b>{fmt(f.decision)}</b> <span className="muted small">· {content.confidence[f.decision.conf].label} confidence</span>
          <button type="button" className="btn quiet" disabled={busy}
                  onClick={() => void act(async () => onRisk(await api.clearEstimate(risk.riskId, f.factor)))}>
            Change
          </button>
        </div>
      ) : (
        <>
          <div className="dgrid">
            {BOUNDS.map(([k, label]) => (
              <label className="fld" key={`${k}-${inputKey}`}>
                <span>{label}</span>
                <NumberInput kind={kind} value={mine[k]} onValue={(v) => setMine((m) => ({ ...m, [k]: v }))} />
              </label>
            ))}
            <label className="fld conf">
              <span>Confidence</span>
              <select value={mine.conf} onChange={(e) => setMine((m) => ({ ...m, conf: e.target.value as Conf }))}>
                {(Object.keys(content.confidence) as Conf[]).map((c) => (
                  <option key={c} value={c}>
                    {content.confidence[c].label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {status.state === 'error' && <div className="dmsg">{status.msg}</div>}

          {f.revealed && f.agent ? (
            <div className="compare-ranges">
              <table className="ctl">
                <thead>
                  <tr>
                    <th scope="col">Range</th>
                    <th scope="col">Min / most likely / max</th>
                    <th scope="col">Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th scope="row">
                      Yours{f.reveal?.enteredBeforeReveal ? ' (entered before revealing)' : ''}
                    </th>
                    <td>{status.state === 'ok' ? fmt(mine) : '—'}</td>
                    <td>{status.state === 'ok' ? content.confidence[mine.conf].label : '—'}</td>
                  </tr>
                  <tr>
                    <th scope="row">
                      Agent’s ({f.agent.basis} evidence)
                      {f.agent.evidenceMatch === 'related' && <span className="tag warn">Rests on related evidence</span>}
                    </th>
                    <td>{fmt(f.agent)}</td>
                    <td>{content.confidence[f.agent.conf].label}</td>
                  </tr>
                </tbody>
              </table>
              <p className="small"><b>Agent’s rationale:</b> {f.agent.rationale}</p>
              {f.agent.evidenceMatch === 'related' ? (
                <div className="check warn small">
                  <b>Rests on related evidence.</b> None of the cited items is tagged to this factor; the agent used
                  these from the same group, so its confidence is capped at low:
                  <ul className="gaps">
                    {cited(f.agent.evidenceIds).map((e) => (
                      <li key={e.id}>
                        {e.summary} <span className="mono muted">{e.citation}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="small muted">Cites: {cited(f.agent.evidenceIds).map((e) => e.citation).join('; ') || '—'}</p>
              )}
              <div className="draftactions">
                <button type="button" className="btn" disabled={busy || status.state !== 'ok'} onClick={useMine}>
                  Keep mine
                </button>
                <button type="button" className="btn primary" disabled={busy}
                        onClick={() => void act(async () => onRisk(await api.decideEstimate(risk.riskId, f.factor, 'agent')))}>
                  Take the agent’s
                </button>
                <button type="button" className="btn quiet" disabled={busy}
                        onClick={() => { setMine(empty()); setInputKey((k) => k + 1) }}>
                  Enter a third
                </button>
              </div>
            </div>
          ) : (
            <div className="draftactions">
              <button type="button" className="btn" disabled={busy || status.state !== 'ok'} onClick={useMine}>
                Use my range
              </button>
              {f.status === 'estimated' && (
                <button
                  type="button"
                  className="btn quiet"
                  disabled={busy || status.state === 'error'}
                  onClick={() =>
                    void act(async () =>
                      onRisk(await api.revealEstimate(risk.riskId, f.factor, status.state === 'ok' ? mine : null)),
                    )
                  }
                >
                  Show agent range
                </button>
              )}
            </div>
          )}
        </>
      )}
    </section>
  )
}

function EvidenceList({ items }: { items: EvidenceItem[] }) {
  if (!items.length) return <p className="muted small">No evidence tagged to this factor.</p>
  return (
    <details className="more" open>
      <summary>Evidence for this factor ({items.length})</summary>
      <ul className="gaps small">
        {items.map((e) => (
          <li key={e.id}>
            <span className={`tag ${e.origin === 'internal' ? 'ok' : ''}`}>{e.origin === 'internal' ? 'Internal' : 'External'}</span>{' '}
            {e.stale && <span className="tag warn">Stale</span>} <ValueCheckTag e={e} /> {e.summary}
            {e.value != null && (
              <b>
                {' '}
                ({e.value.toLocaleString('en-US')} {e.unit})
              </b>
            )}{' '}
            <span className="mono muted">{e.citation}</span>
            <SourceRecord e={e} />
          </li>
        ))}
      </ul>
    </details>
  )
}

import { useState, type FormEvent } from 'react'
import type {
  AgentRun,
  AgentStatus,
  Draft,
  QualityResult,
  RegisterRiskDetail,
  TriageResult,
  TriageStatus,
} from '../types'
import { api, ApiError } from '../api/client'
import { dateTime } from '../lib/format'
import { CONFIDENCE, conditionLabel, gapFieldLabel, QUALITY, TRIAGE } from '../lib/register'

interface Props {
  risk: RegisterRiskDetail
  agent: AgentStatus | null
  /** Replace the risk after an action, or reload it. */
  onRisk: (r: RegisterRiskDetail) => void
  reload: () => void
}

const TASK_LABEL: Record<string, string> = { quality: 'Quality check', triage: 'Triage', classification: 'Condition type' }

/** The quality check, triage and condition type for one risk (pipeline steps 1 to 3). */
export function QualityTab({ risk, agent, onRisk, reload }: Props) {
  const { quality, triage, classification } = risk.intake
  const running = risk.agent.state === 'running'
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function rerun() {
    setBusy(true)
    setError(null)
    try {
      await api.rerunIntake(risk.riskId)
      reload()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="intake">
      <div className="agentbar">
        <div role="status" aria-live="polite">
          {running ? (
            <span>Checking this risk now…</span>
          ) : risk.agent.state === 'failed' ? (
            <span className="err">The last check failed: {risk.agent.error}</span>
          ) : quality ? (
            <span className="muted small">Checked {quality.draftedAt ? dateTime(quality.draftedAt) : ''}.</span>
          ) : (
            <span className="muted small">Not checked yet.</span>
          )}
        </div>
        <button
          type="button"
          className="btn"
          disabled={busy || running || !agent?.configured}
          title={agent && !agent.configured ? (agent.reason ?? undefined) : undefined}
          onClick={() => void rerun()}
        >
          {quality ? 'Run checks again' : 'Run checks'}
        </button>
      </div>
      {error && (
        <div className="check error" role="alert">
          {error}
        </div>
      )}

      <h3>Quality check</h3>
      {quality ? <QualityView draft={quality} /> : <p className="muted">Not run yet.</p>}

      <h3>Triage</h3>
      {triage ? (
        <TriageView draft={triage} risk={risk} onRisk={onRisk} />
      ) : quality?.effective.status === 'needs_info' ? (
        <p className="muted">Not run. Triage waits until the quality check finds the entry ready.</p>
      ) : (
        <p className="muted">Not run yet.</p>
      )}

      <h3>Condition type</h3>
      {classification ? (
        <>
          <DraftLabel draft={classification} />
          <p>
            <b>{conditionLabel(classification.effective.primary_type)}</b>
            {classification.effective.secondary_type && (
              <> and {conditionLabel(classification.effective.secondary_type).toLowerCase()}</>
            )}
            <span className="muted"> · {CONFIDENCE[classification.effective.confidence]} confidence</span>
          </p>
          <p>{classification.effective.reason}</p>
          <p className="cap">The condition type decides where evidence gathering looks first.</p>
        </>
      ) : (triage && triage.effective.status !== 'qualifies') || quality?.effective.status === 'needs_info' ? (
        <p className="muted">Not run. Only risks that are ready and qualify go on to classification.</p>
      ) : (
        <p className="muted">Not run yet.</p>
      )}

      <RunList runs={risk.runs} />
    </div>
  )
}

function DraftLabel({ draft }: { draft: Draft<unknown> }) {
  if (draft.status === 'approved' || draft.status === 'edited') {
    return (
      <p className="draftlabel ok">
        {draft.status === 'edited' ? 'Changed' : 'Approved'} by {draft.reviewer}
        {draft.reviewedAt ? ` on ${dateTime(draft.reviewedAt)}` : ''}
      </p>
    )
  }
  return <p className="draftlabel">Agent draft</p>
}

function QualityView({ draft }: { draft: Draft<QualityResult> }) {
  const q = draft.effective
  const checks: [boolean, string][] = [
    [q.checks.namesAsset, 'what is at risk'],
    [q.checks.namesCondition, 'the weakness behind the risk'],
    [q.checks.namesLossPath, 'how loss could happen'],
  ]
  return (
    <>
      <DraftLabel draft={draft} />
      <p>
        <span className={`badge ${q.status}`}>{QUALITY[q.status]}</span>{' '}
        {q.status === 'ready'
          ? 'The entry has enough to scope a loss scenario.'
          : 'The entry needs more information before a scenario can be drafted.'}
      </p>
      <ul className="checklist" aria-label="What the analysis names">
        {checks.map(([ok, label]) => (
          <li key={label} className={ok ? 'yes' : 'no'}>
            <span aria-hidden="true">{ok ? '✓' : '✗'}</span> {ok ? 'Names' : 'Doesn’t clearly name'} {label}
          </li>
        ))}
      </ul>
      {q.gaps.length > 0 && (
        <>
          <h4>Missing or unclear</h4>
          <ul className="gaps">
            {q.gaps.map((g, i) => (
              <li key={i}>
                <b>{gapFieldLabel(g.field)}:</b> {g.problem}{' '}
                <span className="tag">{g.source === 'rule' ? 'automatic check' : 'agent'}</span>
                {g.blocking && <span className="tag warn">blocks</span>}
              </li>
            ))}
          </ul>
          {!q.wouldQualify && q.status === 'ready' && (
            <p className="cap">
              These don’t block this risk: it scores below the triage threshold, so triage will screen it out unless
              you override.
            </p>
          )}
        </>
      )}
      {q.questions.length > 0 && (
        <>
          <h4>Questions for you</h4>
          <ol className="questions">
            {q.questions.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ol>
        </>
      )}
    </>
  )
}

function TriageView({
  draft,
  risk,
  onRisk,
}: {
  draft: Draft<TriageResult>
  risk: RegisterRiskDetail
  onRisk: (r: RegisterRiskDetail) => void
}) {
  const t = draft.effective
  const other: TriageStatus = t.status === 'qualifies' ? 'screened_out' : 'qualifies'
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (reason.trim().length < 3) {
      setError('Give a reason for the override.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const r = await api.triageOverride(risk.riskId, { status: other, reason: reason.trim() })
      onRisk(r)
      setOpen(false)
      setReason('')
      setNote(
        r.classificationNote
          ? `Overridden. The condition type wasn’t drafted because the agent is off: ${r.classificationNote}`
          : null,
      )
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <DraftLabel draft={draft} />
      <p>
        <span className={`badge ${t.status}`}>{TRIAGE[t.status]}</span>{' '}
        {t.override ? `Overridden from “${TRIAGE[t.override.from].toLowerCase()}”.` : t.rule}
      </p>
      {t.override && (
        <p>
          <b>Reason for the override:</b> {t.override.reason}
          <span className="muted small"> The rule said: {draft.payload.rule}</span>
        </p>
      )}
      {t.reason && <p>{t.reason}</p>}
      {t.noteError && <p className="muted small">The agent couldn’t write an explanation: {t.noteError}</p>}
      {t.advisory && (
        <div className="check info">
          <b>Advisory from the agent:</b> {t.advisory} It doesn’t change the result.
        </div>
      )}
      {note && <p className="muted small">{note}</p>}
      {!open ? (
        <button type="button" className="btn quiet" onClick={() => setOpen(true)}>
          Override triage
        </button>
      ) : (
        <form className="override" onSubmit={(e) => void submit(e)}>
          <p>
            Change this risk to <b>{TRIAGE[other].toLowerCase()}</b>. The reason is recorded with your name.
          </p>
          <label className="fld">
            <span>Reason</span>
            <textarea
              rows={2}
              value={reason}
              required
              aria-invalid={error ? true : undefined}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          {error && (
            <p className="err small" role="alert">
              {error}
            </p>
          )}
          <div className="row">
            <button type="submit" className="btn primary" disabled={busy}>
              Override to {TRIAGE[other].toLowerCase()}
            </button>
            <button type="button" className="btn quiet" onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </>
  )
}

function RunList({ runs }: { runs: AgentRun[] }) {
  if (!runs.length) return null
  return (
    <details className="more">
      <summary>Agent runs for this risk</summary>
      <div className="tblwrap">
        <table className="runs-tbl">
          <thead>
            <tr>
              <th scope="col">Step</th>
              <th scope="col">Status</th>
              <th scope="col">Started</th>
              <th scope="col">Model and prompt</th>
              <th scope="col" className="num">
                Tokens in / out
              </th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <th scope="row">{TASK_LABEL[r.task] ?? r.task}</th>
                <td>
                  {r.status}
                  {r.error && <div className="small err">{r.error}</div>}
                </td>
                <td>{dateTime(r.startedAt)}</td>
                <td className="mono">
                  {r.model ?? '—'} · {r.promptVersion ?? '—'}
                </td>
                <td className="num">
                  {r.inputTokens.toLocaleString('en-US')} / {r.outputTokens.toLocaleString('en-US')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}

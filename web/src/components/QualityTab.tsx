import { useState, type FormEvent } from 'react'
import type {
  AgentRun,
  AgentStatus,
  ClassificationResult,
  Draft,
  QualityResult,
  RegisterRiskDetail,
  TriageResult,
  TriageStatus,
} from '../types'
import { api, ApiError } from '../api/client'
import { dateTime } from '../lib/format'
import { CONDITION, CONFIDENCE, conditionLabel, gapFieldLabel, QUALITY, TRIAGE } from '../lib/register'
import { DraftActions, DraftLabel, ReasonField, reasonOk, ReviewError, useReview } from './DraftControls'

interface Props {
  risk: RegisterRiskDetail
  agent: AgentStatus | null
  /** Replace the risk after an action, or reload it. */
  onRisk: (r: RegisterRiskDetail) => void
  reload: () => void
}

const TASK_LABEL: Record<string, string> = {
  quality: 'Quality check',
  triage: 'Triage',
  classification: 'Condition type',
  scenario: 'Scenario',
  vectors: 'Vectors',
}

/** The intake checks' status, the last failure, and "Run checks again". */
export function IntakeBar({ risk, agent, reload }: Omit<Props, 'onRisk'>) {
  const quality = risk.intake.quality
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
    <>
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
    </>
  )
}

/** Review props shared by the intake views. `onContinue` runs after an approval succeeds. */
interface StepProps {
  onRisk: (r: RegisterRiskDetail) => void
  onContinue?: () => void
}

/** Approve, reject (with a reason) or edit, then continue after an approval. */
function reviewAndContinue(r: ReturnType<typeof useReview>, draftId: number, onContinue?: () => void) {
  return (a: 'approve' | 'reject', why?: string) =>
    void r.review(draftId, a, undefined, why).then((ok) => {
      if (ok && a === 'approve') onContinue?.()
    })
}

export function QualityView({ draft, onRisk, onContinue }: { draft: Draft<QualityResult> } & StepProps) {
  const q = draft.effective
  const r = useReview(onRisk)
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
      <DraftActions
        draft={draft}
        actions={['approve', 'reject']}
        busy={r.busy}
        onAction={reviewAndContinue(r, draft.id, onContinue)}
        needsReason
        approveLabel={onContinue ? 'Approve and continue' : undefined}
      />
      <ReviewError error={r.error} fieldErrors={r.fieldErrors} />
    </>
  )
}

export function ClassificationView({ draft, onRisk, onContinue }: { draft: Draft<ClassificationResult> } & StepProps) {
  const c = draft.effective
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<ClassificationResult>(c)
  const [reason, setReason] = useState('')
  const [tried, setTried] = useState(false)
  const r = useReview((x) => {
    onRisk(x)
    setEditing(false)
  })
  return (
    <>
      <DraftLabel draft={draft} />
      {editing ? (
        <form
          className="editor"
          onSubmit={(e) => {
            e.preventDefault()
            setTried(true)
            if (!reasonOk(reason)) return
            void r.review(draft.id, 'edit', { ...form, secondary_type: form.secondary_type || null }, reason.trim())
          }}
        >
          <div className="grid2">
            <label className="fld">
              <span>Condition type</span>
              <select value={form.primary_type} onChange={(e) => setForm({ ...form, primary_type: e.target.value })}>
                {Object.entries(CONDITION).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <label className="fld">
              <span>Also (optional)</span>
              <select
                value={form.secondary_type ?? ''}
                onChange={(e) => setForm({ ...form, secondary_type: e.target.value || null })}
              >
                <option value="">None</option>
                {Object.entries(CONDITION).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <label className="fld">
              <span>Confidence</span>
              <select
                value={form.confidence}
                onChange={(e) => setForm({ ...form, confidence: e.target.value as ClassificationResult['confidence'] })}
              >
                {Object.entries(CONFIDENCE).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="fld">
            <span>Reason</span>
            <textarea rows={2} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          </label>
          <ReasonField label="Why are you changing it?" value={reason} onChange={setReason} showError={tried} />
          <div className="row">
            <button type="submit" className="btn primary" disabled={r.busy}>
              Save and approve
            </button>
            <button type="button" className="btn quiet" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <>
          <p>
            <b>{conditionLabel(c.primary_type)}</b>
            {c.secondary_type && <> and {conditionLabel(c.secondary_type).toLowerCase()}</>}
            <span className="muted"> · {CONFIDENCE[c.confidence]} confidence</span>
          </p>
          <p>{c.reason}</p>
          <p className="cap">The condition type decides where evidence gathering looks first.</p>
          <DraftActions
            draft={draft}
            actions={['approve', 'edit', 'reject']}
            busy={r.busy}
            onAction={reviewAndContinue(r, draft.id, onContinue)}
            needsReason
            approveLabel={onContinue ? 'Approve and continue' : undefined}
            onEdit={() => {
              setForm(c)
              setReason('')
              setTried(false)
              setEditing(true)
            }}
          />
        </>
      )}
      <ReviewError error={r.error} fieldErrors={r.fieldErrors} />
    </>
  )
}

export function TriageView({
  draft,
  risk,
  onRisk,
  onContinue,
}: { draft: Draft<TriageResult>; risk: RegisterRiskDetail } & StepProps) {
  const t = draft.effective
  const r = useReview(onRisk)
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
        <div className="draftactions">
          {draft.status === 'drafted' && (
            <button type="button" className="btn primary" disabled={r.busy} onClick={() => reviewAndContinue(r, draft.id, onContinue)('approve')}>
              {onContinue ? 'Approve and continue' : 'Approve'}
            </button>
          )}
          <button type="button" className="btn quiet" onClick={() => setOpen(true)}>
            Override triage
          </button>
        </div>
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
      <ReviewError error={r.error} fieldErrors={r.fieldErrors} />
    </>
  )
}

export function RunList({ runs }: { runs: AgentRun[] }) {
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

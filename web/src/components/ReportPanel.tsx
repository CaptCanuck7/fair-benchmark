import { useEffect, useState } from 'react'
import type { AnalysisAgent } from '../hooks/useAnalysisAgent'
import { DraftActions, DraftLabel } from './DraftControls'

interface Props {
  agent: AnalysisAgent
  /** The stored run whose results are shown, or null before the first run. */
  runId: string | null
  /** The inputs changed after this run. */
  stale: boolean
}

const paragraphs = (text: string) => text.split(/\n\s*\n|\n/).filter((p) => p.trim())

/** "Draft report" in the results (task 7): a leadership summary and an exception justification. */
export function ReportPanel({ agent, runId, stale }: Props) {
  const draft = runId ? (agent.view?.reports[runId] ?? null) : null
  const last = agent.view?.runs.find((r) => r.task === 'report')
  const working = last && (last.status === 'queued' || last.status === 'running')
  const [editing, setEditing] = useState(false)
  const [summary, setSummary] = useState('')
  const [justification, setJustification] = useState('')
  useEffect(() => setEditing(false), [runId])

  if (!runId) return null
  const startEdit = () => {
    if (!draft) return
    setSummary(draft.effective.leadershipSummary)
    setJustification(draft.effective.exceptionJustification ?? '')
    setEditing(true)
  }

  return (
    <div className="report" aria-labelledby="report-h">
      <h3 id="report-h">Report for leaders</h3>
      <p className="cap">
        The agent drafts a leadership summary from this run and, when there is a treatment option, an exception
        justification comparing it with the current state. Every number in the draft is checked against the run; a
        draft with a number that doesn’t match is discarded.
      </p>
      {stale && <p className="small muted">This report describes the run shown, not your latest inputs.</p>}
      <div className="row">
        <button
          type="button"
          className="btn"
          disabled={agent.busy || !!agent.off}
          title={agent.off ?? undefined}
          onClick={() => void agent.report(runId)}
        >
          {draft ? 'Draft again' : 'Draft report'}
        </button>
        {agent.off && <span className="small muted">{agent.off}</span>}
      </div>
      {working && <p className="muted" role="status">The agent is drafting the report…</p>}
      {!working && last?.status === 'failed' && <div className="check error">The last draft failed: {last.error}</div>}
      {draft && !editing && (
        <>
          <DraftLabel draft={draft} />
          {!!draft.numberCheck?.length && (
            <div className="check warn">
              These numbers aren’t in the run results or the analysis: {draft.numberCheck.join(', ')}. Check them before
              sharing.
            </div>
          )}
          <h4>Leadership summary</h4>
          {paragraphs(draft.effective.leadershipSummary).map((p, k) => (
            <p key={k}>{p}</p>
          ))}
          {draft.effective.exceptionJustification ? (
            <>
              <h4>Exception justification: current state and {draft.effective.residualName}</h4>
              {paragraphs(draft.effective.exceptionJustification).map((p, k) => (
                <p key={k}>{p}</p>
              ))}
            </>
          ) : (
            <p className="small muted">Add a treatment option and run again to draft an exception justification.</p>
          )}
          <DraftActions
            draft={draft}
            actions={['approve', 'edit', 'reject']}
            busy={agent.busy}
            onAction={(a) => void agent.decide(draft.id, a)}
            onEdit={startEdit}
          />
        </>
      )}
      {draft && editing && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void agent
              .decide(draft.id, 'edit', { leadershipSummary: summary, exceptionJustification: justification.trim() || null })
              .then(() => setEditing(false))
          }}
        >
          <label className="fld">
            <span>Leadership summary</span>
            <textarea rows={9} value={summary} onChange={(e) => setSummary(e.target.value)} required />
          </label>
          {draft.payload.exceptionJustification != null && (
            <label className="fld">
              <span>Exception justification</span>
              <textarea rows={7} value={justification} onChange={(e) => setJustification(e.target.value)} />
            </label>
          )}
          <div className="draftactions">
            <button type="submit" className="btn primary" disabled={agent.busy}>
              Save and approve
            </button>
            <button type="button" className="btn quiet" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {agent.error && (
        <div className="check error" role="alert">
          {agent.error}
        </div>
      )}
    </div>
  )
}

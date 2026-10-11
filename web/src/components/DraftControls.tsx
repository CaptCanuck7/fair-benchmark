import { useState } from 'react'
import type { Draft, RegisterRiskDetail, ReviewAction } from '../types'
import { api, ApiError, type FieldError } from '../api/client'
import { dateTime } from '../lib/format'

/** "Agent draft" until reviewed; then who approved, changed or rejected it, and when. */
export function DraftLabel({ draft }: { draft: Draft<unknown> }) {
  const when = draft.reviewedAt ? ` on ${dateTime(draft.reviewedAt)}` : ''
  if (draft.status === 'approved') return <p className="draftlabel ok">Approved by {draft.reviewer}{when}</p>
  if (draft.status === 'edited') return <p className="draftlabel ok">Edited and approved by {draft.reviewer}{when}</p>
  if (draft.status === 'rejected') return <p className="draftlabel rejected">Rejected by {draft.reviewer}{when}</p>
  return <p className="draftlabel">Agent draft</p>
}

/** Calls the review endpoint, reporting the updated risk or the error. */
export function useReview(onRisk: (r: RegisterRiskDetail) => void) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([])

  async function review(draftId: number, action: ReviewAction, payload?: unknown): Promise<boolean> {
    setBusy(true)
    setError(null)
    setFieldErrors([])
    try {
      onRisk(await api.reviewDraft(draftId, action, payload))
      return true
    } catch (e) {
      if (e instanceof ApiError) {
        setError(e.message)
        setFieldErrors(e.errors)
      } else setError(String(e))
      return false
    } finally {
      setBusy(false)
    }
  }
  return { review, busy, error, fieldErrors }
}

interface ActionsProps {
  draft: Draft<unknown>
  /** Which actions this kind of draft offers. */
  actions: ReviewAction[]
  busy: boolean
  onAction: (a: Exclude<ReviewAction, 'edit'>) => void
  onEdit?: () => void
}

/** Approve, Edit and Reject. Approve is hidden once the draft is approved or edited. */
export function DraftActions({ draft, actions, busy, onAction, onEdit }: ActionsProps) {
  const accepted = draft.status === 'approved' || draft.status === 'edited'
  return (
    <div className="draftactions">
      {actions.includes('approve') && !accepted && (
        <button type="button" className="btn primary" disabled={busy} onClick={() => onAction('approve')}>
          Approve
        </button>
      )}
      {actions.includes('edit') && onEdit && (
        <button type="button" className="btn" disabled={busy} onClick={onEdit}>
          Edit
        </button>
      )}
      {actions.includes('reject') && draft.status !== 'rejected' && (
        <button type="button" className="btn quiet danger" disabled={busy} onClick={() => onAction('reject')}>
          Reject
        </button>
      )}
    </div>
  )
}

/** Error from a review, with any field-level messages. */
export function ReviewError({ error, fieldErrors }: { error: string | null; fieldErrors: FieldError[] }) {
  if (!error) return null
  return (
    <div className="check error" role="alert">
      {error}
      {fieldErrors.length > 0 && (
        <ul className="small">
          {fieldErrors.map((e, i) => (
            <li key={i}>
              {e.path.replace(/^payload\./, '')}: {e.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** The run control for an analyst-started task: button, status, and why it can't run. */
export function TaskBar({
  label,
  againLabel,
  hasDraft,
  blocked,
  running,
  agentOff,
  onRun,
  busy,
}: {
  label: string
  againLabel: string
  hasDraft: boolean
  blocked: string | null
  running: boolean
  agentOff: string | null
  onRun: () => void
  busy: boolean
}) {
  const reason = agentOff ?? blocked
  return (
    <div className="agentbar">
      <div role="status" aria-live="polite" className="small">
        {running ? 'The agent is working on this risk…' : reason ? <span className="muted">{reason}</span> : null}
      </div>
      <button type="button" className="btn" disabled={busy || running || !!reason} onClick={onRun}>
        {hasDraft ? againLabel : label}
      </button>
    </div>
  )
}

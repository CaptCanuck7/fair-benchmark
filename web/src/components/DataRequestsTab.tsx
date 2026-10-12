import { useState } from 'react'
import type { DataRequest, RegisterRiskDetail } from '../types'
import { api, ApiError } from '../api/client'
import { useContent } from '../content'
import { dateTime } from '../lib/format'
import { GROUPS } from './EvidenceTab'

interface Props {
  risk: RegisterRiskDetail
  onRisk: (r: RegisterRiskDetail) => void
}

/** Questions for other teams where no evidence was found, and their answers. */
export function DataRequestsTab({ risk, onRisk }: Props) {
  const requests = risk.dataRequests
  if (!requests.length) {
    return (
      <p className="muted">
        {risk.evidenceRun ? 'No data requests: every part of the risk has some evidence.' : 'Gather evidence first.'}
      </p>
    )
  }
  const open = requests.filter((r) => r.status === 'open').length
  return (
    <div className="intake">
      <p className="muted small">
        {open} open, {requests.length - open} answered. An answer becomes internal evidence, cited as “Data request
        answered by {'{team}'} on {'{date}'}”.
      </p>
      <ul className="evlist">
        {requests.map((r) => (
          <RequestRow key={r.id} r={r} onRisk={onRisk} />
        ))}
      </ul>
    </div>
  )
}

export function RequestRow({ r, onRisk }: { r: DataRequest; onRisk: (x: RegisterRiskDetail) => void }) {
  const { factors } = useContent()
  const [editing, setEditing] = useState(r.status === 'open')
  const [text, setText] = useState(r.answer ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const group = GROUPS.find(([g]) => r.groups.includes(g))?.[1]

  async function save() {
    if (!text.trim()) {
      setError('Write the answer first.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      onRisk(await api.answerDataRequest(r.id, text.trim()))
      setEditing(false)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="evitem">
      <div className="evhead">
        <b>{r.team}</b>
        <span className={`tag ${r.status === 'answered' ? 'ok' : 'warn'}`}>{r.status === 'answered' ? 'Answered' : 'Open'}</span>
        {group && <span className="tag">{group}</span>}
      </div>
      <p>{r.question}</p>
      <div className="small muted">
        For: {factors[r.factor]?.label ?? r.factor}. {r.reason}
      </div>
      {r.status === 'answered' && !editing && (
        <div className="answer">
          <p className="prewrap">{r.answer}</p>
          <div className="small muted">
            Recorded by {r.answeredBy} on {r.answeredAt ? dateTime(r.answeredAt) : ''}.{' '}
            <button type="button" className="linkbtn" onClick={() => setEditing(true)}>
              Change answer
            </button>
          </div>
        </div>
      )}
      {editing && (
        <form
          className="override"
          onSubmit={(e) => {
            e.preventDefault()
            void save()
          }}
        >
          <label className="fld">
            <span>Answer from {r.team}</span>
            <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} />
          </label>
          {error && (
            <p className="err small" role="alert">
              {error}
            </p>
          )}
          <div className="row">
            <button type="submit" className="btn primary" disabled={busy}>
              Save answer
            </button>
            {r.status === 'answered' && (
              <button type="button" className="btn quiet" onClick={() => setEditing(false)}>
                Cancel
              </button>
            )}
          </div>
        </form>
      )}
    </li>
  )
}

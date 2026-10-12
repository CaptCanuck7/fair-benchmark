import { useState, type FormEvent } from 'react'
import type { AgentStatus, RegisterRiskDetail, ThreatPath, VectorsDraft } from '../types'
import { api, ApiError } from '../api/client'
import { DraftActions, DraftLabel, ReasonField, reasonOk, ReviewError, TaskBar, useReview } from './DraftControls'

const ORIGIN: Record<string, string> = {
  from_register: 'From the register',
  agent_drafted: 'Drafted by the agent',
  analyst: 'Added by the analyst',
}

interface Props {
  risk: RegisterRiskDetail
  agent: AgentStatus | null
  onRisk: (r: RegisterRiskDetail) => void
  reload: () => void
}

/** Task 4: attack vectors, or failure paths for non-malicious threat types. */
export function VectorsTab({ risk, agent, onRisk, reload }: Props) {
  const draft = risk.vectors
  const [editing, setEditing] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const r = useReview((x) => {
    onRisk(x)
    setEditing(false)
  })

  async function run() {
    setStarting(true)
    setRunError(null)
    try {
      await api.startRiskTask(risk.riskId, 'vectors')
      reload()
    } catch (e) {
      setRunError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="intake">
      <TaskBar
        label="Draft vectors"
        againLabel="Draft again"
        hasDraft={!!draft}
        blocked={risk.blocked.vectors}
        running={risk.agent.state === 'running'}
        agentOff={agent && !agent.configured ? agent.reason : null}
        busy={starting}
        onRun={() => void run()}
      />
      {runError && (
        <div className="check error" role="alert">
          {runError}
        </div>
      )}
      {risk.runs[0]?.task === 'vectors' && risk.runs[0].status === 'failed' && (
        <div className="check error">The last attempt failed: {risk.runs[0].error}</div>
      )}
      {draft && risk.vectorsStale && (
        <div className="banner">
          The scenario changed after these were drafted. Check they still fit, or draft them again.
        </div>
      )}
      {!draft ? (
        <p className="muted">No vectors yet.</p>
      ) : (
        <>
          <DraftLabel draft={draft} />
          {editing ? (
            <VectorsEditor
              initial={draft.effective}
              busy={r.busy}
              onCancel={() => setEditing(false)}
              onSave={(v, why) => void r.review(draft.id, 'edit', v, why)}
            />
          ) : (
            <>
              <VectorsView v={draft.effective} />
              <DraftActions
                draft={draft}
                actions={['approve', 'edit', 'reject']}
                busy={r.busy}
                onAction={(a, why) => void r.review(draft.id, a, undefined, why)}
                needsReason
                onEdit={() => setEditing(true)}
              />
            </>
          )}
          <ReviewError error={r.error} fieldErrors={r.fieldErrors} />
        </>
      )}
    </div>
  )
}

function VectorsView({ v }: { v: VectorsDraft }) {
  const failure = v.kind === 'failure_paths'
  return (
    <>
      <p className="muted small">
        {failure
          ? 'Failure paths: this scenario’s threat isn’t malicious, so these describe what fails and how it becomes a loss.'
          : 'Attack vectors: the ways a threat actor could reach the asset and cause the loss.'}
      </p>
      {v.paths.map((p, i) => (
        <section className="path" key={i} aria-labelledby={`path-${i}`}>
          <h4 id={`path-${i}`}>
            {i + 1}. {p.title} <span className="tag">{ORIGIN[p.origin] ?? p.origin}</span>
          </h4>
          {failure && p.what_fails && (
            <p>
              <b>What fails:</b> {p.what_fails}
            </p>
          )}
          <ol className="steps">
            {p.steps.map((s, j) => (
              <li key={j}>
                {s.text}
                {s.controls.length > 0 && (
                  <div className="small muted">Controls that matter here: {s.controls.join(', ')}</div>
                )}
              </li>
            ))}
          </ol>
          {failure && p.makes_worse.length > 0 && (
            <p className="small">
              <b>Makes it worse:</b> {p.makes_worse.join('; ')}
            </p>
          )}
          {failure && p.limits.length > 0 && (
            <p className="small">
              <b>Limits the damage:</b> {p.limits.join('; ')}
            </p>
          )}
        </section>
      ))}
    </>
  )
}

const split = (text: string, sep: RegExp) =>
  text
    .split(sep)
    .map((x) => x.trim())
    .filter(Boolean)

interface EditPath {
  title: string
  origin: ThreatPath['origin']
  steps: { text: string; controls: string }[]
  what_fails: string
  makes_worse: string
  limits: string
}

function VectorsEditor({
  initial,
  busy,
  onSave,
  onCancel,
}: {
  initial: VectorsDraft
  busy: boolean
  onSave: (v: VectorsDraft, reason: string) => void
  onCancel: () => void
}) {
  const failure = initial.kind === 'failure_paths'
  const [paths, setPaths] = useState<EditPath[]>(() =>
    initial.paths.map((p) => ({
      title: p.title,
      origin: p.origin,
      steps: p.steps.map((s) => ({ text: s.text, controls: s.controls.join(', ') })),
      what_fails: p.what_fails ?? '',
      makes_worse: p.makes_worse.join('\n'),
      limits: p.limits.join('\n'),
    })),
  )
  const setPath = (i: number, patch: Partial<EditPath>) =>
    setPaths((ps) => ps.map((p, j) => (j === i ? { ...p, ...patch } : p)))

  const [reason, setReason] = useState('')
  const [tried, setTried] = useState(false)

  function submit(e: FormEvent) {
    e.preventDefault()
    setTried(true)
    if (!reasonOk(reason)) return
    onSave({
      kind: initial.kind,
      paths: paths.map((p) => ({
        title: p.title.trim(),
        origin: p.origin,
        steps: p.steps
          .filter((s) => s.text.trim())
          .map((s) => ({ text: s.text.trim(), controls: split(s.controls, /,/) })),
        what_fails: failure ? p.what_fails.trim() || null : null,
        makes_worse: failure ? split(p.makes_worse, /\n/) : [],
        limits: failure ? split(p.limits, /\n/) : [],
      })),
    }, reason.trim())
  }

  return (
    <form className="editor" onSubmit={submit}>
      {paths.map((p, i) => (
        <fieldset className="rows" key={i}>
          <legend>{failure ? 'Failure path' : 'Attack vector'} {i + 1}</legend>
          <label className="fld">
            <span>Title</span>
            <input value={p.title} onChange={(e) => setPath(i, { title: e.target.value })} />
          </label>
          {failure && (
            <label className="fld">
              <span>What fails</span>
              <input value={p.what_fails} onChange={(e) => setPath(i, { what_fails: e.target.value })} />
            </label>
          )}
          {p.steps.map((s, j) => (
            <div className="ctlrow" key={j}>
              <label className="fld wide">
                <span>
                  Step {j + 1} of path {i + 1}
                </span>
                <textarea
                  rows={2}
                  value={s.text}
                  onChange={(e) =>
                    setPath(i, { steps: p.steps.map((x, k) => (k === j ? { ...x, text: e.target.value } : x)) })
                  }
                />
              </label>
              <label className="fld">
                <span>Controls that matter (comma-separated)</span>
                <input
                  value={s.controls}
                  onChange={(e) =>
                    setPath(i, { steps: p.steps.map((x, k) => (k === j ? { ...x, controls: e.target.value } : x)) })
                  }
                />
              </label>
              <button
                type="button"
                className="btn quiet danger"
                disabled={p.steps.length === 1}
                onClick={() => setPath(i, { steps: p.steps.filter((_, k) => k !== j) })}
              >
                Remove step {j + 1}
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn quiet"
            disabled={p.steps.length >= 8}
            onClick={() => setPath(i, { steps: [...p.steps, { text: '', controls: '' }] })}
          >
            Add a step
          </button>
          {failure && (
            <div className="grid2">
              <label className="fld">
                <span>Makes it worse (one per line)</span>
                <textarea rows={2} value={p.makes_worse} onChange={(e) => setPath(i, { makes_worse: e.target.value })} />
              </label>
              <label className="fld">
                <span>Limits the damage (one per line)</span>
                <textarea rows={2} value={p.limits} onChange={(e) => setPath(i, { limits: e.target.value })} />
              </label>
            </div>
          )}
          <button
            type="button"
            className="btn quiet danger"
            disabled={paths.length === 1}
            onClick={() => setPaths((ps) => ps.filter((_, k) => k !== i))}
          >
            Remove this path
          </button>
        </fieldset>
      ))}
      <button
        type="button"
        className="btn quiet"
        disabled={paths.length >= 6}
        onClick={() =>
          setPaths((ps) => [
            ...ps,
            { title: '', origin: 'analyst', steps: [{ text: '', controls: '' }], what_fails: '', makes_worse: '', limits: '' },
          ])
        }
      >
        Add a path
      </button>
      <ReasonField label="Why are you changing it?" value={reason} onChange={setReason} showError={tried} />
      <div className="row">
        <button type="submit" className="btn primary" disabled={busy}>
          Save and approve
        </button>
        <button type="button" className="btn quiet" onClick={onCancel}>
          Cancel
        </button>
      </div>
      <p className="cap">Your version is saved beside the agent’s draft, which is kept.</p>
    </form>
  )
}

import { useState, type FormEvent } from 'react'
import {
  EFFECTS_LIST,
  THREAT_TYPES_LIST,
  type AgentStatus,
  type ControlFactor,
  type RegisterRiskDetail,
  type ScenarioControl,
  type ScenarioDraft,
} from '../types'
import { api, ApiError } from '../api/client'
import { DraftActions, DraftLabel, ReasonField, reasonOk, ReviewError, TaskBar, useReview } from './DraftControls'

const FACTOR: Record<ControlFactor, string> = {
  frequency: 'How often the threat acts',
  susceptibility: 'Whether an attempt succeeds',
  magnitude: 'How much is lost',
}

const SPLIT: Record<string, string> = {
  threat_type_or_effect_differs: 'Different threat type or effect',
  data_exposure_differs: 'Very different amount of data exposed',
  mitigation_differs: 'The planned fixes affect it differently',
}

interface Props {
  risk: RegisterRiskDetail
  agent: AgentStatus | null
  onRisk: (r: RegisterRiskDetail) => void
  reload: () => void
  /** Runs after an approval succeeds (the guided page moves to the next step). */
  onContinue?: () => void
}

/** Task 3: the default loss-event scenario, with review and editing. */
export function ScenarioTab({ risk, agent, onRisk, reload, onContinue }: Props) {
  const draft = risk.scenario
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
      await api.startRiskTask(risk.riskId, 'scenario')
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
        label="Draft scenario"
        againLabel="Draft again"
        hasDraft={!!draft}
        blocked={risk.blocked.scenario}
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
      {risk.runs[0]?.task === 'scenario' && risk.runs[0].status === 'failed' && (
        <div className="check error">The last attempt failed: {risk.runs[0].error}</div>
      )}
      {!draft ? (
        <p className="muted">No scenario yet.</p>
      ) : (
        <>
          <DraftLabel draft={draft} />
          {editing ? (
            <ScenarioEditor
              initial={draft.effective}
              busy={r.busy}
              onCancel={() => setEditing(false)}
              onSave={(edited, why) => void r.review(draft.id, 'edit', edited, why)}
            />
          ) : (
            <>
              <ScenarioView s={draft.effective} />
              <DraftActions
                draft={draft}
                actions={['approve', 'edit', 'reject']}
                busy={r.busy}
                onAction={(a, why) =>
                  void r.review(draft.id, a, undefined, why).then((ok) => {
                    if (ok && a === 'approve') onContinue?.()
                  })
                }
                needsReason
                approveLabel={onContinue ? 'Approve and continue' : undefined}
                onEdit={() => setEditing(true)}
              />
            </>
          )}
          <ReviewError error={r.error} fieldErrors={r.fieldErrors} />
          {draft.status === 'drafted' && (
            <p className="cap">Approve or edit the scenario before drafting vectors. Vectors use the approved version.</p>
          )}
        </>
      )}
      {risk.fields.mitigation_plan && (
        <>
          <h3>Mitigation plan, from the register</h3>
          <p className="prewrap">{String(risk.fields.mitigation_plan)}</p>
          <p className="cap">
            The residual state is built from this later, as a treatment option in the analysis. It isn’t created
            automatically.
          </p>
        </>
      )}
    </div>
  )
}

function ScenarioView({ s }: { s: ScenarioDraft }) {
  return (
    <>
      <blockquote className="sentence">{s.scenario_sentence}</blockquote>
      <dl className="facts">
        <div>
          <dt>Asset</dt>
          <dd>{s.asset}</dd>
        </div>
        <div>
          <dt>Threat community</dt>
          <dd>{s.threat_community}</dd>
        </div>
        <div>
          <dt>Threat type</dt>
          <dd>{s.threat_type}</dd>
        </div>
        <div>
          <dt>Effect</dt>
          <dd>{s.effect}</dd>
        </div>
      </dl>
      <h4>Condition</h4>
      <p>{s.condition}</p>

      <h4>Baseline controls</h4>
      {s.controls.length === 0 ? (
        <p className="muted">None named in the register.</p>
      ) : (
        <div className="tblwrap">
          <table className="ctl">
            <thead>
              <tr>
                <th scope="col">Control</th>
                <th scope="col">Part of the risk it affects</th>
                <th scope="col">Helps in this scenario</th>
              </tr>
            </thead>
            <tbody>
              {s.controls.map((c, i) => (
                <tr key={i}>
                  <th scope="row">{c.control}</th>
                  <td>{FACTOR[c.factor]}</td>
                  <td>
                    {c.helps ? 'Yes' : <b>No</b>}
                    {c.note && <div className="small muted">{c.note}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {s.notes.length > 0 && (
        <>
          <h4>Assumptions and open questions</h4>
          <ul className="gaps">
            {s.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </>
      )}

      <h4>Scenarios you could split out</h4>
      {s.alternatives.length === 0 ? (
        <p className="muted small">None suggested: one scenario covers the paths in this entry.</p>
      ) : (
        <ul className="alts">
          {s.alternatives.map((a, i) => (
            <li key={i}>
              <b>{a.title}</b> <span className="tag">{SPLIT[a.split_reason] ?? a.split_reason}</span>
              <div className="small">
                {a.threat_community} · {a.threat_type} · {a.effect} · {a.asset}
              </div>
              <div className="small muted">{a.reason}</div>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

const lines = (text: string) =>
  text
    .split('\n')
    .map((x) => x.trim())
    .filter(Boolean)

function ScenarioEditor({
  initial,
  busy,
  onSave,
  onCancel,
}: {
  initial: ScenarioDraft
  busy: boolean
  onSave: (s: ScenarioDraft, reason: string) => void
  onCancel: () => void
}) {
  const [s, setS] = useState<ScenarioDraft>(() => JSON.parse(JSON.stringify(initial)))
  const [notes, setNotes] = useState(initial.notes.join('\n'))
  const set = <K extends keyof ScenarioDraft>(k: K, v: ScenarioDraft[K]) => setS((x) => ({ ...x, [k]: v }))
  const setControl = (i: number, patch: Partial<ScenarioControl>) =>
    set(
      'controls',
      s.controls.map((c, j) => (j === i ? { ...c, ...patch } : c)),
    )

  const [reason, setReason] = useState('')
  const [tried, setTried] = useState(false)

  function submit(e: FormEvent) {
    e.preventDefault()
    setTried(true)
    if (!reasonOk(reason)) return
    onSave(
      { ...s, notes: lines(notes), controls: s.controls.map((c) => ({ ...c, note: c.note?.trim() || null })) },
      reason.trim(),
    )
  }

  return (
    <form className="editor" onSubmit={submit}>
      <label className="fld">
        <span>Scenario sentence</span>
        <textarea rows={2} value={s.scenario_sentence} onChange={(e) => set('scenario_sentence', e.target.value)} />
      </label>
      <div className="grid2">
        <label className="fld">
          <span>Asset</span>
          <input value={s.asset} onChange={(e) => set('asset', e.target.value)} />
        </label>
        <label className="fld">
          <span>Threat community</span>
          <input value={s.threat_community} onChange={(e) => set('threat_community', e.target.value)} />
        </label>
        <label className="fld">
          <span>Threat type</span>
          <select value={s.threat_type} onChange={(e) => set('threat_type', e.target.value)}>
            {THREAT_TYPES_LIST.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        <label className="fld">
          <span>Effect</span>
          <select value={s.effect} onChange={(e) => set('effect', e.target.value)}>
            {EFFECTS_LIST.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
      </div>
      <label className="fld">
        <span>Condition (the weakness)</span>
        <textarea rows={2} value={s.condition} onChange={(e) => set('condition', e.target.value)} />
      </label>

      <fieldset className="rows">
        <legend>Baseline controls</legend>
        {s.controls.map((c, i) => (
          <div className="ctlrow" key={i}>
            <label className="fld">
              <span>Control {i + 1}</span>
              <input value={c.control} onChange={(e) => setControl(i, { control: e.target.value })} />
            </label>
            <label className="fld">
              <span>Affects</span>
              <select value={c.factor} onChange={(e) => setControl(i, { factor: e.target.value as ControlFactor })}>
                {(Object.keys(FACTOR) as ControlFactor[]).map((f) => (
                  <option key={f} value={f}>
                    {FACTOR[f]}
                  </option>
                ))}
              </select>
            </label>
            <label className="check-inline">
              <input type="checkbox" checked={c.helps} onChange={(e) => setControl(i, { helps: e.target.checked })} />{' '}
              Helps in this scenario
            </label>
            <label className="fld">
              <span>Note</span>
              <input value={c.note ?? ''} onChange={(e) => setControl(i, { note: e.target.value })} />
            </label>
            <button
              type="button"
              className="btn quiet danger"
              onClick={() =>
                set(
                  'controls',
                  s.controls.filter((_, j) => j !== i),
                )
              }
            >
              Remove control {i + 1}
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn quiet"
          onClick={() => set('controls', [...s.controls, { control: '', factor: 'susceptibility', helps: true, note: null }])}
        >
          Add a control
        </button>
      </fieldset>

      <label className="fld">
        <span>Assumptions and open questions (one per line)</span>
        <textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>

      {s.alternatives.length > 0 && (
        <fieldset className="rows">
          <legend>Suggested splits</legend>
          {s.alternatives.map((a, i) => (
            <div className="ctlrow" key={i}>
              <span>{a.title}</span>
              <button
                type="button"
                className="btn quiet danger"
                onClick={() =>
                  set(
                    'alternatives',
                    s.alternatives.filter((_, j) => j !== i),
                  )
                }
              >
                Remove “{a.title}”
              </button>
            </div>
          ))}
        </fieldset>
      )}

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

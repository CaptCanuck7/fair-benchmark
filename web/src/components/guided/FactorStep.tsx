import { useId, useState } from 'react'
import type { AgentStatus, Conf, EstimateFactor, EvidenceItem, RangeValue, RegisterRiskDetail } from '../../types'
import { api, ApiError } from '../../api/client'
import { useContent } from '../../content'
import { dateTime } from '../../lib/format'
import { distStatus } from '../../lib/model'
import { factorKind, fairTerm, fieldUnit, fmtRange, stepPath, words } from '../../lib/guided'
import { RequestRow } from '../DataRequestsTab'
import { TaskBar } from '../DraftControls'
import { SourceRecord, ValueCheckTag } from '../EvidenceTab'
import { NumberInput } from '../NumberInput'

const METHOD: Record<string, string> = {
  tef_vuln: 'attempts per year × how often an attempt works',
  cf_poa: 'contacts per year × how often a contact becomes an attempt × how often an attempt works',
  lef: 'loss events per year, estimated directly',
}
const BOUNDS = [
  ['min', 'Lowest you’d expect'],
  ['ml', 'Most likely'],
  ['max', 'Highest you’d expect'],
] as const
const SHOWN = 4
const RATIONALE_MIN = 15

interface Why {
  rationale: string
  evidenceIds: number[]
  placeholder: boolean
}
const emptyRange = (): RangeValue => ({ min: null, ml: null, max: null, conf: 'med' })
const emptyWhy = (): Why => ({ rationale: '', evidenceIds: [], placeholder: false })

/** Why an analyst range can't be saved yet (the api's rules), or null. */
function whyProblem(w: Why): { field: 'rationale' | 'evidence'; msg: string } | null {
  if (w.rationale.trim().length < RATIONALE_MIN)
    return { field: 'rationale', msg: 'Say why you chose this range, in a sentence or two.' }
  if (!w.evidenceIds.length && !w.placeholder)
    return { field: 'evidence', msg: 'Tick the evidence you relied on, or mark this range as a placeholder.' }
  return null
}

type Mode = 'view' | 'enter' | 'compare' | 'third'

interface Props {
  risk: RegisterRiskDetail
  f: EstimateFactor
  agent: AgentStatus | null
  nonMal: boolean
  onRisk: (r: RegisterRiskDetail) => void
  reload: () => void
  navigate: (path: string) => void
}

/** One factor of the Estimates step: evidence, your range, why, then (only after saving) the agent's range. */
export function FactorStep({ risk, f, agent, nonMal, onRisk, reload, navigate }: Props) {
  const content = useContent()
  const est = risk.estimates!
  const kind = factorKind(content, f)
  const w = words(content, f.factor, nonMal)
  const index = est.factors.findIndex((x) => x.factor === f.factor)
  const prev = est.factors[index - 1]
  const next = est.factors[index + 1]
  const dec = f.decision

  const [mode, setMode] = useState<Mode>(dec ? 'view' : f.revealed ? 'compare' : 'enter')
  const [mine, setMine] = useState<RangeValue>(() => f.reveal?.analystRange ?? emptyRange())
  const [why, setWhy] = useState<Why>(emptyWhy)
  const [inputKey, setInputKey] = useState(0)
  const [tried, setTried] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const status = distStatus({ ...mine, src: '' }, kind)
  const problem = whyProblem(why)
  const changed = [est.stale.scenario && 'the scenario', est.stale.evidence && 'the evidence'].filter(Boolean).join(' and ')
  const go = (key?: string) => navigate(key ? stepPath(risk.riskId, 'estimates', key) : stepPath(risk.riskId, 'summary'))
  const label = (key: string) => words(content, key, nonMal).plain

  async function act(fn: () => Promise<RegisterRiskDetail>, then?: Mode) {
    setBusy(true)
    setError(null)
    try {
      onRisk(await fn())
      if (then) setMode(then)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  /** Open the form, filled from a decision (Change) or blank (enter a third). */
  function openForm(from: 'decision' | 'blank') {
    if (from === 'decision' && dec) {
      setMine({ min: dec.min, ml: dec.ml, max: dec.max, conf: dec.conf })
      setWhy(
        dec.choice === 'analyst'
          ? { rationale: dec.rationale ?? '', evidenceIds: dec.evidenceIds, placeholder: !!dec.placeholder }
          : emptyWhy(),
      )
    } else {
      setMine(emptyRange())
      setWhy(emptyWhy())
    }
    setInputKey((k) => k + 1)
    setTried(false)
    setMode(from === 'blank' ? 'third' : 'enter')
  }

  function save() {
    setTried(true)
    if (status.state !== 'ok' || problem) return
    void act(
      () =>
        api.decideEstimate(risk.riskId, f.factor, 'analyst', mine, {
          rationale: why.rationale.trim(),
          evidenceIds: why.evidenceIds,
          placeholder: why.placeholder,
        }),
      'view',
    )
  }

  /** Reveal the agent's range: after saving, sending the saved range as the analyst's own. */
  function compare() {
    if (f.revealed) return setMode('compare')
    const own = dec ? { min: dec.min, ml: dec.ml, max: dec.max, conf: dec.conf } : status.state === 'ok' ? mine : null
    void act(() => api.revealEstimate(risk.riskId, f.factor, own), 'compare')
  }

  const keepMine = () =>
    dec &&
    void act(
      () =>
        api.decideEstimate(risk.riskId, f.factor, 'analyst', { min: dec.min, ml: dec.ml, max: dec.max, conf: dec.conf }, {
          rationale: dec.rationale ?? '',
          evidenceIds: dec.evidenceIds,
          placeholder: !!dec.placeholder,
        }),
      'view',
    )

  const takeAgents = () =>
    void act(() => api.decideEstimate(risk.riskId, f.factor, 'agent', undefined, note.trim() ? { note: note.trim() } : undefined), 'view')

  const forming = mode === 'enter' || mode === 'third'

  return (
    <div className="factorstep">
      <div className="stephead">
        <h1 className="steptitle" id="step-h">
          {w.question}
        </h1>
        <p className="muted">
          {w.plain} · {fairTerm(content, f.factor)}
        </p>
      </div>

      {index === 0 && (
        <>
          <TaskBar
            label="Draft estimates"
            againLabel="Draft estimates again"
            hasDraft
            blocked={risk.blocked.estimates}
            running={risk.agent.state === 'running'}
            agentOff={agent && !agent.configured ? agent.reason : null}
            busy={busy}
            onRun={() => void act(async () => { await api.startRiskTask(risk.riskId, 'estimates'); reload(); return risk })}
          />
          {risk.runs[0]?.task === 'estimates' && risk.runs[0].status === 'failed' && (
            <div className="check error">The last attempt failed: {risk.runs[0].error}</div>
          )}
          <div className="method">
            <b>How the agent recommends working out frequency:</b> {METHOD[est.method.mode]}.{' '}
            <span className="muted">{est.method.reason}</span>
          </div>
        </>
      )}
      {changed && (
        <div className="check warn" role="status">
          <b>Out of date:</b> {changed} changed after these estimates were drafted
          {est.stale.evidence && ' (a new evidence run, or an answered data request)'}. Your decided ranges are kept
          and still usable.{' '}
          {index === 0 ? (
            'Draft the estimates again above if you want fresh agent ranges.'
          ) : (
            <a
              href={stepPath(risk.riskId, 'estimates', est.factors[0].factor)}
              onClick={(e) => {
                e.preventDefault()
                go(est.factors[0].factor)
              }}
            >
              Draft them again from the first factor
            </a>
          )}
        </div>
      )}
      {error && (
        <div className="check error" role="alert">
          {error}
        </div>
      )}

      {mode === 'view' && dec && (
        <Decided risk={risk} f={f} onChange={() => openForm('decision')} onCompare={compare} busy={busy} />
      )}

      {forming && (
        <form
          className="factorform"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            save()
          }}
        >
          {mode === 'third' && (
            <div className="check info">
              <b>Enter a third range.</b> It needs its own reasoning, and replaces the range you saved.
            </div>
          )}
          <EvidencePart
            risk={risk}
            f={f}
            ticked={why.evidenceIds}
            onTick={(id, on) =>
              setWhy((x) => ({ ...x, evidenceIds: on ? [...x.evidenceIds, id] : x.evidenceIds.filter((i) => i !== id) }))
            }
            onRisk={onRisk}
          />

          <fieldset className="part">
            <legend>2 · Enter your range</legend>
            <div className="rangegrid">
              {BOUNDS.map(([k, text]) => (
                <RangeField key={`${k}-${inputKey}`} label={text} kind={kind} value={mine[k]}
                            onValue={(v) => setMine((m) => ({ ...m, [k]: v }))} />
              ))}
              <label className="fld big">
                <span>How sure are you</span>
                <select value={mine.conf} onChange={(e) => setMine((m) => ({ ...m, conf: e.target.value as Conf }))}>
                  {(Object.keys(content.confidence) as Conf[]).map((c) => (
                    <option key={c} value={c}>
                      {content.confidence[c].label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {status.state === 'error' && <div className="dmsg" role="alert">{status.msg}</div>}
            {tried && status.state === 'empty' && (
              <div className="dmsg" role="alert">Enter all three values: lowest, most likely and highest.</div>
            )}
          </fieldset>

          <WhyPart why={why} onWhy={setWhy} problem={tried ? problem : null} />

          <div className="primaryrow">
            <button type="submit" className="btn primary big" disabled={busy}>
              Save my range and reasoning
            </button>
            {dec || (f.revealed && f.agent) ? (
              <button type="button" className="btn quiet" onClick={() => setMode(dec ? 'view' : 'compare')}>
                Cancel
              </button>
            ) : f.status === 'estimated' ? (
              <span className="small muted">
                After you save, you can compare with the agent’s range and keep yours, take the agent’s, or enter a
                third.
              </span>
            ) : null}
          </div>
          {mode === 'enter' && !dec && f.status === 'estimated' && !f.revealed && (
            <p className="small">
              <button type="button" className="linkbtn" disabled={busy || status.state === 'error'} onClick={compare}>
                Show the agent’s range without entering mine
              </button>
            </p>
          )}
          {dec && mode === 'enter' && (
            <p className="small">
              <button type="button" className="linkbtn danger" disabled={busy}
                      onClick={() => void act(() => api.clearEstimate(risk.riskId, f.factor), 'enter')}>
                Clear this decision
              </button>{' '}
              <span className="muted">The factor is then left empty in the analysis until you decide it again.</span>
            </p>
          )}
        </form>
      )}

      {mode === 'compare' && f.agent && (
        <Compare
          risk={risk}
          f={f}
          busy={busy}
          note={note}
          onNote={setNote}
          onKeep={keepMine}
          onTake={takeAgents}
          onThird={() => openForm(dec?.choice === 'analyst' ? 'blank' : 'decision')}
          onBack={() => setMode(dec ? 'view' : 'enter')}
        />
      )}

      <nav className="factornav" aria-label="Factors">
        {prev ? (
          <a href={stepPath(risk.riskId, 'estimates', prev.factor)} onClick={(e) => { e.preventDefault(); go(prev.factor) }}>
            <span aria-hidden="true">← </span>
            {label(prev.factor)}
          </a>
        ) : (
          <span />
        )}
        <a
          className={dec && mode === 'view' ? 'btn primary' : ''}
          href={next ? stepPath(risk.riskId, 'estimates', next.factor) : stepPath(risk.riskId, 'summary')}
          onClick={(e) => {
            e.preventDefault()
            go(next?.factor)
          }}
        >
          Next: {next ? label(next.factor) : 'Summary'}
          <span aria-hidden="true"> →</span>
        </a>
      </nav>
    </div>
  )
}

function RangeField({
  label,
  kind,
  value,
  onValue,
}: {
  label: string
  kind: ReturnType<typeof factorKind>
  value: number | null
  onValue: (v: number | null) => void
}) {
  const id = useId()
  const unit = fieldUnit(kind)
  return (
    <div className="fld big">
      <label htmlFor={id}>{label}</label>
      <div className="unitfield">
        {unit.before && <span aria-hidden="true">{unit.before}</span>}
        <NumberInput id={id} kind={kind} value={value} onValue={(v) => onValue(v)}
                     aria-describedby={`${id}-u`} />
        {unit.after && <span aria-hidden="true">{unit.after}</span>}
        <span id={`${id}-u`} className="sr">
          {kind === 'money' ? 'US dollars per event' : kind === 'pct' ? 'percent' : kind === 'score' ? 'out of 100' : 'per year'}
        </span>
      </div>
    </div>
  )
}

/** Part 1: the evidence for this factor, each with a box to tick if relied on. */
function EvidencePart({
  risk,
  f,
  ticked,
  onTick,
  onRisk,
}: {
  risk: RegisterRiskDetail
  f: EstimateFactor
  ticked: number[]
  onTick: (id: number, on: boolean) => void
  onRisk: (r: RegisterRiskDetail) => void
}) {
  const [all, setAll] = useState(false)
  const [related, setRelated] = useState(false)
  const items = risk.evidence.filter((e) => e.factors.includes(f.factor))
  const group = groupOf(f.factor)
  const groupItems = risk.evidence.filter((e) => !e.factors.includes(f.factor) && (e.groups as string[]).includes(group))
  const shown = all ? items : items.slice(0, SHOWN)
  const request =
    f.unestimated?.dataRequestId != null ? risk.dataRequests.find((r) => r.id === f.unestimated?.dataRequestId) : null
  return (
    <fieldset className="part">
      <legend>1 · Read the evidence and tick what you rely on</legend>
      {items.length === 0 && <p className="muted small">No evidence is tagged to this factor.</p>}
      <ul className="ticklist">
        {shown.map((e) => (
          <TickItem key={e.id} e={e} on={ticked.includes(e.id)} onTick={onTick} />
        ))}
      </ul>
      {items.length > SHOWN && (
        <button type="button" className="linkbtn" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? 'Show fewer' : `Show ${items.length - SHOWN} more item${items.length - SHOWN === 1 ? '' : 's'}`}
        </button>
      )}
      {groupItems.length > 0 && (
        <div>
          <button type="button" className="linkbtn" aria-expanded={related} onClick={() => setRelated(!related)}>
            {related ? 'Hide' : 'Show'} {groupItems.length} related item{groupItems.length === 1 ? '' : 's'} from the same
            part of the model
          </button>
          {related && (
            <ul className="ticklist">
              {groupItems.map((e) => (
                <TickItem key={e.id} e={e} on={ticked.includes(e.id)} onTick={onTick} />
              ))}
            </ul>
          )}
        </div>
      )}
      {f.status === 'unestimated' && (
        <div className="noagent">
          <p className="small">
            <b>The agent gave no range:</b> {f.unestimated?.reason ?? 'it didn’t propose a range for this factor.'}
          </p>
          {request && (
            <ul className="evlist">
              <RequestRow r={request} onRisk={onRisk} />
            </ul>
          )}
        </div>
      )}
    </fieldset>
  )
}

const GROUP_OF: Record<string, string> = {
  lef: 'frequency', tef: 'frequency', cf: 'frequency', poa: 'frequency',
  vuln: 'susceptibility', tcap: 'susceptibility', rs: 'susceptibility', slef: 'secondary',
}
const groupOf = (factor: string) => GROUP_OF[factor] ?? factor.split('.')[0]

function TickItem({ e, on, onTick }: { e: EvidenceItem; on: boolean; onTick: (id: number, on: boolean) => void }) {
  const id = useId()
  return (
    <li className="tickitem">
      <input id={id} type="checkbox" checked={on} onChange={(x) => onTick(e.id, x.target.checked)} />
      <div>
        <label htmlFor={id}>
          {e.summary}
          {e.value != null && (
            <b>
              {' '}
              ({e.value.toLocaleString('en-US')} {e.unit})
            </b>
          )}{' '}
          <span className="cite">{e.citation}</span>
        </label>
        <div className="tickmeta">
          <span className={`tag ${e.origin === 'internal' ? 'ok' : ''}`}>{e.origin === 'internal' ? 'Internal' : 'External'}</span>
          {e.stale && <span className="tag warn">Stale</span>}
          {e.fromDataRequest && <span className="tag">Data request answer</span>}
          <ValueCheckTag e={e} />
        </div>
        <SourceRecord e={e} />
      </div>
    </li>
  )
}

/** Part 3: "Why this range?" and the placeholder flag. */
function WhyPart({
  why,
  onWhy,
  problem,
}: {
  why: Why
  onWhy: (w: Why) => void
  problem: ReturnType<typeof whyProblem>
}) {
  const id = useId()
  return (
    <div className="part whypart">
      <label htmlFor={id} className="partlabel">
        3 · Why this range? <span className="req">Required</span>
      </label>
      <textarea
        id={id}
        rows={4}
        value={why.rationale}
        aria-invalid={problem?.field === 'rationale'}
        aria-describedby={`${id}-hint`}
        onChange={(e) => onWhy({ ...why, rationale: e.target.value })}
      />
      <span id={`${id}-hint`} className="hint">
        One or two sentences. This is saved with your name and shown wherever the number appears.
      </span>
      <label className="check-inline">
        <input type="checkbox" checked={why.placeholder} onChange={(e) => onWhy({ ...why, placeholder: e.target.checked })} />
        This is a placeholder until better data arrives.
      </label>
      {problem && (
        <div className="dmsg" role="alert">
          {problem.msg}
        </div>
      )}
    </div>
  )
}

/** A decided factor: the range, who decided it and when, the reason, and Change. */
function Decided({
  risk,
  f,
  onChange,
  onCompare,
  busy,
}: {
  risk: RegisterRiskDetail
  f: EstimateFactor
  onChange: () => void
  onCompare: () => void
  busy: boolean
}) {
  const content = useContent()
  const d = f.decision!
  const kind = factorKind(content, f)
  const relied = risk.evidence.filter((e) => d.evidenceIds.includes(e.id))
  const before = d.choice === 'analyst' ? !d.revealedFirst || !!f.reveal?.enteredBeforeReveal : !!f.reveal?.enteredBeforeReveal
  return (
    <section className="decidedcard" aria-label="Your decision">
      <p className="bigrange">{fmtRange(kind, d)}</p>
      <p className="small">
        <b>{d.choice === 'agent' ? 'The agent’s range, taken by' : 'Your range, decided by'} {d.by}</b> on{' '}
        {dateTime(d.at)} · {content.confidence[d.conf].label.toLowerCase()} confidence
        {d.placeholder && <span className="tag warn">Placeholder</span>}
        {d.evidenceMatch === 'related' && <span className="tag warn">Rests on related evidence</span>}
      </p>
      <p className="small muted">
        {before ? 'Entered before seeing the agent’s range.' : 'Decided after seeing the agent’s range.'}
      </p>
      {d.rationale ? (
        <>
          <h3 className="h4">{d.choice === 'agent' ? 'The agent’s rationale' : 'Why'}</h3>
          <p className="prewrap">{d.rationale}</p>
        </>
      ) : (
        d.choice === 'analyst' && (
          <p className="small muted">No reason was recorded: this range was decided before reasons were required.</p>
        )
      )}
      {d.note && (
        <p>
          <b>Your note:</b> {d.note}
        </p>
      )}
      {relied.length > 0 && (
        <>
          <h3 className="h4">Evidence relied on</h3>
          <ul className="gaps small">
            {relied.map((e) => (
              <li key={e.id}>
                {e.summary} <span className="cite">{e.citation}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      <div className="draftactions">
        <button type="button" className="btn" onClick={onChange} disabled={busy}>
          Change
        </button>
        {f.status === 'estimated' && (
          <button type="button" className="btn" onClick={onCompare} disabled={busy}>
            Compare with the agent’s range
          </button>
        )}
      </div>
    </section>
  )
}

/** Both ranges side by side, the agent's reasoning and citations, and three choices. */
function Compare({
  risk,
  f,
  busy,
  note,
  onNote,
  onKeep,
  onTake,
  onThird,
  onBack,
}: {
  risk: RegisterRiskDetail
  f: EstimateFactor
  busy: boolean
  note: string
  onNote: (s: string) => void
  onKeep: () => void
  onTake: () => void
  onThird: () => void
  onBack: () => void
}) {
  const content = useContent()
  const noteId = useId()
  const kind = factorKind(content, f)
  const a = f.agent!
  const d = f.decision
  const mine = d?.choice === 'analyst' ? d : null
  const cited = risk.evidence.filter((e) => a.evidenceIds.includes(e.id))
  return (
    <section className="comparebox" aria-labelledby="cmp-h">
      <h2 id="cmp-h" className="h3">
        Compare with the agent’s range
      </h2>
      <div className="cmpgrid">
        <div className="cmpcol">
          <h3 className="h4">Yours</h3>
          {mine ? (
            <>
              <p className="bigrange">{fmtRange(kind, mine)}</p>
              <p className="small muted">{content.confidence[mine.conf].label} confidence</p>
              {mine.rationale && <p className="small">{mine.rationale}</p>}
            </>
          ) : (
            <p className="muted">
              {f.reveal?.analystRange
                ? `Entered before revealing, not saved: ${fmtRange(kind, f.reveal.analystRange)}`
                : 'You didn’t enter a range before revealing.'}
            </p>
          )}
        </div>
        <div className="cmpcol">
          <h3 className="h4">
            The agent’s <span className="muted small">({a.basis} evidence)</span>
          </h3>
          <p className="bigrange">{fmtRange(kind, a)}</p>
          <p className="small muted">
            {content.confidence[a.conf].label} confidence
            {a.evidenceMatch === 'related' && <span className="tag warn">Rests on related evidence</span>}
          </p>
          <p className="small">{a.rationale}</p>
        </div>
      </div>
      {a.evidenceMatch === 'related' ? (
        <div className="check warn small">
          <b>Rests on related evidence.</b> None of the cited items is tagged to this factor; the agent used these from
          the same group, so its confidence is capped at low:
          <ul className="gaps">
            {cited.map((e) => (
              <li key={e.id}>
                {e.summary} <span className="cite">{e.citation}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="small muted">Cites: {cited.map((e) => e.citation).join('; ') || '—'}</p>
      )}
      <div className="fld">
        <label htmlFor={noteId}>Note if you take the agent’s range (optional)</label>
        <textarea id={noteId} rows={2} value={note} onChange={(e) => onNote(e.target.value)} />
      </div>
      <div className="draftactions">
        {mine && (
          <button type="button" className="btn" disabled={busy} onClick={onKeep}>
            Keep mine
          </button>
        )}
        <button type="button" className="btn" disabled={busy} onClick={onTake}>
          Take the agent’s
        </button>
        <button type="button" className="btn" disabled={busy} onClick={onThird}>
          {mine ? 'Enter a third' : 'Enter my own range'}
        </button>
        <button type="button" className="btn quiet" onClick={onBack}>
          Back
        </button>
      </div>
    </section>
  )
}

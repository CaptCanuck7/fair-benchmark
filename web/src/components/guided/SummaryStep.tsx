import { Fragment, type MouseEvent } from 'react'
import type { EstimateFactor, RegisterRiskDetail } from '../../types'
import type { Navigate } from '../../App'
import { useContent } from '../../content'
import { dateTime } from '../../lib/format'
import { factorKind, fairTerm, firstLine, fmtMl, fmtRange, fmtSpan, stepPath, words } from '../../lib/guided'
import { CreateAnalysis } from '../CreateAnalysis'

interface Props {
  risk: RegisterRiskDetail
  nonMal: boolean
  navigate: Navigate
  /** The factor whose justification is open, or null. */
  picked: string | null
  onPick: (factor: string | null) => void
}

const FREQ = ['lef', 'tef', 'cf', 'poa', 'vuln', 'tcap', 'rs']

/**
 * Step 8: the approved scenario, every factor's range and reason as a map,
 * and Create analysis. Nothing here is calculated: results come only from the
 * simulation, after the analysis is created.
 */
export function SummaryStep({ risk, nonMal, navigate, picked, onPick }: Props) {
  const content = useContent()
  const scenario = risk.scenario && ['approved', 'edited'].includes(risk.scenario.status) ? risk.scenario.effective : null
  const est = risk.estimates
  const factors = est?.factors ?? []
  const decided = factors.filter((f) => f.decision)
  const placeholders = decided.filter((f) => f.decision?.placeholder).length
  const open = risk.dataRequests.filter((r) => r.status === 'open').length
  const plain = (k: string) => words(content, k, nonMal).plain
  const byKey = (k: string) => factors.find((f) => f.factor === k)

  const freq = factors.filter((f) => FREQ.includes(f.factor)).map((f) => f.factor)
  const direct = factors.filter((f) => f.factor.startsWith('primary.')).map((f) => f.factor)
  const others = factors.filter((f) => f.factor === 'slef' || f.factor.startsWith('secondary.')).map((f) => f.factor)
  // tcap and rs together stand for "how often an attempt works".
  const freqOps = (k: string) => (k === 'rs' ? 'compared with' : '×')

  const box = (k: string) => {
    const f = byKey(k)
    if (!f) return null
    return (
      <Fragment key={k}>
        <FactorBox risk={risk} f={f} label={plain(k)} on={picked === k} onPick={() => onPick(picked === k ? null : k)} />
        {picked === k && (
          <div className="justinline">
            <Justification risk={risk} f={f} nonMal={nonMal} navigate={navigate} onClose={() => onPick(null)} />
          </div>
        )}
      </Fragment>
    )
  }

  return (
    <div className="summary">
      {scenario ? (
        <p className="scenariosentence">{scenario.scenario_sentence}</p>
      ) : (
        <p className="muted">No approved scenario yet.</p>
      )}

      {!est ? (
        <p className="muted">No estimates yet. Draft them in the Estimates step.</p>
      ) : (
        <>
          <section className="mapblock" aria-labelledby="map-freq">
            <h2 id="map-freq" className="h3">
              How often it happens
            </h2>
            <p className="small muted">
              {freq.map((k, i) => (i ? ` ${freqOps(k)} ${plain(k).toLowerCase()}` : plain(k))).join('')}
            </p>
            <div className="maprow">
              {freq.map((k, i) => (
                <Fragment key={k}>
                  {i > 0 && (
                    <div className="mapop" aria-hidden="true">
                      {freqOps(k)}
                    </div>
                  )}
                  <div className="mapcell">{box(k)}</div>
                </Fragment>
              ))}
            </div>
          </section>

          <section className="mapblock" aria-labelledby="map-cost">
            <h2 id="map-cost" className="h3">
              What one event costs
            </h2>
            <p className="small muted">Direct costs + costs from how others react</p>
            <div className="mapcols">
              <div className="mapcol">
                <h3 className="h4">Direct costs to us</h3>
                {direct.map(box)}
              </div>
              <div className="mapcol">
                <h3 className="h4">Costs from how others react</h3>
                {others.map(box)}
              </div>
            </div>
          </section>
        </>
      )}

      {open > 0 && (
        <p className="small">
          {open} data request{open === 1 ? ' is' : 's are'} still open.{' '}
          <a
            href={stepPath(risk.riskId, 'evidence')}
            onClick={(e) => {
              e.preventDefault()
              navigate(stepPath(risk.riskId, 'evidence'))
              window.setTimeout(() => document.getElementById('requests-h')?.scrollIntoView(), 0)
            }}
          >
            See the data requests
          </a>
        </p>
      )}
      <CreateAnalysis risk={risk} navigate={navigate}>
        {summarySentence(factors.length, decided.length, placeholders, factors.length - decided.length)}
      </CreateAnalysis>
    </div>
  )
}

/** Teams whose open data requests this factor waits on. */
function waitingOn(risk: RegisterRiskDetail, factor: string): string[] {
  return [...new Set(risk.dataRequests.filter((r) => r.factor === factor && r.status === 'open').map((r) => r.team))]
}

const and = (xs: string[]) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`)

function FactorBox({
  risk,
  f,
  label,
  on,
  onPick,
}: {
  risk: RegisterRiskDetail
  f: EstimateFactor
  label: string
  on: boolean
  onPick: () => void
}) {
  const content = useContent()
  const kind = factorKind(content, f)
  const d = f.decision
  if (!d) {
    const teams = waitingOn(risk, f.factor)
    return (
      <button type="button" className={`mapbox empty${on ? ' on' : ''}`} aria-expanded={on} onClick={onPick}>
        <span className="mapboxlabel">{label}</span>
        <span className="mapval">Not estimated</span>
        <span className="mapwho">{teams.length ? `Waiting on ${and(teams)}.` : 'Your turn.'}</span>
      </button>
    )
  }
  const reason = d.choice === 'agent' ? d.note || d.rationale : d.rationale
  return (
    <button type="button" className={`mapbox${on ? ' on' : ''}`} aria-expanded={on} onClick={onPick}>
      <span className="mapboxlabel">{label}</span>
      <span className="mapval">
        {fmtSpan(kind, d.min, d.max)} <span className="muted">{fmtMl(kind, d.ml)}</span>
      </span>
      <span className="mapwho">
        {d.choice === 'agent' ? 'Agent’s range, taken by the analyst' : 'Analyst’s range'} ·{' '}
        {content.confidence[d.conf].label.toLowerCase()} confidence
        {d.placeholder && <span className="tag warn">Placeholder</span>}
      </span>
      {reason && <span className="mapreason">{firstLine(reason)}</span>}
    </button>
  )
}

/** The justification for one factor: range, who and when, the full reason, the evidence, and Change. */
export function Justification({
  risk,
  f,
  nonMal,
  navigate,
  onClose,
}: {
  risk: RegisterRiskDetail
  f: EstimateFactor
  nonMal: boolean
  navigate: Navigate
  onClose: () => void
}) {
  const content = useContent()
  const kind = factorKind(content, f)
  const d = f.decision
  const w = words(content, f.factor, nonMal)
  const to = stepPath(risk.riskId, 'estimates', f.factor)
  const go = (hash = '') => (e: MouseEvent) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
    e.preventDefault()
    navigate(to + hash)
  }
  const relied = d ? risk.evidence.filter((e) => d.evidenceIds.includes(e.id)) : []
  const before = d
    ? d.choice === 'analyst'
      ? !d.revealedFirst || !!f.reveal?.enteredBeforeReveal
      : !!f.reveal?.enteredBeforeReveal
    : false
  const teams = waitingOn(risk, f.factor)
  return (
    <section className="justification" aria-labelledby={`just-${f.factor}`}>
      <div className="justhead">
        <p className="raillabel">Justification</p>
        <h2 id={`just-${f.factor}`} className="h3">
          {w.plain}
        </h2>
        <p className="small muted">{fairTerm(content, f.factor)}</p>
      </div>
      {d ? (
        <>
          <p className="bigrange">{fmtRange(kind, d)}</p>
          <p className="small">
            {d.choice === 'agent' ? 'The agent’s range, taken by' : 'Decided by'} {d.by} on {dateTime(d.at)} ·{' '}
            {content.confidence[d.conf].label.toLowerCase()} confidence
            {d.placeholder && <span className="tag warn">Placeholder</span>}
          </p>
          <p className="small muted">
            {before ? 'Entered before seeing the agent’s range.' : 'Decided after seeing the agent’s range.'}
          </p>
          <h3 className="h4">Why</h3>
          {d.choice === 'agent' ? (
            <>
              {d.note && <p className="prewrap">{d.note}</p>}
              <p className="prewrap small">
                <b>The agent’s rationale:</b> {d.rationale}
              </p>
            </>
          ) : d.rationale ? (
            <p className="prewrap">{d.rationale}</p>
          ) : (
            <p className="small muted">No reason was recorded: this range was decided before reasons were required.</p>
          )}
          <h3 className="h4">Evidence relied on</h3>
          {relied.length ? (
            <ul className="gaps small">
              {relied.map((e) => (
                <li key={e.id}>
                  {e.summary} <span className="cite">{e.citation}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="small muted">{d.placeholder ? 'None: this is a placeholder.' : 'None recorded.'}</p>
          )}
          {f.status === 'estimated' && (
            <>
              <h3 className="h4">The agent’s view</h3>
              <p className="small">
                {f.revealed
                  ? d.choice === 'agent'
                    ? 'The analyst took the agent’s range.'
                    : 'The agent proposed a range from the same evidence. The analyst kept their own.'
                  : 'The agent proposed a range. It hasn’t been shown yet.'}{' '}
                <a href={to + '#compare'} onClick={go('#compare')}>
                  Compare with the agent’s range
                </a>
              </p>
            </>
          )}
        </>
      ) : (
        <>
          <p className="bigrange">Not estimated</p>
          <p className="small">
            {teams.length
              ? `Waiting on ${and(teams)}: a data request for this factor is still open.`
              : 'Your turn: enter a range on the factor’s screen.'}
          </p>
          {f.unestimated?.reason && <p className="small muted">{f.unestimated.reason}</p>}
        </>
      )}
      <div className="draftactions">
        <a className="btn" href={to} onClick={go()}>
          {d ? 'Change this estimate' : 'Estimate this factor'}
        </a>
        <button type="button" className="btn quiet" onClick={onClose}>
          Close
        </button>
      </div>
    </section>
  )
}

/** "7 of 9 factors decided, 3 of them placeholders. 2 are not estimated, so the result will understate the loss." */
export function summarySentence(total: number, decided: number, placeholders: number, missing: number): string {
  if (!total) return 'There are no estimates yet, so the analysis will start with every factor empty.'
  let s = `${decided} of ${total} factors decided`
  if (placeholders) s += `, ${placeholders} of them ${placeholders === 1 ? 'a placeholder' : 'placeholders'}`
  s += '.'
  if (missing) s += ` ${missing} ${missing === 1 ? 'is' : 'are'} not estimated, so the result will understate the loss.`
  return s
}

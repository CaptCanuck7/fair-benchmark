import { Fragment } from 'react'
import type { RegisterRiskDetail } from '../../types'
import { useContent } from '../../content'
import { factorKind, fmtRange, words, type StepId } from '../../lib/guided'

/** What each step is for, shown in the panel when no factor is on screen. */
const STEP_ABOUT: Record<StepId, string> = {
  quality:
    'The quality check reads the register entry for missing or vague information. A risk can only be analyzed once the entry names what is at risk, the weakness, and how loss could happen.',
  triage:
    'Triage decides which risks get a full analysis. A fixed rule on the register score decides; you can override it either way, with a reason.',
  weakness:
    'The kind of weakness (unsupported software, a missing control, and so on) decides where evidence gathering looks first.',
  scenario:
    'The scenario is the one loss event the analysis measures: who acts, against what, and what is lost. Every later step, and the analysis itself, uses the approved version.',
  paths:
    'The paths are the ways the loss could happen, step by step, with the controls that stand in the way. They help you judge how often an attempt works.',
  evidence:
    'Evidence is what every range must rest on: internal records and public sources, each cited. Where nothing was found, a data request asks the team that knows.',
  estimates:
    'Each estimate is a range: the lowest you would expect, the most likely value, and the highest. The simulation uses the whole range, not just the middle.',
  summary:
    'The summary shows every range you decided, and why, before they become an analysis. Results come only from the simulation, after the analysis is created.',
}

interface Box {
  key: string
  label: string
  /** Factors inside the box: the decided range of each, or "You are here". */
  factors?: string[]
}

/** "Where this fits": the factor's place in the model as boxes with operators, and two short paragraphs. */
export function FitsPanel({
  risk,
  step,
  factor,
  nonMal,
}: {
  risk: RegisterRiskDetail
  step: StepId
  factor?: string
  nonMal: boolean
}) {
  const content = useContent()
  const est = risk.estimates
  if (!factor || !est) {
    return (
      <aside className="fits" aria-labelledby="fits-h">
        <h2 id="fits-h" className="raillabel">
          Where this fits
        </h2>
        <p className="small muted">{STEP_ABOUT[step]}</p>
      </aside>
    )
  }
  const plain = (k: string) => words(content, k, nonMal).plain
  const w = words(content, factor, nonMal)
  const { mode, vuln_mode } = est.method
  const lossWords = { attempts: nonMal ? 'Occurrences per year' : 'Attempts per year' }

  let chain: (Box | string)[]
  if (factor.startsWith('primary.') || factor.startsWith('secondary.') || factor === 'slef') {
    chain = [
      { key: 'primary', label: 'Direct costs to us', factors: est.factors.map((x) => x.factor).filter((k) => k.startsWith('primary.')) },
      '+',
      {
        key: 'secondary',
        label: 'Costs from how others react',
        factors: est.factors.map((x) => x.factor).filter((k) => k === 'slef' || k.startsWith('secondary.')),
      },
      '=',
      { key: 'event', label: 'What one event costs' },
    ]
  } else if (mode === 'lef') {
    chain = [{ key: 'lef', label: plain('lef'), factors: ['lef'] }]
  } else if (factor === 'tcap' || factor === 'rs') {
    chain = [
      { key: 'tcap', label: plain('tcap'), factors: ['tcap'] },
      'compared with',
      { key: 'rs', label: plain('rs'), factors: ['rs'] },
      '=',
      { key: 'vuln', label: plain('vuln') },
    ]
  } else if (mode === 'cf_poa' && (factor === 'cf' || factor === 'poa')) {
    chain = [
      { key: 'cf', label: plain('cf'), factors: ['cf'] },
      '×',
      { key: 'poa', label: plain('poa'), factors: ['poa'] },
      '=',
      { key: 'attempts', label: lossWords.attempts },
    ]
  } else {
    const attempts: Box = mode === 'cf_poa' ? { key: 'attempts', label: lossWords.attempts } : { key: 'tef', label: plain('tef'), factors: ['tef'] }
    const works: Box =
      vuln_mode === 'direct' ? { key: 'vuln', label: plain('vuln'), factors: ['vuln'] } : { key: 'vuln', label: `${plain('vuln')} (from capability and controls)` }
    chain = [attempts, '×', works, '=', { key: 'lef', label: plain('lef') }]
  }

  const decided = (k: string) => est.factors.find((x) => x.factor === k)?.decision

  return (
    <aside className="fits" aria-labelledby="fits-h">
      <h2 id="fits-h" className="raillabel">
        Where this fits
      </h2>
      <div className="fitchain" role="list" aria-label="The factor’s place in the model">
        {chain.map((b, i) =>
          typeof b === 'string' ? (
            <div key={i} className="fitop" role="listitem">
              {b}
            </div>
          ) : (
            <div
              key={b.key}
              role="listitem"
              className={`fitbox${b.factors?.includes(factor) ? ' here' : ''}`}
              aria-current={b.factors?.includes(factor) ? 'step' : undefined}
            >
              <div className={b.factors?.length === 1 ? '' : 'fitboxlabel'}>{b.label}</div>
              {b.factors?.length === 1 ? (
                <FitValue k={b.factors[0]} here={b.factors[0] === factor} />
              ) : (
                b.factors?.map((k) => (
                  <Fragment key={k}>
                    <div className={`fitsub${k === factor ? ' here' : ''}`}>
                      {plain(k)}
                      <FitValue k={k} here={k === factor} />
                    </div>
                  </Fragment>
                ))
              )}
            </div>
          ),
        )}
      </div>
      <p className="small muted">{w.context}</p>
      <p className="small muted fitcheck">{w.check}</p>
    </aside>
  )

  function FitValue({ k, here }: { k: string; here: boolean }) {
    if (here) return <div className="fithere">You are here</div>
    const d = decided(k)
    if (!d) return <div className="muted small">Not decided yet</div>
    return <div className="fitval">{fmtRange(factorKind(content, k), d)}</div>
  }
}

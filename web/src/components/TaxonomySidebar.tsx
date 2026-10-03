import type { ReactNode } from 'react'
import type { State, StateResult } from '../types'
import { useContent } from '../content'
import { fmtVal, freq, money, pct } from '../lib/format'
import { distStatus, getPath, isOk } from '../lib/model'

interface Props {
  state: State
  /** Results for this state from a run that matches the current inputs, if any. */
  result: StateResult | null
  onGoto: (target: string) => void
}

type Cls = 'est' | 'der' | 'off'

/** The Open FAIR taxonomy tree for the active option, as in the prototype's renderSide(). */
export function TaxonomySidebar({ state: st, result: r, onGoto }: Props) {
  const content = useContent()
  const L = st.lef
  const m = L.mode
  const vm = L.vulnMode
  const off = 'not used'

  const est = (key: string) => {
    const f = content.factors[key]
    const d = getPath(st, f.path) as State['slef']
    const s = distStatus(d, f.kind)
    return s.state === 'ok' ? 'most likely ' + fmtVal(f.kind, d.ml) : s.state === 'error' ? 'check inputs' : 'not entered'
  }

  const node = (label: string, cls: Cls, val: string, target: string, kids?: ReactNode, root = false) => (
    <li>
      <button type="button" className={`node ${cls}${root ? ' root' : ''}`} onClick={() => onGoto(target)}>
        <span className="nl">{label}</span>
        <span className="nv">{val}</span>
      </button>
      {kids && <ul>{kids}</ul>}
    </li>
  )

  const cfUsed = m === 'cf_poa'
  const tcUsed = m !== 'lef' && vm === 'tcap_rs'
  const formsIn = (grp: 'primary' | 'secondary') =>
    content.forms[grp].filter(({ key }) => isOk(st[grp][key as keyof State[typeof grp]], 'money')).length
  const pf = formsIn('primary')
  const sf = formsIn('secondary')
  const slefOk = isOk(st.slef, 'pct')

  const tefCls: Cls = m === 'lef' ? 'off' : m === 'cf_poa' ? 'der' : 'est'
  const tefVal = m === 'lef' ? off : m === 'cf_poa' ? 'calculated' : est('tef')
  const vCls: Cls = m === 'lef' ? 'off' : vm === 'tcap_rs' ? 'der' : 'est'
  const vVal =
    m === 'lef' ? off : vm === 'tcap_rs' ? (r && r.derivedVulnerability != null ? pct(r.derivedVulnerability) : 'calculated') : est('vuln')
  const lefVal = m === 'lef' ? est('lef') : r ? freq(r.lefMean) + '/yr mean' : 'calculated'

  const tree = node(
    'Risk', 'der', r ? money(r.meanAnnualLoss) + '/yr mean' : 'run to calculate', 'sec-results',
    <>
      {node(
        'Loss event frequency', m === 'lef' ? 'est' : 'der', lefVal, m === 'lef' ? 'f-lef' : 'sec-lef',
        <>
          {node(
            'Threat event frequency', tefCls, tefVal, cfUsed ? 'f-cf' : 'f-tef',
            <>
              {node('Contact frequency', cfUsed ? 'est' : 'off', cfUsed ? est('cf') : off, 'f-cf')}
              {node('Probability of action', cfUsed ? 'est' : 'off', cfUsed ? est('poa') : off, 'f-poa')}
            </>,
          )}
          {node(
            'Vulnerability', vCls, vVal, tcUsed ? 'f-tcap' : 'f-vuln',
            <>
              {node('Threat capability', tcUsed ? 'est' : 'off', tcUsed ? est('tcap') : off, 'f-tcap')}
              {node('Resistance strength', tcUsed ? 'est' : 'off', tcUsed ? est('rs') : off, 'f-rs')}
            </>,
          )}
        </>,
      )}
      {node(
        'Loss magnitude', 'der', r ? money(r.singleLossMean) + ' per event' : 'calculated', 'sec-primary',
        <>
          {node('Primary loss', pf ? 'est' : 'der', pf ? `${pf} of 3 forms entered` : 'not entered', 'sec-primary')}
          {node(
            'Secondary loss', 'der', sf && slefOk ? 'calculated' : 'not entered', 'sec-secondary',
            <>
              {node('Secondary loss event frequency', slefOk ? 'est' : 'der', est('slef'), 'f-slef')}
              {node('Secondary loss magnitude', sf ? 'est' : 'der', sf ? `${sf} of 4 forms entered` : 'not entered', 'f-secondary-response')}
            </>,
          )}
        </>,
      )}
    </>,
    true,
  )

  return (
    <aside className="side panel" aria-label="FAIR taxonomy">
      <h2>Open FAIR taxonomy</h2>
      <p className="lede">{st.name}. Tap a factor to jump to it.</p>
      <ul className="tree">{tree}</ul>
      <div className="legend">
        <span>
          <i className="f" />
          you estimate it
        </span>
        <span>
          <i />
          calculated
        </span>
        <span>
          <i className="o" />
          not used by this method
        </span>
      </div>
    </aside>
  )
}

import type { Comparison } from '../types'
import { money, pct } from '../lib/format'
import { ChecksList } from './ChecksList'
import { LecChart, SERIES_COLORS } from './charts'

export const STALE_COMPARE = 'Inputs changed since the last run. Run the simulation again to update the comparison.'

interface Props {
  /** Comparison from the run being shown, or null when that run had a single option or doesn't cover every option. */
  comparison: Comparison | null
  threshold: number | null
  stale: boolean
}

export function CompareSection({ comparison: c, threshold: thr, stale }: Props) {
  return (
    <section className="panel sec" id="sec-compare">
      <h2>
        <span className="n">6</span>Compare options
      </h2>
      {!c ? (
        <p className="lede">Run the simulation to compare the options.</p>
      ) : (
        <>
          {stale && <div className="banner">{STALE_COMPARE}</div>}
          <div className="tblwrap" tabIndex={0} role="region" aria-label="Comparison of options">
            <table>
              <thead>
                <tr>
                  <th scope="col">Option</th>
                  <th scope="col">Average annual loss</th>
                  <th scope="col">1 in 10 year</th>
                  <th scope="col">1 in 20 year</th>
                  {thr ? <th scope="col">Chance &gt; {money(thr)}</th> : null}
                  <th scope="col">Reduction vs current</th>
                  <th scope="col">Annual cost</th>
                  <th scope="col">Net benefit</th>
                  <th scope="col">Return</th>
                </tr>
              </thead>
              <tbody>
                {c.rows.map((row, i) => (
                  <tr key={row.stateId}>
                    <th scope="row">
                      <span className="sw" style={{ background: SERIES_COLORS[i] }} />
                      {row.name}
                    </th>
                    <td>{money(row.meanAnnualLoss)}</td>
                    <td>{money(row.p90)}</td>
                    <td>{money(row.p95)}</td>
                    {thr ? <td>{pct(row.chanceAboveThreshold)}</td> : null}
                    <td>{i ? `${money(row.reduction)} (${pct(row.reductionPct ?? 0)})` : '—'}</td>
                    <td>{i ? (row.cost != null ? money(row.cost) : 'not entered') : '—'}</td>
                    <td>{row.netBenefit != null ? money(row.netBenefit) : '—'}</td>
                    <td>{row.return != null ? row.return.toFixed(1) + '×' : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="cap">
            Reduction is the drop in average annual loss compared with the current state. Net benefit is reduction minus
            annual cost. Return is reduction divided by cost: 3× means each dollar spent removes about three dollars of
            expected annual loss.
          </p>
          <ChecksList checks={c.checks} />
          <h3>Loss exceedance curves</h3>
          <div className="chart">
            <LecChart
              label="Loss exceedance curves for all options"
              series={c.curves.series.map((s, i) => ({ name: s.name, color: SERIES_COLORS[i], points: s.points }))}
              threshold={thr}
            />
          </div>
          <p className="cap">
            A curve that sits lower and further left means less loss. Watch the tail on the right: an option can have a
            similar average but a much smaller chance of a severe year.
          </p>
        </>
      )}
    </section>
  )
}

import type { Check, Settings, StateResult } from '../types'
import { useContent } from '../content'
import { every, freq, money, pct } from '../lib/format'
import { ITERATION_CHOICES } from '../lib/model'
import { ChecksList } from './ChecksList'
import { HistChart, LecChart } from './charts'
import { NumberInput } from './NumberInput'

export const STALE_RESULTS = 'Inputs changed since the last run. Run the simulation again to update these results.'

interface Props {
  stateName: string
  /** Results for this option from the run being shown, or null if it has none. */
  result: StateResult | null
  /** Settings the shown run used. */
  run: { iterations: number; threshold: number | null } | null
  stale: boolean
  /** Pre-run checks for this option from /api/validate, shown before a run. */
  preChecks: Check[]
  settings: Settings
  onSettings: (field: keyof Settings, value: number | null) => void
  /** Set when showing a past run: settings are read-only and the banner explains why. */
  history: { runAt: string; onBack: () => void } | null
  csvUrl: string | null
}

function Stat({ k, v, ex, keyStat }: { k: string; v: string; ex: string; keyStat?: boolean }) {
  return (
    <div className={'stat' + (keyStat ? ' key' : '')}>
      <div className="k">{k}</div>
      <div className="v">{v}</div>
      <div className="ex">{ex}</div>
    </div>
  )
}

export function ResultsSection({ stateName, result: r, run, stale, preChecks, settings, onSettings, history, csvUrl }: Props) {
  const content = useContent()
  const thr = run?.threshold ?? null

  return (
    <section className="panel sec" id="sec-results">
      <h2>
        <span className="n">5</span>Results: {stateName}
      </h2>
      {history && (
        <div className="banner history">
          Showing a past run from {new Date(history.runAt).toLocaleString()}. It is read-only.{' '}
          <button type="button" className="btn quiet" onClick={history.onBack}>
            Back to the latest run
          </button>
        </div>
      )}
      {!history && (
        <>
          <label className="fld threshold">
            <span>
              Loss threshold to test <span className="hint">optional, e.g. your risk appetite or tolerance</span>
            </span>
            <NumberInput
              kind="money"
              value={settings.threshold}
              placeholder="e.g. 1m"
              onValue={(v, invalid) => !invalid && onSettings('threshold', v)}
            />
          </label>
          <details className="more">
            <summary>Simulation settings</summary>
            <div className="body wide">
              <div className="settings">
                <label className="fld">
                  <span>Simulated years</span>
                  <select value={settings.iterations} onChange={(e) => onSettings('iterations', Number(e.target.value))}>
                    {(ITERATION_CHOICES.includes(settings.iterations) ? ITERATION_CHOICES : [...ITERATION_CHOICES, settings.iterations]).map((n) => (
                      <option key={n} value={n}>
                        {n.toLocaleString('en-US')}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="fld">
                  <span>Random seed</span>
                  <NumberInput kind="int" value={settings.seed} onValue={(v, invalid) => !invalid && v != null && onSettings('seed', v)} />
                </label>
              </div>
              <p className="muted">
                More simulated years give steadier tail percentiles. The seed makes results repeatable: the same inputs
                and seed always give the same numbers, and every option uses the same seed so differences come from
                your inputs, not random noise.
              </p>
            </div>
          </details>
        </>
      )}

      {!r || !run ? (
        <>
          <p className="lede">Run the simulation to see results for {stateName}.</p>
          <ChecksList checks={preChecks} />
        </>
      ) : (
        <>
          {stale && !history && <div className="banner">{STALE_RESULTS}</div>}
          <p className="narr">
            Across {run.iterations.toLocaleString('en-US')} simulated years, the loss event happened {every(r.lefMean)}, and at
            least one loss occurred in {pct(r.chanceAnyLoss)} of years. The average annual loss is{' '}
            <b>{money(r.meanAnnualLoss)}</b>.{' '}
            {r.p50 > 0 ? `In a typical (median) year, losses are about ${money(r.p50)}.` : 'In a typical year there is no loss at all.'} In 1
            year out of 10, losses exceed <b>{money(r.p90)}</b>, and in 1 out of 20 they exceed {money(r.p95)}. When the event
            happens, it typically costs {money(r.singleLossP50)}, and 1 event in 10 costs more than {money(r.singleLossP90)}.
            {thr ? (
              <>
                {' '}The chance of losing more than {money(thr)} in a year is <b>{pct(r.chanceAboveThreshold)}</b>.
              </>
            ) : null}
          </p>
          <div className="stats">
            <Stat k="Average annual loss" v={money(r.meanAnnualLoss)} ex="The mean across all simulated years. Use it for cost-benefit and for comparing options." keyStat />
            <Stat k="Bad year: 1 in 10" v={money(r.p90)} ex="90th percentile of annual loss. One year in ten is worse than this." />
            <Stat k="Severe year: 1 in 20" v={money(r.p95)} ex="95th percentile of annual loss." />
            <Stat
              k="Loss event frequency"
              v={freq(r.lefMean) + ' per year'}
              ex={`Mean. ${every(r.lefMean).replace(/^./, (c) => c.toUpperCase())}. Range 10th–90th: ${freq(r.lefP10)} to ${freq(r.lefP90)}.`}
            />
            <Stat k="Chance of any loss in a year" v={pct(r.chanceAnyLoss)} ex="Share of simulated years with at least one loss event." />
            <Stat k="Cost of one event" v={money(r.singleLossP50)} ex={`Median per loss event. 1 in 10 events costs more than ${money(r.singleLossP90)}.`} />
            {thr ? (
              <Stat k={'Chance of exceeding ' + money(thr)} v={pct(r.chanceAboveThreshold)} ex="Share of simulated years where total loss is above your threshold." />
            ) : null}
            <Stat k="Worst simulated year" v={money(r.max)} ex="The single worst year in the run. Unstable; don’t report it as a figure." />
          </div>

          <h3>Checks on inputs and results</h3>
          <ChecksList checks={r.checks} />

          <h3>Loss exceedance curve</h3>
          <div className="chart">
            <LecChart
              label={`Loss exceedance curve for ${stateName}`}
              series={[{ name: stateName, color: 'var(--s1)', points: r.exceedanceCurve }]}
              threshold={thr}
            />
          </div>
          <p className="cap">
            Read it as: the chance that total loss in a year is higher than the amount on the horizontal axis. The curve
            starts at the chance of any loss and falls as the amount rises. {thr ? 'The dashed line is your threshold.' : ''}
          </p>

          <h3>Cost of a single loss event</h3>
          <div className="chart">
            <HistChart hist={r.histogram} />
          </div>
          <p className="cap">
            How the cost of one loss event is spread across simulated events. Bars on the right are rare, expensive
            events, usually the ones with secondary loss.
          </p>

          <h3>Where the loss comes from</h3>
          <Breakdown breakdown={r.breakdown} labels={content.factors} />
          <p className="cap">
            Average annual loss by form of loss. It shows which estimates matter most, so you know where better data
            would change the answer.
          </p>
          {csvUrl && (
            <p>
              <a className="btn" href={csvUrl} download>
                Download results CSV
              </a>
            </p>
          )}
        </>
      )}
    </section>
  )
}

function Breakdown({ breakdown, labels }: { breakdown: Record<string, number>; labels: Record<string, { label: string }> }) {
  const rows = Object.entries(breakdown).sort((a, b) => b[1] - a[1])
  if (!rows.length) return <p className="muted">No loss was simulated.</p>
  const max = Math.max(1, ...rows.map((x) => x[1]))
  const total = rows.reduce((s, x) => s + x[1], 0) || 1
  return (
    <div className="bars" role="list" aria-label="Average annual loss by form of loss">
      {rows.map(([k, v]) => {
        const sec = k.startsWith('secondary')
        return (
          <div className="bar" role="listitem" key={k}>
            <span>
              {sec ? 'Secondary' : 'Primary'} {labels[k]?.label.toLowerCase() ?? k}
            </span>
            <span className="track" aria-hidden="true">
              <span className={'fill' + (sec ? ' sec' : '')} style={{ width: `${((v / max) * 100).toFixed(1)}%` }} />
            </span>
            <span className="amt">
              {money(v)} · {pct(v / total)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

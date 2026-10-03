import type { RunSummary } from '../types'
import { api } from '../api/client'
import { dateTime, money } from '../lib/format'

interface Props {
  analysisId: string
  runs: RunSummary[]
  /** Id of the run on screen. */
  shownId: string | null
  latestId: string | null
  currentHash: string
  onView: (runId: string) => void
}

export function RunHistory({ analysisId, runs, shownId, latestId, currentHash, onView }: Props) {
  return (
    <section className="panel sec" id="sec-history">
      <h2>
        <span className="n">7</span>Run history
      </h2>
      {!runs.length ? (
        <p className="lede">No runs yet. Each run is saved here with the exact inputs it used, so you can reopen it later.</p>
      ) : (
        <>
          <p className="lede">
            Every run is stored with a copy of its inputs. Select one to see its results read-only.
          </p>
          <ul className="runs">
            {runs.map((r) => {
              const shown = r.id === shownId
              return (
                <li key={r.id} className={shown ? 'on' : ''}>
                  <div className="run-main">
                    <div className="t">
                      {dateTime(r.runAt)}
                      {r.id === latestId && <span className="tag ok">latest</span>}
                      {r.inputHash !== currentHash && <span className="tag">inputs since changed</span>}
                    </div>
                    <div className="d">
                      {r.iterations.toLocaleString('en-US')} simulated years · seed {r.seed}
                      {r.threshold ? ` · threshold ${money(r.threshold)}` : ''}
                    </div>
                    <div className="d">
                      {r.options.map((o, k) => (
                        <span key={o.stateId}>
                          {k > 0 && ' · '}
                          {o.name} <b>{money(o.meanAnnualLoss)}</b>
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="item-actions">
                    <button type="button" className="btn" aria-pressed={shown} disabled={shown} onClick={() => onView(r.id)}>
                      {shown ? 'Showing' : 'View'}
                    </button>
                    <a className="btn quiet" href={api.exportCsvUrl(analysisId, r.id)} download>
                      CSV
                    </a>
                  </div>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </section>
  )
}

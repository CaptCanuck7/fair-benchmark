import type { RegisterRiskDetail } from '../../types'
import { dateTime } from '../../lib/format'

const SECTIONS: [key: string, label: string][] = [
  ['preamble', 'Introduction'],
  ['risk_statement', 'Risk statement'],
  ['detailed_analysis', 'Detailed risk analysis'],
  ['baseline_controls', 'Baseline controls'],
  ['exploit_paths', 'Exploit paths'],
]

const FACTS: [key: string, label: string][] = [
  ['risk_category', 'Category'],
  ['business_unit', 'Business unit'],
  ['environment', 'Environment'],
  ['assets', 'Assets'],
  ['analyst', 'Analyst'],
  ['grc_manager', 'GRC manager'],
  ['risk_owner', 'Risk owner'],
  ['date_identified', 'Date identified'],
  ['risk_action', 'Risk action'],
  ['monitoring_frequency', 'Monitoring frequency'],
  ['remediation_ticket', 'Remediation ticket'],
  ['treatment_owner', 'Treatment owner'],
  ['due_date', 'Due date'],
]

function scoreText(impact: unknown, likelihood: unknown, score: number | null): string {
  if (score == null) {
    const i = impact ?? '—'
    const l = likelihood ?? '—'
    return `Impact ${i}, likelihood ${l}: no score`
  }
  return `${impact} × ${likelihood} = ${score}`
}

/** The risk as it stands in the register: facts, scores, analysis text, plan and monitoring. */
export function RegisterEntry({ risk }: { risk: RegisterRiskDetail }) {
  const f = risk.fields
  const latest = risk.monitoring
    .slice()
    .reverse()
    .find((m) => m.residualScore != null)
  return (
    <section className="entry" aria-labelledby="step-h">
      <h1 id="step-h" className="steptitle">
        The register entry
      </h1>
      <p className="muted">As imported. The steps work from this text; nothing here is changed by them.</p>
      <dl className="facts">
        {FACTS.map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>{f[key] ?? <span className="muted">—</span>}</dd>
          </div>
        ))}
      </dl>

      <h2 className="h3">Scores</h2>
      <dl className="facts">
        <div>
          <dt>Baseline</dt>
          <dd>{scoreText(f.baseline_impact, f.baseline_likelihood, risk.baselineScore)}</dd>
        </div>
        <div>
          <dt>Target residual</dt>
          <dd>{scoreText(f.target_residual_impact, f.target_residual_likelihood, risk.targetScore)}</dd>
        </div>
        <div>
          <dt>Latest residual</dt>
          <dd>
            {latest ? (
              scoreText(latest.residualImpact, latest.residualLikelihood, latest.residualScore)
            ) : (
              <span className="muted">No monitoring update yet</span>
            )}
          </dd>
        </div>
      </dl>
      <p className="cap">
        Scores are impact × likelihood on 1 to 5 scales, recalculated on import. They have no automatic dollar
        equivalent.
      </p>

      <h2 className="h3">Risk analysis</h2>
      {risk.structured ? (
        SECTIONS.filter(([key]) => risk.sections[key]).map(([key, label]) => (
          <div key={key} className="regsec">
            <h3 className="h4">{label}</h3>
            <p className="prewrap">{risk.sections[key]}</p>
          </div>
        ))
      ) : (
        <>
          <div className="check warn">
            <b>Unstructured.</b> This analysis has none of the section labels (Risk Statement, Detailed Risk Analysis,
            Baseline Controls, Exploit Paths), so it is shown as written.
          </div>
          <p className="prewrap">{risk.sections.raw || <span className="muted">No analysis text.</span>}</p>
        </>
      )}

      <h2 className="h3">Mitigation plan</h2>
      <p className="prewrap">{f.mitigation_plan ?? <span className="muted">None recorded.</span>}</p>

      <h2 className="h3">Monitoring updates</h2>
      {risk.monitoring.length === 0 ? (
        <p className="muted">None recorded.</p>
      ) : (
        <ol className="updates">
          {risk.monitoring.map((m, i) => (
            <li key={i}>
              <div className="t">
                {m.taskName ?? 'Update'}
                {m.completedDate && <span className="muted"> · completed {m.completedDate}</span>}
              </div>
              {m.updateText && <p className="prewrap">{m.updateText}</p>}
              <div className="d">Residual: {scoreText(m.residualImpact, m.residualLikelihood, m.residualScore)}</div>
            </li>
          ))}
        </ol>
      )}
      {risk.import && (
        <p className="cap">
          From {risk.import.filename}, imported {dateTime(risk.import.importedAt)}.
        </p>
      )}
    </section>
  )
}

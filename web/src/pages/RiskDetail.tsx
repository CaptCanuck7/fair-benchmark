import { useCallback, useEffect, useState } from 'react'
import type { AgentStatus, RegisterRiskDetail } from '../types'
import { api, ApiError } from '../api/client'
import { dateTime } from '../lib/format'
import { DataRequestsTab } from '../components/DataRequestsTab'
import { EstimatesTab } from '../components/EstimatesTab'
import { EvidenceTab } from '../components/EvidenceTab'
import { QualityTab } from '../components/QualityTab'
import { ScenarioTab } from '../components/ScenarioTab'
import { VectorsTab } from '../components/VectorsTab'
import { TestDataNotice } from '../components/TestDataNotice'

interface Props {
  riskId: string
  navigate: (path: string) => void
}

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

// Tabs in pipeline order. Each fills in as the agent milestones land.
const TABS: [id: string, label: string, about: string][] = [
  [
    'quality',
    'Quality',
    'Checks this entry for missing or vague information and lists questions for you, then triages it and names the kind of weakness behind it.',
  ],
  [
    'scenario',
    'Scenario',
    'A draft loss event scenario: asset, threat community, threat type and effect, with each baseline control mapped to the part of the risk it affects.',
  ],
  [
    'vectors',
    'Vectors',
    'The ways loss could happen, as numbered steps. For accidental or failure risks, the failure paths instead.',
  ],
  ['evidence', 'Evidence', 'Cited evidence for each factor, from internal records and allowlisted public sources.'],
  ['requests', 'Data requests', 'Questions for other teams where no evidence was found.'],
  [
    'estimates',
    'Estimates',
    'First-pass ranges for each factor, each backed by evidence. You see the evidence and enter your own range before you can reveal the agent’s.',
  ],
]

function scoreText(impact: unknown, likelihood: unknown, score: number | null): string {
  if (score == null) {
    const i = impact ?? '—'
    const l = likelihood ?? '—'
    return `Impact ${i}, likelihood ${l}: no score`
  }
  return `${impact} × ${likelihood} = ${score}`
}

export function RiskDetail({ riskId, navigate }: Props) {
  const [risk, setRisk] = useState<RegisterRiskDetail | null>(null)
  const [agent, setAgent] = useState<AgentStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState(TABS[0][0])

  const load = useCallback(() => {
    api.getRisk(riskId).then(setRisk, (e: ApiError) => setError(e.message))
  }, [riskId])

  useEffect(() => {
    document.title = `${riskId} · Risk register`
    load()
    api.agentStatus().then(setAgent, () => setAgent(null))
  }, [riskId, load])

  // Refresh while the agent is working on this risk.
  const running = risk?.agent.state === 'running'
  useEffect(() => {
    if (!running) return
    const t = window.setTimeout(load, 2500)
    return () => window.clearTimeout(t)
  }, [risk, running, load])

  const f = risk?.fields ?? {}
  const latest = risk?.monitoring
    .slice()
    .reverse()
    .find((m) => m.residualScore != null)
  const active = TABS.find((t) => t[0] === tab) ?? TABS[0]

  return (
    <>
      <header className="wrap top">
        <a
          href="/register"
          className="back"
          onClick={(e) => {
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
            e.preventDefault()
            navigate('/register')
          }}
        >
          <span aria-hidden="true">←</span> Risk register
        </a>
        <div className="brand">FAIR risk workbench</div>
        <h1 className="pagetitle">
          {riskId}
          {risk?.title ? ` ${risk.title}` : ''}
        </h1>
      </header>

      <main className="wrap">
        <TestDataNotice />
        {error && (
          <div className="check error" role="alert">
            {error}
          </div>
        )}
        {!risk && !error && <p className="muted">Loading…</p>}
        {risk && (
          <div className="detail">
            <section className="panel" aria-labelledby="entry-h">
              <h2 id="entry-h" className="h2">
                Register entry
              </h2>
              <dl className="facts">
                {FACTS.map(([key, label]) => (
                  <div key={key}>
                    <dt>{label}</dt>
                    <dd>{f[key] ?? <span className="muted">—</span>}</dd>
                  </div>
                ))}
              </dl>

              <h3>Scores</h3>
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
                    {latest
                      ? scoreText(latest.residualImpact, latest.residualLikelihood, latest.residualScore)
                      : <span className="muted">No monitoring update yet</span>}
                  </dd>
                </div>
              </dl>
              <p className="cap">
                Scores are impact × likelihood on 1 to 5 scales, recalculated on import. They have no automatic dollar
                equivalent.
              </p>

              <h3>Risk analysis</h3>
              {risk.structured ? (
                SECTIONS.filter(([key]) => risk.sections[key]).map(([key, label]) => (
                  <div key={key} className="regsec">
                    <h4>{label}</h4>
                    <p className="prewrap">{risk.sections[key]}</p>
                  </div>
                ))
              ) : (
                <>
                  <div className="check warn">
                    <b>Unstructured.</b> This analysis has none of the section labels (Risk Statement, Detailed Risk
                    Analysis, Baseline Controls, Exploit Paths), so it is shown as written.
                  </div>
                  <p className="prewrap">{risk.sections.raw || <span className="muted">No analysis text.</span>}</p>
                </>
              )}

              <h3>Mitigation plan</h3>
              <p className="prewrap">{f.mitigation_plan ?? <span className="muted">None recorded.</span>}</p>

              <h3>Monitoring updates</h3>
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
                      <div className="d">
                        Residual: {scoreText(m.residualImpact, m.residualLikelihood, m.residualScore)}
                      </div>
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

            <section className="panel" aria-label="Agent preparation">
              <div className="tabs" role="tablist" aria-label="Preparation steps">
                {TABS.map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    role="tab"
                    id={`tab-${id}`}
                    aria-selected={tab === id}
                    aria-controls="tabpanel"
                    className={`tab${tab === id ? ' on' : ''}`}
                    onClick={() => setTab(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div id="tabpanel" role="tabpanel" aria-labelledby={`tab-${active[0]}`}>
                <h2 className="h2">{active[1]}</h2>
                <p className="lede">{active[2]}</p>
                {active[0] === 'quality' ? (
                  <QualityTab risk={risk} agent={agent} onRisk={setRisk} reload={load} />
                ) : active[0] === 'scenario' ? (
                  <ScenarioTab risk={risk} agent={agent} onRisk={setRisk} reload={load} />
                ) : active[0] === 'vectors' ? (
                  <VectorsTab risk={risk} agent={agent} onRisk={setRisk} reload={load} />
                ) : active[0] === 'evidence' ? (
                  <EvidenceTab risk={risk} agent={agent} reload={load} onShowRequests={() => setTab('requests')} />
                ) : active[0] === 'requests' ? (
                  <DataRequestsTab risk={risk} onRisk={setRisk} />
                ) : active[0] === 'estimates' ? (
                  <EstimatesTab risk={risk} agent={agent} onRisk={setRisk} reload={load} navigate={navigate} />
                ) : (
                  <p className="muted">Not run yet.</p>
                )}
              </div>
            </section>
          </div>
        )}
      </main>
    </>
  )
}

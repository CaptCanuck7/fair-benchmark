import { useCallback, useEffect, useState, type ReactNode } from 'react'
import type { AgentStatus, RegisterRiskDetail } from '../types'
import type { Navigate } from '../App'
import { api, ApiError } from '../api/client'
import { firstStep, nonMalicious, stepPath, steps, STEP_IDS, type StepId, type StepInfo } from '../lib/guided'
import { DataRequestsTab } from '../components/DataRequestsTab'
import { TaskBar } from '../components/DraftControls'
import { EvidenceTab } from '../components/EvidenceTab'
import { ClassificationView, IntakeBar, QualityView, RunList, TriageView } from '../components/QualityTab'
import { ScenarioTab } from '../components/ScenarioTab'
import { VectorsTab } from '../components/VectorsTab'
import { TestDataNotice } from '../components/TestDataNotice'
import { FactorStep } from '../components/guided/FactorStep'
import { FitsPanel } from '../components/guided/FitsPanel'
import { DecisionRecord } from '../components/guided/DecisionRecord'
import { RegisterEntry } from '../components/guided/RegisterEntry'
import { Justification, SummaryStep } from '../components/guided/SummaryStep'

interface Props {
  riskId: string
  /** The rest of the address: a step, "estimates/{factor}", "entry" or "record". */
  sub: string
  navigate: Navigate
}

/** What each step decides, in plain words. */
function heading(step: StepId, nonMal: boolean): string {
  switch (step) {
    case 'quality':
      return 'Does the register entry say enough to analyze?'
    case 'triage':
      return 'Does this risk need a full analysis?'
    case 'weakness':
      return 'What kind of weakness is behind this risk?'
    case 'scenario':
      return 'What loss event are we measuring?'
    case 'paths':
      return nonMal ? 'How could a failure lead to the loss?' : 'How could an attacker cause the loss?'
    case 'evidence':
      return 'What do we know, and what do we still need to ask?'
    case 'estimates':
      return 'How often, and how much? Start with the agent’s first draft.'
    case 'summary':
      return 'Does the whole picture hold together?'
  }
}

type View = { kind: 'step'; step: StepId; factor?: string } | { kind: 'entry' } | { kind: 'record' } | { kind: 'none' }

function parseSub(sub: string): View {
  const [head, factor] = sub.split('/')
  if (!head) return { kind: 'none' }
  if (head === 'entry') return { kind: 'entry' }
  if (head === 'record') return { kind: 'record' }
  if ((STEP_IDS as string[]).includes(head))
    return { kind: 'step', step: head as StepId, factor: factor ? decodeURIComponent(factor) : undefined }
  return { kind: 'none' }
}

/** The guided risk page (UI_REBUILD.md): eight steps, one at a time. */
export function RiskDetail({ riskId, sub, navigate }: Props) {
  const [risk, setRisk] = useState<RegisterRiskDetail | null>(null)
  const [agent, setAgent] = useState<AgentStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [railOpen, setRailOpen] = useState(false)
  // The summary map's selected factor, whose justification is open.
  const [picked, setPicked] = useState<string | null>(null)
  const view = parseSub(sub)

  const load = useCallback(() => {
    api.getRisk(riskId).then(setRisk, (e: ApiError) => setError(e.message))
  }, [riskId])

  useEffect(() => {
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

  // /register/{riskId} opens the first step that needs the analyst; the
  // Estimates step opens its first undecided factor.
  useEffect(() => {
    if (!risk) return
    if (view.kind === 'none') navigate(stepPath(riskId, firstStep(risk)), { replace: true })
    else if (view.kind === 'step' && view.step === 'estimates' && risk.estimates?.factors.length) {
      const fs = risk.estimates.factors
      if (!view.factor || !fs.some((f) => f.factor === view.factor)) {
        const target = fs.find((f) => !f.decision) ?? fs[0]
        navigate(stepPath(riskId, 'estimates', target.factor), { replace: true })
      }
    }
  }, [risk, view.kind, view.kind === 'step' ? view.step : '', view.kind === 'step' ? view.factor : '']) // eslint-disable-line react-hooks/exhaustive-deps

  const nonMal = risk ? nonMalicious(risk) : false
  const factor = view.kind === 'step' && view.step === 'estimates' ? view.factor : undefined
  const all = risk ? steps(risk, factor) : []
  const current = view.kind === 'step' ? all.find((s) => s.id === view.step) : undefined
  const currentFactor = factor ? risk?.estimates?.factors.find((f) => f.factor === factor) : undefined

  useEffect(() => {
    const what = view.kind === 'entry' ? 'Register entry' : view.kind === 'record' ? 'Decision record' : current?.label
    document.title = `${riskId}${what ? ` · ${what}` : ''} · Risk register`
  }, [riskId, current?.label, view.kind])

  const go = (step: StepId) => {
    setRailOpen(false)
    navigate(stepPath(riskId, step))
  }
  const link = (to: string, children: ReactNode, className?: string) => (
    <a
      href={to}
      className={className}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
        e.preventDefault()
        setRailOpen(false)
        navigate(to)
      }}
    >
      {children}
    </a>
  )

  return (
    <>
      <header className="guidedhead">
        {link(
          '/register',
          <>
            <span aria-hidden="true">←</span> Risk register
          </>,
          'back',
        )}
        <p className="guidedtitle">
          {riskId}
          {risk?.title ? ` · ${risk.title}` : ''}
        </p>
        {link(stepPath(riskId, 'record'), 'Decision record', `recordlink${view.kind === 'record' ? ' on' : ''}`)}
      </header>

      <div className="guided">
        {risk && (
          <nav className={`rail${railOpen ? ' open' : ''}`} aria-label="Steps">
            <button type="button" className="railtoggle" aria-expanded={railOpen} aria-controls="steplist"
                    onClick={() => setRailOpen(!railOpen)}>
              {current ? `Step ${current.n} of ${all.length} · ${current.label}` : 'Steps'}
              {current && <span className="muted"> · {current.status}</span>}
              <span aria-hidden="true" className="chev">{railOpen ? '▴' : '▾'}</span>
            </button>
            <div id="steplist" className="railbody">
              <h2 className="raillabel">Steps</h2>
              <ol className="steplist">
                {all.map((s) => (
                  <li key={s.id}>
                    <RailItem s={s} current={current?.id === s.id} riskId={riskId} onGo={go} />
                  </li>
                ))}
              </ol>
              <p className="railextra">
                {link(stepPath(riskId, 'entry'), 'View the register entry', view.kind === 'entry' ? 'on' : undefined)}
              </p>
            </div>
          </nav>
        )}

        <main className="guidedmain" id="main">
          <TestDataNotice />
          {error && (
            <div className="check error" role="alert">
              {error}
            </div>
          )}
          {!risk && !error && <p className="muted">Loading…</p>}
          {risk && view.kind === 'entry' && (
            <>
              <RegisterEntry risk={risk} />
              <p className="stepnav">{link(stepPath(riskId, firstStep(risk)), 'Back to the steps')}</p>
            </>
          )}
          {risk && view.kind === 'record' && (
            <>
              <DecisionRecord risk={risk} nonMal={nonMal} navigate={navigate} />
              <p className="stepnav">{link(stepPath(riskId, firstStep(risk)), 'Back to the steps')}</p>
            </>
          )}
          {risk && current && (
            <>
              <p className="stepof">
                Step {current.n} of {all.length} · {current.label}
                {currentFactor && ` · Factor ${risk.estimates!.factors.indexOf(currentFactor) + 1} of ${risk.estimates!.factors.length}`}
              </p>
              {current.blocked && (
                <div className="check blocked" role="status">
                  <b>Can’t start yet.</b> {current.blocked}
                </div>
              )}
              {currentFactor ? (
                <FactorStep
                  key={currentFactor.factor}
                  risk={risk}
                  f={currentFactor}
                  agent={agent}
                  nonMal={nonMal}
                  onRisk={setRisk}
                  reload={load}
                  navigate={navigate}
                />
              ) : (
                <>
                  <h1 className="steptitle" id="step-h">
                    {heading(current.id, nonMal)}
                  </h1>
                  {stepBody(current.id, risk, () => go(all[current.n]?.id ?? 'summary'))}
                  <StepNav all={all} current={current} riskId={riskId} link={link} />
                </>
              )}
            </>
          )}
        </main>

        {risk && current && (() => {
          const pickedFactor = current.id === 'summary' && picked ? risk.estimates?.factors.find((f) => f.factor === picked) : undefined
          return pickedFactor ? (
            <div className="justside">
              <Justification risk={risk} f={pickedFactor} nonMal={nonMal} navigate={navigate} onClose={() => setPicked(null)} />
            </div>
          ) : (
            <FitsPanel risk={risk} step={current.id} factor={currentFactor?.factor} nonMal={nonMal} />
          )
        })()}
      </div>
    </>
  )

  // A plain function, not a component, so the steps keep their state across renders.
  function stepBody(step: StepId, risk: RegisterRiskDetail, next: () => void) {
    const { quality, triage, classification } = risk.intake
    switch (step) {
      case 'quality':
        return (
          <div className="intake">
            <IntakeBar risk={risk} agent={agent} reload={load} />
            {quality ? <QualityView draft={quality} onRisk={setRisk} onContinue={next} /> : <p className="muted">Not run yet.</p>}
            <RunList runs={risk.runs} />
          </div>
        )
      case 'triage':
        return (
          <div className="intake">
            {triage ? (
              <TriageView draft={triage} risk={risk} onRisk={setRisk} onContinue={next} />
            ) : (
              <p className="muted">Not run yet.</p>
            )}
          </div>
        )
      case 'weakness':
        return (
          <div className="intake">
            {classification ? (
              <ClassificationView draft={classification} onRisk={setRisk} onContinue={next} />
            ) : (
              <p className="muted">Not run yet.</p>
            )}
          </div>
        )
      case 'scenario':
        return <ScenarioTab risk={risk} agent={agent} onRisk={setRisk} reload={load} onContinue={next} />
      case 'paths':
        return <VectorsTab risk={risk} agent={agent} onRisk={setRisk} reload={load} onContinue={next} />
      case 'evidence':
        return (
          <>
            <EvidenceTab
              risk={risk}
              agent={agent}
              reload={load}
              onShowRequests={() => document.getElementById('requests-h')?.scrollIntoView()}
            />
            <section className="requests" aria-labelledby="requests-h">
              <h2 id="requests-h" className="h3" tabIndex={-1}>
                Data requests
              </h2>
              <p className="cap">Questions for other teams where no evidence was found. An answer becomes evidence.</p>
              <DataRequestsTab risk={risk} onRisk={setRisk} />
            </section>
          </>
        )
      case 'estimates':
        // With estimates, the effect above moves on to the first undecided factor.
        return (
          <div className="intake">
            <TaskBar
              label="Draft estimates"
              againLabel="Draft estimates again"
              hasDraft={!!risk.estimates}
              blocked={risk.blocked.estimates}
              running={risk.agent.state === 'running'}
              agentOff={agent && !agent.configured ? agent.reason : null}
              busy={false}
              onRun={() => void api.startRiskTask(risk.riskId, 'estimates').then(load, (e) => setError(String(e.message ?? e)))}
            />
            {risk.runs[0]?.task === 'estimates' && risk.runs[0].status === 'failed' && (
              <div className="check error">The last attempt failed: {risk.runs[0].error}</div>
            )}
            <p className="muted">
              {risk.estimates
                ? 'Opening the first factor…'
                : 'No estimates yet. The agent drafts a first-pass range for each factor from the evidence; you then enter your own range for each, with your reasons, before you see the agent’s.'}
            </p>
          </div>
        )
      case 'summary':
        return <SummaryStep risk={risk} nonMal={nonMal} navigate={navigate} picked={picked} onPick={setPicked} />
    }
  }
}

function RailItem({
  s,
  current,
  riskId,
  onGo,
}: {
  s: StepInfo
  current: boolean
  riskId: string
  onGo: (s: StepId) => void
}) {
  return (
    <a
      href={stepPath(riskId, s.id)}
      className={`stepitem${current ? ' on' : ''}${s.blocked ? ' muted' : ''}`}
      aria-current={current ? 'step' : undefined}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
        e.preventDefault()
        onGo(s.id)
      }}
    >
      <span className="stepn" aria-hidden="true">
        {s.n}
      </span>
      <span>
        <span className="steplabel">{s.label}</span>
        <span className="stepstatus">
          <span className="sr">: </span>
          {s.blocked ? `Can’t start yet · ${s.status}` : s.status}
        </span>
      </span>
    </a>
  )
}

/** Previous and next steps. Next is the primary button once this step needs nothing from the analyst. */
function StepNav({
  all,
  current,
  riskId,
  link,
}: {
  all: StepInfo[]
  current: StepInfo
  riskId: string
  link: (to: string, children: ReactNode, className?: string) => ReactNode
}) {
  const prev = all[current.n - 2]
  const next = all[current.n]
  return (
    <nav className="stepnav" aria-label="Previous and next step">
      {prev ? (
        link(stepPath(riskId, prev.id), <><span aria-hidden="true">← </span>{prev.label}</>)
      ) : (
        <span />
      )}
      {next &&
        link(
          stepPath(riskId, next.id),
          <>
            Next: {next.label}
            <span aria-hidden="true"> →</span>
          </>,
          !current.needsAnalyst && !next.blocked ? 'btn primary' : undefined,
        )}
    </nav>
  )
}

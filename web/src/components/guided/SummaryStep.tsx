import type { RegisterRiskDetail } from '../../types'
import type { Navigate } from '../../App'
import { stepPath } from '../../lib/guided'
import { CreateAnalysis } from '../CreateAnalysis'

interface Props {
  risk: RegisterRiskDetail
  nonMal: boolean
  navigate: Navigate
}

/** Step 8: the approved scenario, what will be pushed, and Create analysis. */
export function SummaryStep({ risk, navigate }: Props) {
  const scenario = risk.scenario && ['approved', 'edited'].includes(risk.scenario.status) ? risk.scenario.effective : null
  const est = risk.estimates
  const factors = est?.factors ?? []
  const decided = factors.filter((f) => f.decision)
  const placeholders = decided.filter((f) => f.decision?.placeholder).length
  const missing = factors.length - decided.length
  const open = risk.dataRequests.filter((r) => r.status === 'open').length

  return (
    <div className="summary">
      {scenario && <p className="scenariosentence">{scenario.scenario_sentence}</p>}
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
        {summarySentence(factors.length, decided.length, placeholders, missing)}
      </CreateAnalysis>
    </div>
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

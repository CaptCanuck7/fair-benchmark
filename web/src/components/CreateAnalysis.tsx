import { useState, type ReactNode } from 'react'
import type { RegisterRiskDetail } from '../types'
import { api, ApiError } from '../api/client'

interface Props {
  risk: RegisterRiskDetail
  navigate: (path: string) => void
  /** What will be pushed, in a sentence. */
  children: ReactNode
}

/** "Create analysis", with the out-of-date refusal and its "Create anyway" confirmation. */
export function CreateAnalysis({ risk, navigate, children }: Props) {
  const est = risk.estimates
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // The create-analysis refusal for out-of-date estimates, offering "Create anyway".
  const [staleBlock, setStaleBlock] = useState<string | null>(null)
  const changed = est ? [est.stale.scenario && 'the scenario', est.stale.evidence && 'the evidence'].filter(Boolean).join(' and ') : ''

  async function create(acknowledgeStale: boolean) {
    setStaleBlock(null)
    setError(null)
    setBusy(true)
    try {
      const r = await api.analysisFromRisk(risk.riskId, acknowledgeStale)
      navigate(`/analyses/${r.analysisId}`)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && changed && !acknowledgeStale) setStaleBlock(e.message)
      else setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="create" aria-label="Create analysis">
      <div className="createrow">
        <button type="button" className="btn primary big" disabled={busy} onClick={() => void create(false)}>
          Create analysis
        </button>
        <p className="small">{children}</p>
      </div>
      {risk.analysisId && (
        <p className="small">
          <a
            href={`/analyses/${risk.analysisId}`}
            onClick={(e) => {
              if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
              e.preventDefault()
              navigate(`/analyses/${risk.analysisId}`)
            }}
          >
            Open the last analysis created from this risk
          </a>
        </p>
      )}
      {staleBlock && (
        <div className="check warn" role="alert">
          {staleBlock}{' '}
          <button type="button" className="btn" disabled={busy} onClick={() => void create(true)}>
            Create anyway
          </button>
        </div>
      )}
      {error && (
        <div className="check error" role="alert">
          {error}
        </div>
      )}
    </section>
  )
}

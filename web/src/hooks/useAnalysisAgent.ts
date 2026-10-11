import { useCallback, useEffect, useState } from 'react'
import type { AgentStatus, AnalysisAgentView, ReviewAction } from '../types'
import { api, ApiError } from '../api/client'

/**
 * The agent's input review and reports for one analysis: loads them, starts
 * tasks, and refreshes every few seconds while a task is running.
 */
export function useAnalysisAgent(analysisId: string) {
  const [view, setView] = useState<AnalysisAgentView | null>(null)
  const [status, setStatus] = useState<AgentStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  const load = useCallback(() => {
    api.analysisAgent(analysisId).then(setView, () => setView(null))
  }, [analysisId])

  useEffect(() => {
    setView(null)
    setError(null)
    load()
    api.agentStatus().then(setStatus, () => setStatus(null))
  }, [load])

  const busy = !!view?.busy
  useEffect(() => {
    if (!busy) return
    const t = window.setTimeout(load, 2500)
    return () => window.clearTimeout(t)
  }, [view, busy, load])

  async function act(fn: () => Promise<unknown>) {
    setStarting(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setStarting(false)
      load()
    }
  }

  return {
    view,
    error,
    busy: busy || starting,
    /** Why the agent can't run, or null when it can. */
    off: status && !status.configured ? (status.reason ?? 'The agent is off.') : status ? null : 'The agent service isn’t reachable.',
    review: () => act(() => api.startReview(analysisId)),
    report: (runId: string) => act(() => api.startReport(analysisId, runId)),
    decide: (draftId: number, action: ReviewAction, payload?: { leadershipSummary: string; exceptionJustification: string | null }) =>
      act(async () => setView(await api.reviewAnalysisDraft(draftId, action, payload))),
  }
}

export type AnalysisAgent = ReturnType<typeof useAnalysisAgent>

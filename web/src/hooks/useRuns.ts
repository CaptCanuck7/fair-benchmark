import { useCallback, useState } from 'react'
import type { Run, RunSummary } from '../types'
import { api } from '../api/client'

/** Run history for one analysis: the list, the latest full run, and a past run being viewed. */
export function useRuns(analysisId: string) {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [latest, setLatest] = useState<Run | null>(null)
  const [viewing, setViewing] = useState<Run | null>(null)

  const load = useCallback(async () => {
    const list = await api.listRuns(analysisId)
    setRuns(list)
    setLatest(list.length ? await api.getRun(analysisId, list[0].id) : null)
  }, [analysisId])

  /** Record a run that just finished and show it. */
  const added = useCallback(
    async (run: Run) => {
      setLatest(run)
      setViewing(null)
      setRuns(await api.listRuns(analysisId))
    },
    [analysisId],
  )

  const view = useCallback(
    async (runId: string) => {
      if (latest && runId === latest.id) setViewing(null)
      else setViewing(await api.getRun(analysisId, runId))
    },
    [analysisId, latest],
  )

  return { runs, latest, viewing, shown: viewing ?? latest, load, added, view, back: () => setViewing(null) }
}

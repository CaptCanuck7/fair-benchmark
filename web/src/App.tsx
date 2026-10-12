import { useCallback, useEffect, useState } from 'react'
import type { Content } from './types'
import { api } from './api/client'
import { ContentContext } from './content'
import { AnalysesList } from './components/AnalysesList'
import { Workspace } from './components/Workspace'
import { RegisterList } from './pages/RegisterList'
import { RiskDetail } from './pages/RiskDetail'
import { Settings } from './pages/Settings'

// Pages: "/" lists analyses, "/analyses/:id" is the workspace, "/register"
// lists register risks, "/register/:riskId/:step" shows one (the guided page;
// "/register/:riskId/estimates/:factor" for one factor) and "/settings" shows
// the agent's status and outbound log.
// nginx falls back to index.html, so both work on reload.
export type Navigate = (path: string, opts?: { replace?: boolean }) => void

function useRoute(): [string, Navigate] {
  const [path, setPath] = useState(() => window.location.pathname)
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const navigate = useCallback<Navigate>((to, opts) => {
    if (opts?.replace) window.history.replaceState(null, '', to)
    else if (to !== window.location.pathname) window.history.pushState(null, '', to)
    setPath(new URL(to, window.location.origin).pathname)
    window.scrollTo(0, 0)
  }, [])
  return [path, navigate]
}

export default function App() {
  const [content, setContent] = useState<Content | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [path, navigate] = useRoute()

  useEffect(() => {
    api.content().then(setContent, (e) => setError(e.message))
  }, [])

  if (error) return <p className="wrap top">Couldn’t load the app: {error}</p>
  if (!content) return <p className="wrap top muted">Loading…</p>

  const m = /^\/analyses\/([^/]+)\/?$/.exec(path)
  const risk = /^\/register\/([^/]+)(?:\/(.+?))?\/?$/.exec(path)
  let page
  if (m) page = <Workspace key={m[1]} id={decodeURIComponent(m[1])} navigate={navigate} />
  else if (risk) page = <RiskDetail key={risk[1]} riskId={decodeURIComponent(risk[1])} sub={risk[2] ?? ''} navigate={navigate} />
  else if (/^\/register\/?$/.test(path)) page = <RegisterList navigate={navigate} />
  else if (/^\/settings\/?$/.test(path)) page = <Settings navigate={navigate} />
  else page = <AnalysesList navigate={navigate} />
  return <ContentContext.Provider value={content}>{page}</ContentContext.Provider>
}

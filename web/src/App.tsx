import { useCallback, useEffect, useState } from 'react'
import type { Content } from './types'
import { api } from './api/client'
import { ContentContext } from './content'
import { AnalysesList } from './components/AnalysesList'
import { Workspace } from './components/Workspace'

// Two pages: "/" lists analyses and "/analyses/:id" is the workspace.
// nginx falls back to index.html, so both work on reload.
function useRoute(): [string, (path: string) => void] {
  const [path, setPath] = useState(() => window.location.pathname)
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const navigate = useCallback((to: string) => {
    if (to !== window.location.pathname) window.history.pushState(null, '', to)
    setPath(to)
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
  return (
    <ContentContext.Provider value={content}>
      {m ? <Workspace key={m[1]} id={decodeURIComponent(m[1])} navigate={navigate} /> : <AnalysesList navigate={navigate} />}
    </ContentContext.Provider>
  )
}

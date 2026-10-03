import { useCallback, useEffect, useRef, useState } from 'react'
import type { Analysis, Scope } from '../types'
import { api, ApiError } from '../api/client'
import { saveStatusText, useAutosave } from '../hooks/useAutosave'
import { setPath, treatmentCopy, updateState } from '../lib/model'
import { FrequencySection } from './FrequencySection'
import { ConformanceNote, Intro } from './Intro'
import { PrimarySection, SecondarySection } from './LossSections'
import { OptionTabs } from './OptionTabs'
import { ScopeSection } from './ScopeSection'
import { TaxonomySidebar } from './TaxonomySidebar'

const LEF_ANCHORS = new Set(['f-lef', 'f-tef', 'f-cf', 'f-poa', 'f-vuln', 'f-tcap', 'f-rs'])

interface Props {
  id: string
  navigate: (path: string) => void
}

export function Workspace({ id, navigate }: Props) {
  const [doc, setDoc] = useState<Analysis | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [, setInputHash] = useState('')
  const docRef = useRef<Analysis | null>(null)
  const autosave = useAutosave(setInputHash)
  const { schedule, reset } = autosave

  useEffect(() => {
    let live = true
    setDoc(null)
    setLoadError(null)
    api.getAnalysis(id).then(
      ({ doc, inputHash }) => {
        if (!live) return
        docRef.current = doc
        reset(doc)
        setDoc(doc)
        setInputHash(inputHash)
        document.title = `${doc.title} · FAIR risk workbench`
      },
      (e) => live && setLoadError(e instanceof ApiError && e.status === 404 ? 'This analysis doesn’t exist. It may have been deleted.' : String(e.message ?? e)),
    )
    return () => {
      live = false
    }
  }, [id, reset])

  /** Apply an edit, re-render, and schedule an autosave. */
  const edit = useCallback(
    (fn: (a: Analysis) => Analysis) => {
      const cur = docRef.current
      if (!cur) return
      const next = fn(cur)
      docRef.current = next
      setDoc(next)
      schedule(next)
    },
    [schedule],
  )

  const goto = useCallback((target: string) => {
    let el = document.getElementById(target)
    if (!el && LEF_ANCHORS.has(target)) el = document.getElementById('sec-lef')
    if (!el) return
    el.scrollIntoView({ block: 'start' })
    const input = el.querySelector<HTMLElement>('input, select')
    if (input) window.setTimeout(() => input.focus({ preventScroll: true }), 350)
  }, [])

  if (loadError) {
    return (
      <div className="wrap top">
        <p>{loadError}</p>
        <button type="button" className="btn" onClick={() => navigate('/')}>
          All analyses
        </button>
      </div>
    )
  }
  if (!doc) return <p className="wrap top muted">Loading…</p>

  const i = doc.active
  const st = doc.states[i]
  const editState = (path: string, value: unknown) => edit((a) => updateState(a, a.active, path, value))

  return (
    <>
      <header className="wrap top">
        <div className="brand">FAIR risk workbench</div>
        <div className="row">
          <div className="titlebox">
            <label className="sr" htmlFor="title">
              Analysis name
            </label>
            <input
              id="title"
              className="title"
              autoComplete="off"
              value={doc.title}
              onChange={(e) => {
                const title = e.target.value
                document.title = `${title} · FAIR risk workbench`
                edit((a) => ({ ...a, title }))
              }}
            />
            <div className="savestate" aria-live="polite">
              {saveStatusText(autosave.status)}
            </div>
          </div>
          <div className="actions">
            <button type="button" className="btn" onClick={() => navigate('/')}>
              All analyses
            </button>
            <button
              type="button"
              className="btn"
              onClick={async () => {
                await autosave.flush()
                window.location.href = api.exportJsonUrl(doc.id)
              }}
            >
              Export JSON
            </button>
          </div>
        </div>
        <Intro />
      </header>

      <div className="wrap layout">
        <TaxonomySidebar state={st} result={null} onGoto={goto} />
        <main>
          <ScopeSection
            scope={doc.scope}
            onChange={(field: keyof Scope, value) => edit((a) => setPath(a, `scope.${field}`, value))}
          />
          <OptionTabs
            states={doc.states}
            active={i}
            onSelect={(index) => {
              edit((a) => ({ ...a, active: index }))
              document.getElementById('sec-state')?.scrollIntoView({ block: 'start' })
            }}
            onAdd={() => {
              edit((a) => {
                const states = [...a.states, treatmentCopy(a.states[a.active], a.states.length)]
                return { ...a, states, active: states.length - 1 }
              })
              document.getElementById('sec-state')?.scrollIntoView({ block: 'start' })
            }}
            onDelete={() => edit((a) => ({ ...a, states: a.states.filter((_, k) => k !== a.active), active: 0 }))}
            onChange={editState}
          />
          <FrequencySection stateId={st.id} lef={st.lef} onChange={editState} />
          <PrimarySection state={st} onChange={editState} />
          <SecondarySection state={st} onChange={editState} />
          <ConformanceNote />
        </main>
      </div>
    </>
  )
}

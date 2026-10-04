import { useCallback, useEffect, useRef, useState } from 'react'
import type { Analysis, Check, Scope, Settings } from '../types'
import { api, ApiError } from '../api/client'
import { useContent } from '../content'
import { saveStatusText, useAutosave } from '../hooks/useAutosave'
import { useRuns } from '../hooks/useRuns'
import { factorAnchor, parseCheckPath, setPath, treatmentCopy, updateState } from '../lib/model'
import { CompareSection } from './CompareSection'
import { FrequencySection } from './FrequencySection'
import { ConformanceNote, Intro } from './Intro'
import { PrimarySection, SecondarySection } from './LossSections'
import { OptionTabs } from './OptionTabs'
import { ResultsSection } from './ResultsSection'
import { RunBar } from './RunBar'
import { RunHistory } from './RunHistory'
import { ScopeSection } from './ScopeSection'
import { TaxonomySidebar } from './TaxonomySidebar'

const LEF_ANCHORS = new Set(['f-lef', 'f-tef', 'f-cf', 'f-poa', 'f-vuln', 'f-tcap', 'f-rs'])

interface Props {
  id: string
  navigate: (path: string) => void
}

export function Workspace({ id, navigate }: Props) {
  const content = useContent()
  const [doc, setDoc] = useState<Analysis | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [inputHash, setInputHash] = useState('')
  const [preChecks, setPreChecks] = useState<Check[][] | null>(null)
  const [running, setRunning] = useState(false)
  const [runMsg, setRunMsg] = useState<string | null>(null)
  const docRef = useRef<Analysis | null>(null)
  const runs = useRuns(id)

  const validate = useCallback((a: Analysis) => {
    api.validate(a).then(
      (v) => {
        // Ignore an answer for a document that has since changed.
        if (docRef.current && docRef.current.states.length === v.states.length) setPreChecks(v.states.map((s) => s.checks))
      },
      () => setPreChecks(null),
    )
  }, [])

  const onSaved = useCallback(
    (hash: string, saved: Analysis) => {
      setInputHash(hash)
      validate(saved)
    },
    [validate],
  )
  const autosave = useAutosave(onSaved)
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
        validate(doc)
        document.title = `${doc.title} · FAIR risk workbench`
      },
      (e) =>
        live &&
        setLoadError(e instanceof ApiError && e.status === 404 ? 'This analysis doesn’t exist. It may have been deleted.' : String(e.message ?? e)),
    )
    runs.load().catch(() => undefined)
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, reset, validate])

  /** Apply an edit, re-render, and schedule an autosave. */
  const edit = useCallback(
    (fn: (a: Analysis) => Analysis) => {
      const cur = docRef.current
      if (!cur) return
      const next = fn(cur)
      docRef.current = next
      setDoc(next)
      setRunMsg(null)
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

  async function run() {
    const cur = docRef.current
    if (!cur || running) return
    setRunning(true)
    setRunMsg(null)
    try {
      if (!(await autosave.flush())) {
        setRunMsg('Couldn’t save the latest changes, so the run didn’t start. See the save status at the top.')
        return
      }
      const result = await api.runAnalysis(cur.id)
      setInputHash(result.inputHash)
      await runs.added(result)
      window.setTimeout(() => document.getElementById('sec-results')?.scrollIntoView({ block: 'start' }), 0)
    } catch (e) {
      if (!(e instanceof ApiError)) {
        setRunMsg(String(e))
        return
      }
      // Pre-check failure: go to the failing option and factor, as the prototype does.
      const first = e.errors[0]
      const where = first ? parseCheckPath(first.path, Object.fromEntries(Object.entries(content.factors).map(([k, f]) => [k, f.path]))) : null
      if (where) {
        if (where.index !== docRef.current?.active) edit((a) => ({ ...a, active: where.index }))
        const target = where.key ? factorAnchor(where.key) : 'sec-state'
        window.setTimeout(() => goto(target), 50)
      }
      setRunMsg(e.message)
    } finally {
      setRunning(false)
    }
  }

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

  // What the results area shows: a past run when one is selected, else the latest.
  const shown = runs.shown
  const history = runs.viewing
  const stale = !!runs.latest && runs.latest.inputHash !== inputHash
  let shownResult = shown?.results.states.find((s) => s.stateId === st.id) ?? null
  if (history && !shownResult) shownResult = shown?.results.states[0] ?? null
  const sidebarResult = !stale && !history ? (runs.latest?.results.states.find((s) => s.stateId === st.id) ?? null) : null

  const errorCount = preChecks ? preChecks.flat().filter((c) => c.level === 'error').length : 0
  const statusMsg =
    runMsg ??
    (errorCount
      ? `${errorCount} input ${errorCount === 1 ? 'issue' : 'issues'} to fix before running.`
      : stale
        ? 'Inputs changed. Run again to update results.'
        : runs.latest
          ? `Last run: ${runs.latest.iterations.toLocaleString('en-US')} simulated years per option.`
          : preChecks
            ? 'Ready to run.'
            : 'Enter your estimates, then run the simulation.')

  return (
    <>
      <header className="wrap top">
        <a
          href="/"
          className="back"
          onClick={async (e) => {
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
            e.preventDefault()
            // Save first so the home list shows the latest title and numbers.
            await autosave.flush()
            navigate('/')
          }}
        >
          <span aria-hidden="true">←</span> Workbench home
        </a>
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
        <TaxonomySidebar state={st} result={sidebarResult} onGoto={goto} />
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
          <ResultsSection
            key={history?.id ?? 'latest'}
            stateName={history && shownResult ? shownResult.name : st.name}
            result={shownResult}
            run={shown ? { iterations: shown.iterations, threshold: shown.threshold } : null}
            stale={stale}
            preChecks={preChecks?.[i] ?? []}
            settings={doc.settings}
            onSettings={(field: keyof Settings, value) => edit((a) => setPath(a, `settings.${field}`, value))}
            history={history ? { runAt: history.runAt, onBack: runs.back } : null}
            csvUrl={shown ? api.exportCsvUrl(doc.id, shown.id) : null}
          />
          {(doc.states.length > 1 || shown?.results.comparison) && (
            <CompareSection comparison={shown?.results.comparison ?? null} threshold={shown?.threshold ?? null} stale={stale && !history} />
          )}
          <RunHistory
            analysisId={doc.id}
            runs={runs.runs}
            shownId={shown?.id ?? null}
            latestId={runs.latest?.id ?? null}
            currentHash={inputHash}
            onView={(runId) => {
              void runs.view(runId).then(() => document.getElementById('sec-results')?.scrollIntoView({ block: 'start' }))
            }}
          />
          <ConformanceNote />
        </main>
      </div>
      <RunBar message={statusMsg} running={running} onRun={run} />
    </>
  )
}

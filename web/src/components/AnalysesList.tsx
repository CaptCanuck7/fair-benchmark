import { useCallback, useEffect, useRef, useState } from 'react'
import type { AnalysisListItem } from '../types'
import { api, ApiError } from '../api/client'
import { dateTime, money } from '../lib/format'
import { ConformanceNote, Intro } from './Intro'

interface Props {
  navigate: (path: string) => void
}

const NOT_AN_EXPORT = 'That file isn’t a FAIR workbench export. Choose a .json file exported from this tool.'

export function AnalysesList({ navigate }: Props) {
  const [items, setItems] = useState<AnalysisListItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    api.listAnalyses().then(setItems, (e: ApiError) => setError(e.message))
  }, [])

  useEffect(() => {
    document.title = 'FAIR risk workbench'
    load()
  }, [load])

  async function act(fn: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function importFile(file: File) {
    let raw: unknown
    try {
      raw = JSON.parse(await file.text())
    } catch {
      setError(NOT_AN_EXPORT)
      return
    }
    await act(async () => {
      try {
        const { doc } = await api.importAnalysis(raw)
        navigate(`/analyses/${doc.id}`)
      } catch (e) {
        if (e instanceof ApiError && e.status === 422) throw new ApiError(422, `${NOT_AN_EXPORT} (${e.message})`)
        throw e
      }
    })
  }

  return (
    <>
      <header className="wrap top">
        <div className="brand">FAIR risk workbench</div>
        <div className="row">
          <h1 className="pagetitle">Analyses</h1>
          <div className="actions">
            <button
              type="button"
              className="btn primary"
              disabled={busy}
              onClick={() => act(async () => navigate(`/analyses/${(await api.createAnalysis()).doc.id}`))}
            >
              New analysis
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => fileRef.current?.click()}>
              Import
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".json,application/json"
              hidden
              aria-label="Import an analysis JSON file"
              onChange={(e) => {
                const f = e.target.files?.[0]
                e.target.value = ''
                if (f) void importFile(f)
              }}
            />
          </div>
        </div>
        <Intro open={items?.length === 0} />
      </header>

      <main className="wrap">
        {error && (
          <div className="check error" role="alert">
            {error}
          </div>
        )}
        <section className="panel">
          {items == null && !error && <p className="muted">Loading…</p>}
          {items?.length === 0 && (
            <p>No saved analyses yet. Start a new one, or import a JSON file exported from this tool or the prototype.</p>
          )}
          {items?.map((a) => (
            <div className="item" key={a.id}>
              <div className="item-main">
                <a
                  className="t"
                  href={`/analyses/${a.id}`}
                  onClick={(e) => {
                    e.preventDefault()
                    navigate(`/analyses/${a.id}`)
                  }}
                >
                  {a.title || 'Untitled analysis'}
                </a>
                <div className="d">
                  {a.states} option{a.states === 1 ? '' : 's'} · updated {dateTime(a.updatedAt)}
                </div>
                {a.latestRun ? (
                  <div className="d">
                    Average annual loss:{' '}
                    {a.latestRun.options.map((o, k) => (
                      <span key={o.stateId}>
                        {k > 0 && ' · '}
                        {o.name} <b>{money(o.meanAnnualLoss)}</b>
                      </span>
                    ))}
                    {a.latestRun.stale && <span className="tag">inputs changed since this run</span>}
                  </div>
                ) : (
                  <div className="d">Not run yet</div>
                )}
              </div>
              <div className="item-actions">
                <button type="button" className="btn" onClick={() => navigate(`/analyses/${a.id}`)}>
                  Open
                </button>
                <button
                  type="button"
                  className="btn"
                  disabled={busy}
                  onClick={() => act(async () => { await api.duplicateAnalysis(a.id); load() })}
                >
                  Duplicate
                </button>
                {confirmDelete === a.id ? (
                  <>
                    <button
                      type="button"
                      className="btn danger"
                      disabled={busy}
                      onClick={() => act(async () => { await api.deleteAnalysis(a.id); setConfirmDelete(null); load() })}
                    >
                      Confirm delete
                    </button>
                    <button type="button" className="btn quiet" onClick={() => setConfirmDelete(null)}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <button type="button" className="btn quiet danger" onClick={() => setConfirmDelete(a.id)}>
                    Delete
                  </button>
                )}
              </div>
            </div>
          ))}
        </section>
        <ConformanceNote />
      </main>
    </>
  )
}

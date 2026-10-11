import { useCallback, useEffect, useState, type FormEvent } from 'react'
import type { LibraryEntry, LibraryEntryInput } from '../types'
import { api, ApiError } from '../api/client'

const SOURCES = [
  'IBM Cost of a Data Breach Report',
  'Verizon Data Breach Investigations Report',
  'Cyentia Information Risk Insights Study',
]

const EMPTY: LibraryEntryInput = {
  metric: '', value: 0, unit: '', segment: null, source: SOURCES[0], edition: '', url: '', page: null, quote: null,
}

/** The reference library: figures proposed by the refresh task or added by hand, approved before use. */
export function ReferenceLibrary({ externalEnabled }: { externalEnabled: boolean }) {
  const [entries, setEntries] = useState<LibraryEntry[] | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [runNote, setRunNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState<LibraryEntryInput>(EMPTY)

  const load = useCallback(() => {
    api.listLibrary().then(setEntries, (e: ApiError) => setError(e.message))
  }, [])
  useEffect(load, [load])

  // Follow a refresh run until it finishes.
  useEffect(() => {
    if (!runId) return
    const t = window.setInterval(() => {
      api.agentRun(runId).then((r) => {
        if (r.status === 'succeeded' || r.status === 'failed') {
          window.clearInterval(t)
          setRunId(null)
          setRunNote(r.status === 'failed' ? `The refresh failed: ${r.error}` : 'Refresh finished. Review the proposals below.')
          load()
        }
      })
    }, 3000)
    return () => window.clearInterval(t)
  }, [runId, load])

  async function act(fn: () => Promise<unknown>) {
    setError(null)
    try {
      await fn()
      load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    void act(async () => {
      await api.addLibraryEntry({ ...form, segment: form.segment || null, page: form.page || null, quote: form.quote || null })
      setForm(EMPTY)
      setAdding(false)
    })
  }

  const proposed = (entries ?? []).filter((e) => e.status === 'proposed')
  const approved = (entries ?? []).filter((e) => e.status === 'approved')

  return (
    <div>
      <p className="lede">
        Figures from annual reports, used as evidence only once approved. It starts empty: refresh it from the report
        sites, or add figures by hand.
      </p>
      <div className="row">
        <button
          type="button"
          className="btn"
          disabled={!!runId || !externalEnabled}
          title={externalEnabled ? undefined : 'Turn external sources on to refresh from the web.'}
          onClick={() =>
            void act(async () => {
              setRunNote(null)
              setRunId((await api.refreshLibrary()).runId)
            })
          }
        >
          {runId ? 'Refreshing…' : 'Refresh from the report sites'}
        </button>
        <button type="button" className="btn quiet" onClick={() => setAdding((a) => !a)}>
          {adding ? 'Cancel' : 'Add a figure by hand'}
        </button>
      </div>
      <div role="status" aria-live="polite" className="small muted">
        {runId ? 'The agent is reading the report pages. This takes a few minutes.' : runNote}
      </div>
      {error && (
        <div className="check error" role="alert">
          {error}
        </div>
      )}

      {adding && (
        <form className="editor" onSubmit={submit}>
          <div className="grid2">
            <label className="fld">
              <span>Metric</span>
              <input required value={form.metric} onChange={(e) => setForm({ ...form, metric: e.target.value })} />
            </label>
            <label className="fld">
              <span>Value</span>
              <input required type="number" step="any" value={form.value}
                     onChange={(e) => setForm({ ...form, value: Number(e.target.value) })} />
            </label>
            <label className="fld">
              <span>Unit</span>
              <input required value={form.unit} placeholder="USD, percent…"
                     onChange={(e) => setForm({ ...form, unit: e.target.value })} />
            </label>
            <label className="fld">
              <span>Segment (optional)</span>
              <input value={form.segment ?? ''} onChange={(e) => setForm({ ...form, segment: e.target.value })} />
            </label>
            <label className="fld">
              <span>Report</span>
              <select value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}>
                {SOURCES.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            <label className="fld">
              <span>Edition</span>
              <input required value={form.edition} placeholder="2025"
                     onChange={(e) => setForm({ ...form, edition: e.target.value })} />
            </label>
            <label className="fld">
              <span>Web address</span>
              <input required type="url" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
            </label>
            <label className="fld">
              <span>Page (optional)</span>
              <input value={form.page ?? ''} onChange={(e) => setForm({ ...form, page: e.target.value })} />
            </label>
          </div>
          <label className="fld">
            <span>Quote stating the figure (optional)</span>
            <textarea rows={2} value={form.quote ?? ''} onChange={(e) => setForm({ ...form, quote: e.target.value })} />
          </label>
          <div className="row">
            <button type="submit" className="btn primary">
              Add and approve
            </button>
          </div>
        </form>
      )}

      {proposed.length > 0 && (
        <>
          <h3>Proposed by the agent ({proposed.length})</h3>
          <ul className="evlist">
            {proposed.map((e) => (
              <li key={e.id} className="evitem">
                <Entry e={e} />
                <div className="draftactions">
                  <button type="button" className="btn primary" onClick={() => void act(() => api.reviewLibraryEntry(e.id, 'approve'))}>
                    Approve
                  </button>
                  <button type="button" className="btn quiet danger" onClick={() => void act(() => api.reviewLibraryEntry(e.id, 'reject'))}>
                    Reject
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      <h3>Approved ({approved.length})</h3>
      {entries == null ? (
        <p className="muted">Loading…</p>
      ) : approved.length === 0 ? (
        <p className="muted">No approved figures yet.</p>
      ) : (
        <ul className="evlist">
          {approved.map((e) => (
            <li key={e.id} className="evitem">
              <Entry e={e} />
              <div className="small muted">Approved by {e.approvedBy}.</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Entry({ e }: { e: LibraryEntry }) {
  return (
    <>
      <div className="evhead">
        <b>{e.metric}</b>
        {e.segment && <span className="tag">{e.segment}</span>}
      </div>
      <p>
        <b>{e.value.toLocaleString('en-US')}</b> {e.unit}
      </p>
      {e.quote && <blockquote className="sentence small">{e.quote}</blockquote>}
      <div className="small">
        {e.source} {e.edition}
        {e.page ? `, page ${e.page}` : ''} ·{' '}
        <a href={e.url} target="_blank" rel="noreferrer noopener" className="mono">
          {e.url}
        </a>
      </div>
    </>
  )
}

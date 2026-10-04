import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { QualityStatus, RegisterImport, RegisterRisk, TriageStatus } from '../types'
import { api, ApiError } from '../api/client'
import { dateTime } from '../lib/format'
import { TestDataNotice } from '../components/TestDataNotice'

interface Props {
  navigate: (path: string) => void
}

const QUALITY: Record<QualityStatus, string> = { ready: 'Ready', needs_info: 'Needs info' }
const TRIAGE: Record<TriageStatus, string> = { qualifies: 'Qualifies', screened_out: 'Screened out' }
const NOT_RUN = 'not_run'

export function RegisterList({ navigate }: Props) {
  const [risks, setRisks] = useState<RegisterRisk[] | null>(null)
  const [lastImport, setLastImport] = useState<RegisterImport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [quality, setQuality] = useState('')
  const [triage, setTriage] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    Promise.all([api.listRisks(), api.listRegisterImports()]).then(
      ([r, imports]) => {
        setRisks(r)
        setLastImport(imports[0] ?? null)
      },
      (e: ApiError) => setError(e.message),
    )
  }, [])

  useEffect(() => {
    document.title = 'Risk register · FAIR risk workbench'
    load()
  }, [load])

  async function importFile(file: File) {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const r = await api.importRegister(file)
      setStatus(
        `Imported ${r.filename}: ${r.rowCount} row${r.rowCount === 1 ? '' : 's'} gave ${r.riskCount} risk${r.riskCount === 1 ? '' : 's'} (${r.created} new, ${r.updated} updated).`,
      )
      load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const shown = useMemo(
    () =>
      (risks ?? []).filter(
        (r) => (!quality || (r.quality ?? NOT_RUN) === quality) && (!triage || (r.triage ?? NOT_RUN) === triage),
      ),
    [risks, quality, triage],
  )

  return (
    <>
      <header className="wrap top">
        <a
          href="/"
          className="back"
          onClick={(e) => {
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
            e.preventDefault()
            navigate('/')
          }}
        >
          <span aria-hidden="true">←</span> Workbench home
        </a>
        <div className="brand">FAIR risk workbench</div>
        <div className="row">
          <h1 className="pagetitle">Risk register</h1>
          <div className="actions">
            <button type="button" className="btn primary" disabled={busy} onClick={() => fileRef.current?.click()}>
              {busy ? 'Importing…' : 'Import register'}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              hidden
              aria-label="Import a register workbook (.xlsx)"
              onChange={(e) => {
                const f = e.target.files?.[0]
                e.target.value = ''
                if (f) void importFile(f)
              }}
            />
          </div>
        </div>
        <p className="intro">
          Import the tactical risk register workbook (.xlsx, up to 5 MB). Rows that share a risk ID become one risk with
          its monitoring updates. Scores are recalculated as impact × likelihood. Importing again updates risks with the
          same ID.
        </p>
      </header>

      <main className="wrap">
        <TestDataNotice />
        {error && (
          <div className="check error" role="alert">
            {error}
          </div>
        )}
        <div role="status" className={status ? 'check ok' : 'sr'}>
          {status}
        </div>

        <section className="panel">
          {lastImport && (
            <p className="muted small">
              Last import: {lastImport.filename}, {dateTime(lastImport.importedAt)}.
            </p>
          )}
          {risks == null && !error && <p className="muted">Loading…</p>}
          {risks?.length === 0 && <p>No register imported yet. Import a register workbook to list its risks here.</p>}
          {risks && risks.length > 0 && (
            <>
              <div className="filters">
                <label className="fld">
                  <span>Quality</span>
                  <select value={quality} onChange={(e) => setQuality(e.target.value)}>
                    <option value="">All</option>
                    <option value="ready">Ready</option>
                    <option value="needs_info">Needs info</option>
                    <option value={NOT_RUN}>Not checked yet</option>
                  </select>
                </label>
                <label className="fld">
                  <span>Triage</span>
                  <select value={triage} onChange={(e) => setTriage(e.target.value)}>
                    <option value="">All</option>
                    <option value="qualifies">Qualifies</option>
                    <option value="screened_out">Screened out</option>
                    <option value={NOT_RUN}>Not triaged yet</option>
                  </select>
                </label>
                <p className="muted small" aria-live="polite">
                  Showing {shown.length} of {risks.length} risks.
                </p>
              </div>
              <div className="tblwrap">
                <table className="reg">
                  <caption className="sr">Register risks</caption>
                  <thead>
                    <tr>
                      <th scope="col">Risk</th>
                      <th scope="col">Title</th>
                      <th scope="col">Category</th>
                      <th scope="col" className="num">
                        Baseline score
                      </th>
                      <th scope="col">Quality</th>
                      <th scope="col">Triage</th>
                      <th scope="col">Condition type</th>
                      <th scope="col">Analysis</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((r) => (
                      <tr key={r.riskId}>
                        <th scope="row">
                          <a
                            href={`/register/${encodeURIComponent(r.riskId)}`}
                            onClick={(e) => {
                              if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
                              e.preventDefault()
                              navigate(`/register/${encodeURIComponent(r.riskId)}`)
                            }}
                          >
                            {r.riskId}
                          </a>
                        </th>
                        <td className="wrapcell">{r.title ?? '—'}</td>
                        <td>{r.category ?? '—'}</td>
                        <td className="num">{r.baselineScore ?? '—'}</td>
                        <td>{r.quality ? <Status kind={r.quality} label={QUALITY[r.quality]} /> : <NotRun />}</td>
                        <td>{r.triage ? <Status kind={r.triage} label={TRIAGE[r.triage]} /> : <NotRun />}</td>
                        <td>{r.classification ? r.classification.replace(/_/g, ' ') : <NotRun />}</td>
                        <td>
                          {r.analysisId ? (
                            <a
                              href={`/analyses/${r.analysisId}`}
                              onClick={(e) => {
                                e.preventDefault()
                                navigate(`/analyses/${r.analysisId}`)
                              }}
                            >
                              Open
                            </a>
                          ) : (
                            <span className="muted">None</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      </main>
    </>
  )
}

function Status({ kind, label }: { kind: string; label: string }) {
  return <span className={`badge ${kind}`}>{label}</span>
}

function NotRun() {
  return <span className="muted">Not run</span>
}

import { useCallback, useEffect, useState } from 'react'
import type { AgentStatus, OutboundLogEntry } from '../types'
import { api, ApiError } from '../api/client'
import { dateTime } from '../lib/format'
import { ReferenceLibrary } from '../components/ReferenceLibrary'
import { SettingsForm } from '../components/SettingsForm'

interface Props {
  navigate: (path: string) => void
}

// Plain-language versions of the guard's reason codes (agent/app/guard.py).
const REASONS: Record<string, string> = {
  external_disabled: 'External sources are turned off',
  host_not_allowed: 'Site not on the allowed list',
  not_https: 'Not an https address',
  invalid_url: 'Address not allowed',
  encoded_path: 'Address hides its path with encoding',
  url_too_long: 'Address over 500 characters',
  url_query_too_long: 'Address carries over 120 characters of query text',
  query_too_long: 'Search over 120 characters',
  empty_query: 'Empty search',
  vendor_name_needs_approval: 'Names a vendor without approval',
  response_too_large: 'Response too large',
  too_many_redirects: 'Too many redirects',
}

function reasonText(code: string | null): string {
  if (!code) return ''
  if (code.startsWith('identifier:')) return `Contains an internal identifier (${code.slice(11).replace(/_/g, ' ')})`
  return REASONS[code] ?? code
}

export function Settings({ navigate }: Props) {
  const [status, setStatus] = useState<AgentStatus | null>(null)
  const [log, setLog] = useState<OutboundLogEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    Promise.all([api.agentStatus(), api.outboundLog()]).then(
      ([s, l]) => {
        setStatus(s)
        setLog(l)
      },
      (e: ApiError) => setError(e.message),
    )
  }, [])

  useEffect(() => {
    document.title = 'Settings · FAIR risk workbench'
    load()
  }, [load])

  return (
    <>
      <header className="wrap top">
        <a
          href="/register"
          className="back"
          onClick={(e) => {
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
            e.preventDefault()
            navigate('/register')
          }}
        >
          <span aria-hidden="true">←</span> Risk register
        </a>
        <div className="brand">FAIR risk workbench</div>
        <h1 className="pagetitle">Settings</h1>
      </header>

      <main className="wrap">
        {error && (
          <div className="check error" role="alert">
            {error}
          </div>
        )}

        <section className="panel sec" aria-labelledby="agent-h">
          <h2 id="agent-h" className="h2">
            Agent
          </h2>
          {!status && !error && <p className="muted">Loading…</p>}
          {status && (
            <>
              <div className={`check ${status.configured ? 'ok' : 'warn'}`}>
                {status.configured ? (
                  <>
                    <b>Agent is on.</b> Model {status.model}.
                  </>
                ) : (
                  <>
                    <b>Agent is off.</b> {status.reason}
                  </>
                )}
              </div>
              <SettingsForm status={status} onSaved={load} />
              <p className="cap">
                Changes here override the .env file and take effect on the agent’s next task. To go back to a .env
                value, choose “Follow the .env file” or clear the field.
              </p>
            </>
          )}
        </section>

        <section className="panel sec" aria-labelledby="lib-h">
          <h2 id="lib-h" className="h2">
            Reference library
          </h2>
          <ReferenceLibrary externalEnabled={!!status?.externalEnabled} />
        </section>

        <section className="panel sec" aria-labelledby="log-h">
          <div className="row spread">
            <h2 id="log-h" className="h2">
              Outbound requests
            </h2>
            <button type="button" className="btn" onClick={load}>
              Refresh
            </button>
          </div>
          <p className="lede">
            Every request the agent tried to send outside this computer, other than to the Claude API, and whether the
            guard allowed it. Internal identifiers are shown as placeholders such as [asset_id].
          </p>
          {log?.length === 0 && <p className="muted">No outbound requests yet.</p>}
          {log && log.length > 0 && (
            <div className="tblwrap">
              <table className="reg">
                <caption className="sr">Outbound request log, newest first</caption>
                <thead>
                  <tr>
                    <th scope="col">Time</th>
                    <th scope="col">Result</th>
                    <th scope="col">Tool</th>
                    <th scope="col">Destination</th>
                    <th scope="col">Search</th>
                  </tr>
                </thead>
                <tbody>
                  {log.map((e) => (
                    <tr key={e.id}>
                      <th scope="row">{dateTime(e.at)}</th>
                      <td className="wrapcell">
                        {e.allowed ? (
                          <span className="badge ready">Allowed</span>
                        ) : (
                          <>
                            <span className="badge needs_info">Blocked</span>{' '}
                            <span className="small">{reasonText(e.blockedReason)}</span>
                          </>
                        )}
                      </td>
                      <td>{e.tool}</td>
                      <td className="wrapcell mono">{e.destination}</td>
                      <td className="wrapcell">{e.query ?? <span className="muted">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </>
  )
}

import { useEffect, useState, type FormEvent } from 'react'
import type { AgentStatus, AppSettings } from '../types'
import { api, ApiError } from '../api/client'

interface Props {
  status: AgentStatus
  /** Called after a save so the page can reload the agent's effective values. */
  onSaved: () => void
}

/** Analyst name, triage threshold, external sources and allowed domains. */
export function SettingsForm({ status, onSaved }: Props) {
  const [s, setS] = useState<AppSettings | null>(null)
  const [name, setName] = useState('')
  const [threshold, setThreshold] = useState('6')
  const [domain, setDomain] = useState('')
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.getSettings().then((x) => {
      setS(x)
      setName(x.analystName ?? '')
      setThreshold(String(x.triageMinScore))
    })
  }, [])

  async function save(changes: Partial<AppSettings>, done: string) {
    setBusy(true)
    setMessage(null)
    try {
      const next = await api.putSettings(changes)
      setS(next)
      setMessage({ ok: true, text: done })
      onSaved()
    } catch (e) {
      setMessage({ ok: false, text: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }

  if (!s) return <p className="muted">Loading…</p>
  const domains = status.allowedDomains ?? []
  const external = s.externalEnabled === null ? 'env' : s.externalEnabled ? 'on' : 'off'

  function removeDomain(d: string) {
    if (!s) return
    if (s.extraDomains.includes(d)) {
      void save({ extraDomains: s.extraDomains.filter((x) => x !== d) }, `Removed ${d}.`)
    } else {
      void save({ removedDomains: [...s.removedDomains, d] }, `Removed ${d}.`)
    }
  }

  function addDomain(e: FormEvent) {
    e.preventDefault()
    if (!s) return
    const d = domain.trim().toLowerCase()
    if (!d) return
    const changes = s.removedDomains.includes(d)
      ? { removedDomains: s.removedDomains.filter((x) => x !== d) }
      : { extraDomains: [...s.extraDomains, d] }
    void save(changes, `Added ${d}.`).then(() => setDomain(''))
  }

  return (
    <div className="setform">
      <form
        className="grid2"
        onSubmit={(e) => {
          e.preventDefault()
          void save({ analystName: name, triageMinScore: Number(threshold) }, 'Saved.')
        }}
      >
        <label className="fld">
          <span>
            Your name <span className="hint">recorded on approvals, overrides and answers</span>
          </span>
          <input value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="fld">
          <span>
            Triage threshold <span className="hint">baseline score (impact × likelihood) that qualifies</span>
          </span>
          <input type="number" min={1} max={25} value={threshold} onChange={(e) => setThreshold(e.target.value)} />
        </label>
        <div>
          <button type="submit" className="btn" disabled={busy}>
            Save name and threshold
          </button>
        </div>
      </form>

      <fieldset className="rows">
        <legend>External sources</legend>
        {(['env', 'on', 'off'] as const).map((v) => (
          <label key={v} className="check-inline">
            <input
              type="radio"
              name="external"
              checked={external === v}
              disabled={busy}
              onChange={() =>
                void save({ externalEnabled: v === 'env' ? null : v === 'on' }, 'External sources updated.')
              }
            />{' '}
            {v === 'env'
              ? 'Follow the .env file (AGENT_EXTERNAL_ENABLED)'
              : v === 'on'
                ? 'On: public feeds and allowed sites'
                : 'Off: internal evidence and the reference library only'}
          </label>
        ))}
        <p className="cap">Now {status.externalEnabled ? 'on' : 'off'}.</p>
      </fieldset>

      <fieldset className="rows">
        <legend>Allowed sites</legend>
        <ul className="domains">
          {domains.map((d) => (
            <li key={d}>
              <span className="mono">{d}</span>{' '}
              <button type="button" className="btn quiet danger" disabled={busy} onClick={() => removeDomain(d)}>
                Remove {d}
              </button>
            </li>
          ))}
        </ul>
        <form className="row" onSubmit={addDomain}>
          <label className="fld">
            <span>Add a site</span>
            <input value={domain} placeholder="example.org" onChange={(e) => setDomain(e.target.value)} />
          </label>
          <button type="submit" className="btn" disabled={busy || !domain.trim()}>
            Add
          </button>
        </form>
        <p className="cap">
          Subdomains are included. The vulnerability feeds (NVD, CISA KEV, EPSS, MITRE ATT&amp;CK) are always reachable
          while external sources are on.
        </p>
      </fieldset>

      <div role="status" aria-live="polite" className={message ? (message.ok ? 'small' : 'check error') : 'sr'}>
        {message?.text}
      </div>
    </div>
  )
}

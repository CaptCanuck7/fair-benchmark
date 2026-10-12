import { useEffect, useState } from 'react'
import type { Conf, DecisionLogEntry, RegisterRiskDetail } from '../../types'
import type { Navigate } from '../../App'
import { api, ApiError } from '../../api/client'
import { useContent } from '../../content'
import { dateTime } from '../../lib/format'
import { factorKind, fmtMl, fmtSpan, words } from '../../lib/guided'

const STEPS: [DecisionLogEntry['step'], string][] = [
  ['quality', 'Quality check'],
  ['triage', 'Triage'],
  ['classification', 'Kind of weakness'],
  ['scenario', 'Scenario'],
  ['vectors', 'Attack paths'],
  ['evidence', 'Evidence'],
  ['estimate', 'Estimates'],
  ['analysis', 'Create analysis'],
]

const THING: Record<string, string> = {
  quality: 'the quality check',
  triage: 'the triage result',
  classification: 'the kind of weakness',
  scenario: 'the scenario',
  vectors: 'the attack paths',
}

const TRIAGE: Record<string, string> = { qualifies: 'qualifies', screened_out: 'screened out' }

interface Range {
  min: number
  ml: number
  max: number
  conf: Conf
}

/** Every recorded analyst action on the risk, grouped by step, oldest first (UI_REBUILD.md stage 4). */
export function DecisionRecord({ risk, nonMal, navigate }: { risk: RegisterRiskDetail; nonMal: boolean; navigate: Navigate }) {
  const content = useContent()
  const [rows, setRows] = useState<DecisionLogEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.decisionLog(risk.riskId).then(setRows, (e: ApiError) => setError(e.message))
  }, [risk.riskId])

  const plain = (k: string | null) => (k && content.factors[k] ? words(content, k, nonMal).plain : (k ?? ''))
  const range = (k: string | null, r: Range) => {
    if (!k || !content.factors[k]) return ''
    const kind = factorKind(content, k)
    return `${fmtSpan(kind, r.min, r.max).replace(' – ', ' to ')}, ${fmtMl(kind, r.ml)}`
  }

  /** What the analyst did, in a plain sentence. */
  function sentence(r: DecisionLogEntry, i: number, all: DecisionLogEntry[]): string {
    const d = (r.detail ?? {}) as Record<string, unknown>
    const thing = r.step === 'vectors' && nonMal ? 'the failure paths' : (THING[r.step] ?? 'the draft')
    switch (r.action) {
      case 'approve':
        return `Approved ${thing}`
      case 'edit': {
        const changed = (d.changed as string[] | undefined)?.map((c) => c.replace(/_/g, ' ')) ?? []
        return `Edited ${thing}${changed.length ? ` (changed: ${changed.join(', ')})` : ''}`
      }
      case 'reject':
        return `Rejected ${thing}`
      case 'override':
        return `Overrode triage from ${TRIAGE[String(d.from)] ?? d.from} to ${TRIAGE[String(d.to)] ?? d.to}`
      case 'reveal':
        return `Showed the agent’s range for ${plain(r.subject)}, ${d.enteredFirst ? 'after entering their own' : 'without entering their own first'}`
      case 'decide': {
        const rr = d.range as Range
        const what = range(r.subject, rr)
        const ph = d.placeholder ? ' (a placeholder)' : ''
        if (d.choice === 'agent') return `Took the agent’s range for ${plain(r.subject)}: ${what}`
        // The same factor's previous decision, to tell "kept" and "saved again" from a new range.
        const earlier = all
          .slice(0, i)
          .reverse()
          .find((x) => x.action === 'decide' && x.subject === r.subject)
        const prev = earlier?.detail?.choice === 'analyst' ? (earlier.detail.range as Range) : undefined
        const same = !!prev && (['min', 'ml', 'max', 'conf'] as const).every((k) => prev[k] === rr[k])
        if (!d.sawAgentRange)
          return same
            ? `Saved their range for ${plain(r.subject)} again: ${what}${ph}`
            : `Entered their own range for ${plain(r.subject)}: ${what}${ph}`
        return same
          ? `Kept their own range for ${plain(r.subject)}: ${what}${ph}`
          : `Entered a new range for ${plain(r.subject)} after seeing the agent’s: ${what}${ph}`
      }
      case 'clear':
        return `Cleared the decision for ${plain(r.subject)}`
      case 'answer':
        return `Recorded ${d.team}’s answer to the data request about ${plain(String(d.factor ?? ''))}`
      case 'create_analysis': {
        const n = (d.factorsPushed as string[] | undefined)?.length ?? 0
        return `Created an analysis with ${n} decided factor${n === 1 ? '' : 's'}${d.acknowledgedStale ? `, confirming it although ${d.stale} had changed since the estimates were drafted` : ''}`
      }
    }
  }

  /** For a decision: whether the range was entered before seeing the agent's. */
  function anchor(r: DecisionLogEntry): string | null {
    if (r.action !== 'decide') return null
    const d = r.detail ?? {}
    if (!d.sawAgentRange) return 'Entered without seeing the agent’s range.'
    if (d.enteredBeforeReveal) return 'The analyst entered a range of their own before the agent’s was shown.'
    return 'The agent’s range was shown before the analyst entered one.'
  }

  // Reviews made before the record existed: any review date earlier than the first row.
  const first = rows?.[0]?.at
  const reviewed = [
    ...Object.values(risk.intake).map((d) => d?.reviewedAt),
    risk.scenario?.reviewedAt,
    risk.vectors?.reviewedAt,
    ...(risk.estimates?.factors.map((f) => f.decision?.at) ?? []),
  ].filter((x): x is string => !!x)
  const unrecorded = reviewed.some((at) => !first || at < first)

  return (
    <section aria-labelledby="step-h">
      <h1 id="step-h" className="steptitle">
        Decision record
      </h1>
      <p className="muted">
        Every decision made on this risk, with who made it, when, and why. Entries are added as decisions are made and
        are never changed.
      </p>
      {rows && unrecorded && (
        <div className="check info" role="note">
          {first
            ? `The record starts from when this feature was installed, so reviews of this risk made before it aren’t listed. Its first entry here is from ${dateTime(first)}.`
            : 'This risk was reviewed before the decision record was installed. Those reviews aren’t listed; new decisions will be.'}
        </div>
      )}
      {error && (
        <div className="check error" role="alert">
          {error}
        </div>
      )}
      {!rows && !error && <p className="muted">Loading…</p>}
      {rows && rows.length === 0 && !unrecorded && <p className="muted">No decisions have been recorded yet.</p>}
      {rows &&
        STEPS.map(([step, label]) => {
          const group = rows.map((r, i) => [r, i] as const).filter(([r]) => r.step === step)
          if (!group.length) return null
          return (
            <section key={step} className="recgroup" aria-labelledby={`rec-${step}`}>
              <h2 id={`rec-${step}`} className="h3">
                {step === 'vectors' && nonMal ? 'Failure paths' : label}
              </h2>
              <ol className="reclist">
                {group.map(([r, i]) => (
                  <li key={r.id} className="recitem">
                    <div className="recmeta">
                      <time dateTime={r.at}>{dateTime(r.at)}</time> · {r.by}
                    </div>
                    <p className="recwhat">
                      {sentence(r, i, rows)}
                      {r.action === 'create_analysis' && r.subject && (
                        <>
                          {' '}
                          <a
                            href={`/analyses/${r.subject}`}
                            onClick={(e) => {
                              if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
                              e.preventDefault()
                              navigate(`/analyses/${r.subject}`)
                            }}
                          >
                            Open it
                          </a>
                        </>
                      )}
                    </p>
                    {anchor(r) && <p className="small muted">{anchor(r)}</p>}
                    {r.reason ? (
                      <p className="recwhy">
                        <b>Why:</b> <span className="prewrap">{r.reason}</span>
                      </p>
                    ) : (
                      // Edits, rejects and overrides always carry one; old rows may not.
                      ['edit', 'reject', 'override'].includes(r.action) && <p className="small muted">No reason given.</p>
                    )}
                  </li>
                ))}
              </ol>
            </section>
          )
        })}
    </section>
  )
}

// The guided risk page (UI_REBUILD.md): its steps, what each says about
// itself in the rail, and the plain wording for factors.

import type { Content, EstimateFactor, FactorWords, Kind, RegisterRiskDetail } from '../types'
import { conditionLabel, QUALITY, TRIAGE } from './register'
import { money, trim } from './format'

export type StepId = 'quality' | 'triage' | 'weakness' | 'scenario' | 'paths' | 'evidence' | 'estimates' | 'summary'

export const STEP_IDS: StepId[] = ['quality', 'triage', 'weakness', 'scenario', 'paths', 'evidence', 'estimates', 'summary']

const NON_MALICIOUS = ['Error (accidental)', 'Failure (system or vendor)', 'Natural']

/** True when "attempt" reads wrongly: an accident, a failure or a natural event. */
export function nonMalicious(risk: RegisterRiskDetail): boolean {
  const t = risk.scenario?.effective.threat_type
  if (t) return NON_MALICIOUS.includes(t)
  return risk.vectors?.effective.kind === 'failure_paths'
}

/** A factor's plain label, question and "Where this fits" text, for this risk's threat type. */
export function words(content: Content, factor: string, nonMal: boolean): FactorWords {
  const f = content.factors[factor]
  const base = { plain: f.plain, question: f.question, context: f.context, check: f.check }
  return nonMal && f.occurrence ? { ...base, ...f.occurrence } : base
}

/** "FAIR calls this vulnerability · % of threat events that become loss events" */
export function fairTerm(content: Content, factor: string): string {
  const f = content.factors[factor]
  return `FAIR calls this ${f.label.toLowerCase()} · ${f.unit}`
}

export interface StepInfo {
  id: StepId
  n: number
  label: string
  /** The step's status in words, for the rail. */
  status: string
  /** Why the step can't start yet, or null. */
  blocked: string | null
  /** The step is waiting on the analyst. */
  needsAnalyst: boolean
}

const reviewWord = (status: string, drafted: string): string =>
  status === 'approved' ? 'Approved' : status === 'edited' ? 'Edited and approved' : status === 'rejected' ? 'Rejected' : drafted

const usable = (d: { status: string } | null) => !!d && (d.status === 'approved' || d.status === 'edited')

/** The eight steps, with their status, from what the api returned. */
export function steps(risk: RegisterRiskDetail, currentFactor?: string): StepInfo[] {
  const { quality, triage, classification } = risk.intake
  const ready = quality?.effective.status === 'ready'
  const qualifies = triage?.effective.status === 'qualifies'
  const est = risk.estimates
  const openReqs = risk.dataRequests.filter((r) => r.status === 'open').length
  const nonMal = nonMalicious(risk)

  const out: Omit<StepInfo, 'n'>[] = [
    {
      id: 'quality',
      label: 'Quality check',
      status: quality ? reviewWord(quality.status, `${QUALITY[quality.effective.status]}, to review`) : 'Not run yet',
      blocked: null,
      needsAnalyst: !!quality && (quality.status === 'drafted' || !ready),
    },
    {
      id: 'triage',
      label: 'Triage',
      status: triage
        ? `${TRIAGE[triage.effective.status]}${triage.effective.override ? ' (overridden)' : triage.status === 'drafted' ? ', to review' : ''}`
        : 'Not run yet',
      blocked: triage ? null : quality && !ready ? 'Triage waits until the quality check finds the entry ready.' : null,
      needsAnalyst: !!triage && (triage.status === 'drafted' || !qualifies),
    },
    {
      id: 'weakness',
      label: 'Kind of weakness',
      status: classification
        ? classification.status === 'drafted'
          ? `${conditionLabel(classification.effective.primary_type)}, to review`
          : reviewWord(classification.status, '')
        : 'Not run yet',
      blocked: classification
        ? null
        : (triage && !qualifies) || (quality && !ready)
          ? 'Only risks that are ready and qualify go on to classification.'
          : null,
      needsAnalyst: !!classification && classification.status === 'drafted',
    },
    {
      id: 'scenario',
      label: 'Scenario',
      status: risk.scenario ? reviewWord(risk.scenario.status, 'Agent draft, to review') : 'Not drafted',
      blocked: risk.scenario ? null : risk.blocked.scenario,
      needsAnalyst: !usable(risk.scenario),
    },
    {
      id: 'paths',
      label: nonMal ? 'Failure paths' : 'Attack paths',
      status: risk.vectors
        ? risk.vectorsStale
          ? 'Out of date'
          : reviewWord(risk.vectors.status, 'Agent draft, to review')
        : 'Not drafted',
      blocked: risk.vectors ? null : risk.blocked.vectors,
      needsAnalyst: !risk.vectors || risk.vectors.status === 'drafted' || risk.vectorsStale,
    },
    {
      id: 'evidence',
      label: 'Evidence',
      status:
        risk.evidenceRun || risk.evidence.length
          ? `${risk.evidence.length} item${risk.evidence.length === 1 ? '' : 's'} · ${openReqs} request${openReqs === 1 ? '' : 's'} open`
          : 'Not gathered',
      blocked: risk.evidenceRun || risk.evidence.length ? null : risk.blocked.evidence,
      needsAnalyst: !risk.evidenceRun && !risk.evidence.length,
    },
    {
      id: 'estimates',
      label: 'Estimates',
      status: !est
        ? 'Not drafted'
        : currentFactor && est.factors.some((f) => f.factor === currentFactor)
          ? `Factor ${est.factors.findIndex((f) => f.factor === currentFactor) + 1} of ${est.factors.length}`
          : `${est.decided} of ${est.factors.length} decided`,
      blocked: est ? null : risk.blocked.estimates,
      needsAnalyst: !est || est.decided < est.factors.length,
    },
    {
      id: 'summary',
      label: 'Summary',
      status: risk.analysisId ? 'Analysis created' : est ? 'Ready to review' : 'After estimates',
      blocked: usable(risk.scenario) ? null : 'Approve or edit the scenario first: it becomes the analysis scope.',
      needsAnalyst: true,
    },
  ]
  return out.map((s, i) => ({ ...s, n: i + 1 }))
}

/** Where /register/{riskId} opens: the first step that needs the analyst and can start. */
export function firstStep(risk: RegisterRiskDetail): StepId {
  const all = steps(risk)
  return (all.find((s) => s.needsAnalyst && !s.blocked) ?? all[0]).id
}

/** "0.5 – 5", "2 – 30%", "$150K – $2M" */
export function fmtSpan(kind: Kind, min: number | null, max: number | null): string {
  if (min == null || max == null) return '—'
  if (kind === 'money') return `${money(min)} – ${money(max)}`
  if (kind === 'pct') return `${trim(min)} – ${trim(max)}%`
  if (kind === 'score') return `${trim(min)} – ${trim(max)}`
  return `${trim(min)} – ${trim(max)}`
}

/** "most likely 10%" */
export function fmtMl(kind: Kind, ml: number | null): string {
  if (ml == null) return ''
  if (kind === 'money') return `most likely ${money(ml)}`
  if (kind === 'pct') return `most likely ${trim(ml)}%`
  if (kind === 'score') return `most likely ${trim(ml)}`
  return `most likely ${trim(ml)}`
}

/** "2 – 30%, most likely 10%" */
export function fmtRange(kind: Kind, r: { min: number | null; ml: number | null; max: number | null }): string {
  return `${fmtSpan(kind, r.min, r.max)}, ${fmtMl(kind, r.ml)}`
}

/** The unit shown inside a range field. */
export function fieldUnit(kind: Kind): { before?: string; after?: string } {
  if (kind === 'money') return { before: '$' }
  if (kind === 'pct') return { after: '%' }
  if (kind === 'score') return { after: 'of 100' }
  return { after: 'a year' }
}

/** The address of a step, or of one factor in the Estimates step. */
export function stepPath(riskId: string, step: StepId | 'entry' | 'record', factor?: string): string {
  const base = `/register/${encodeURIComponent(riskId)}/${step}`
  return factor ? `${base}/${encodeURIComponent(factor)}` : base
}

/** First line of a reason, for compact boxes. */
export function firstLine(text: string | null | undefined): string {
  if (!text) return ''
  const line = text.trim().split(/\n/)[0]
  const sentence = /^(.+?[.!?])(\s|$)/.exec(line)?.[1] ?? line
  return sentence.length > 140 ? sentence.slice(0, 137).trimEnd() + '…' : sentence
}

export const factorKind = (content: Content, f: EstimateFactor | string): Kind =>
  content.factors[typeof f === 'string' ? f : f.factor].kind as Kind

// Labels for register statuses, condition types and quality-gap fields.

import type { QualityStatus, TriageStatus } from '../types'

export const QUALITY: Record<QualityStatus, string> = { ready: 'Ready', needs_info: 'Needs info' }
export const TRIAGE: Record<TriageStatus, string> = { qualifies: 'Qualifies', screened_out: 'Screened out' }

export const CONDITION: Record<string, string> = {
  unsupported_software: 'Unsupported software',
  missing_control: 'Missing control',
  misconfiguration: 'Misconfiguration',
  process_gap: 'Process gap',
  third_party: 'Third party',
  other: 'Other',
}

export const conditionLabel = (t: string | null | undefined) => (t ? (CONDITION[t] ?? t.replace(/_/g, ' ')) : '')

export const CONFIDENCE: Record<string, string> = { low: 'Low', med: 'Medium', high: 'High' }

/** Register fields and analysis sections named in quality gaps. */
export const GAP_FIELD: Record<string, string> = {
  assets: 'Assets',
  environment: 'Environment',
  risk_owner: 'Risk owner',
  baseline_impact: 'Baseline impact',
  baseline_likelihood: 'Baseline likelihood',
  risk_action: 'Risk action',
  mitigation_plan: 'Mitigation plan',
  risk_statement: 'Risk statement',
  detailed_analysis: 'Detailed risk analysis',
  baseline_controls: 'Baseline controls',
  exploit_paths: 'Exploit paths',
  risk_analysis: 'Risk analysis',
}

export const gapFieldLabel = (f: string) => GAP_FIELD[f] ?? f.replace(/_/g, ' ')

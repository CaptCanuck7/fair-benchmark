// Mirrors api/app/schemas.py (the analysis document) and the run results
// built in api/app/engine/simulate.py.

export type Conf = 'low' | 'med' | 'high'
export type Kind = 'freq' | 'pct' | 'score' | 'money'

export interface Dist {
  min: number | null
  ml: number | null
  max: number | null
  conf: Conf
  src: string
}

export type LefMode = 'tef_vuln' | 'cf_poa' | 'lef'
export type VulnMode = 'direct' | 'tcap_rs'

export interface LefInputs {
  mode: LefMode
  vulnMode: VulnMode
  lef: Dist
  tef: Dist
  cf: Dist
  poa: Dist
  vuln: Dist
  tcap: Dist
  rs: Dist
}

export interface PrimaryLoss {
  productivity: Dist
  response: Dist
  replacement: Dist
}

export interface SecondaryLoss {
  response: Dist
  fines: Dist
  competitive: Dist
  reputation: Dist
}

export interface State {
  id: string
  name: string
  notes: string
  cost: number | null
  lef: LefInputs
  primary: PrimaryLoss
  slef: Dist
  secondary: SecondaryLoss
}

export interface Scope {
  asset: string
  threatCommunity: string
  threatType: string
  effect: string
  condition: string
  controls: string
  notes: string
}

export interface Settings {
  iterations: number
  seed: number
  threshold: number | null
}

export interface Analysis {
  format: 'fair-workbench'
  version: number
  id: string
  title: string
  createdAt: string
  updatedAt: string
  scope: Scope
  settings: Settings
  states: State[]
  active: number
  summary?: Record<string, unknown> | null
}

// ---------------------------------------------------------------- content

export interface FactorInfo {
  path: string
  label: string
  unit: string
  kind: Kind
  help: string
  data: string
}

export interface Content {
  factors: Record<string, FactorInfo>
  forms: { primary: { key: string; label: string }[]; secondary: { key: string; label: string }[] }
  confidence: Record<Conf, { label: string; lam: number }>
  placeholders: Record<Kind, [string, string, string]>
}

// ---------------------------------------------------------------- checks and results

export type CheckLevel = 'error' | 'warn' | 'info' | 'ok'

export interface Check {
  level: CheckLevel
  code: string
  title: string
  detail: string
  message: string
  path?: string
  stateIndex?: number
  stateId?: string
}

export interface CurvePoint {
  x: number
  y: number
}

export interface Histogram {
  max: number
  binWidth: number
  total: number
  bins: { x0: number; x1: number; count: number; share: number }[]
}

export interface StateResult {
  stateId: string
  name: string
  cost: number | null
  meanAnnualLoss: number
  p10: number
  p50: number
  p90: number
  p95: number
  p99: number
  max: number
  chanceAnyLoss: number
  chanceAboveThreshold: number | null
  lefMean: number
  lefP10: number
  lefP90: number
  singleLossMean: number
  singleLossP10: number
  singleLossP50: number
  singleLossP90: number
  derivedVulnerability: number | null
  secondaryShareOfLoss: number
  secondaryShareOfEvents: number
  events: number
  breakdown: Record<string, number>
  exceedanceCurve: CurvePoint[]
  histogram: Histogram | null
  checks: Check[]
}

export interface ComparisonRow {
  stateId: string
  name: string
  meanAnnualLoss: number
  p90: number
  p95: number
  chanceAboveThreshold: number | null
  cost: number | null
  reduction: number | null
  reductionPct: number | null
  netBenefit: number | null
  return: number | null
}

export interface Comparison {
  rows: ComparisonRow[]
  checks: Check[]
  curves: { xMax: number; series: { stateId: string; name: string; points: CurvePoint[] }[] }
}

export interface RunResults {
  runAt: string
  iterations: number
  seed: number
  threshold: number | null
  states: StateResult[]
  comparison: Comparison | null
}

export interface Run {
  id: string
  analysisId: string
  runAt: string
  iterations: number
  seed: number
  threshold: number | null
  inputHash: string
  results: RunResults
  documentSnapshot: Analysis
}

export interface RunSummary {
  id: string
  analysisId: string
  runAt: string
  iterations: number
  seed: number
  threshold: number | null
  inputHash: string
  options: { stateId: string; name: string; meanAnnualLoss: number; p90: number; p95: number; chanceAnyLoss: number }[]
}

export interface AnalysisListItem {
  id: string
  title: string
  states: number
  createdAt: string
  updatedAt: string
  inputHash: string
  latestRun: {
    id: string
    runAt: string
    inputHash: string
    stale: boolean
    options: { stateId: string; name: string; meanAnnualLoss: number }[]
  } | null
}

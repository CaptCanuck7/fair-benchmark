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

// --- Tactical risk register (mirrors api/app/routers/register.py) ---

export type QualityStatus = 'ready' | 'needs_info'
export type TriageStatus = 'qualifies' | 'screened_out'

export interface RegisterRisk {
  riskId: string
  title: string | null
  category: string | null
  assetIds: string[]
  baselineImpact: number | null
  baselineLikelihood: number | null
  baselineScore: number | null
  targetScore: number | null
  residualScore: number | null
  structured: boolean
  monitoringCount: number
  /** Null until the agent's quality, triage and classification steps have run. */
  quality: QualityStatus | null
  triage: TriageStatus | null
  classification: string | null
  analysisId: string | null
}

export interface MonitoringUpdate {
  taskName: string | null
  updateText: string | null
  residualImpact: number | null
  residualLikelihood: number | null
  residualScore: number | null
  completedDate: string | null
}

/** Register fields keyed as in api/app/register/parser.py COLUMNS. */
export type RegisterFields = Record<string, string | number | null> & { asset_ids?: string[] }

export interface RegisterRiskDetail extends RegisterRisk {
  fields: RegisterFields
  /** risk_statement, detailed_analysis, baseline_controls, exploit_paths, preamble; or raw when unstructured. */
  sections: Record<string, string>
  monitoring: MonitoringUpdate[]
  import: { importId: string; filename: string; importedAt: string } | null
  drafts: unknown[]
  evidence: unknown[]
  dataRequests: unknown[]
}

export interface RegisterImportResult {
  importId: string
  filename: string
  importedAt: string
  rowCount: number
  riskCount: number
  created: number
  updated: number
}

export interface RegisterImport {
  importId: string
  filename: string
  importedAt: string
  rowCount: number
  riskCount: number
}

// --- Agent (mirrors api/app/routers/agent.py) ---

export interface AgentStatus {
  configured: boolean
  /** Why the agent is off, in words for the analyst. */
  reason: string | null
  model: string | null
  externalEnabled: boolean
  allowedDomains?: string[]
}

export interface OutboundLogEntry {
  id: number
  agentRunId: string | null
  tool: string
  /** Register and evidence identifiers are already redacted, e.g. "[asset_id]". */
  destination: string
  query: string | null
  allowed: boolean
  blockedReason: string | null
  at: string
}

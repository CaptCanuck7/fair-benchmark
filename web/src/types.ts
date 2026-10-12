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
  /** Null until run, or when the pipeline stopped earlier (needs_info stops before triage). */
  quality: QualityStatus | null
  triage: TriageStatus | null
  triageOverridden: boolean
  /** Condition type: unsupported_software, missing_control, misconfiguration, process_gap, third_party, other. */
  classification: string | null
  secondaryClassification: string | null
  /** Why the risk stopped: the gaps for needs_info, the reason for screened out. */
  note: string | null
  agent: { state: 'running' | 'failed' | null; error: string | null }
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
  /** The current intake results; null for a stage not run or not reached. */
  intake: {
    quality: Draft<QualityResult> | null
    triage: Draft<TriageResult> | null
    classification: Draft<ClassificationResult> | null
  }
  scenario: Draft<ScenarioDraft> | null
  vectors: Draft<VectorsDraft> | null
  /** The vectors were built from a scenario that has since changed. */
  vectorsStale: boolean
  /** Why each analyst-started task can't run yet; null when it can. */
  blocked: { scenario: string | null; vectors: string | null; evidence: string | null; estimates: string | null }
  /** First-pass estimates. Agent ranges are null until revealed, factor by factor. */
  estimates: EstimatesView | null
  triageThreshold: number
  drafts: Draft<unknown>[]
  runs: AgentRun[]
  evidence: EvidenceItem[]
  dataRequests: DataRequest[]
  /** The latest successful evidence run, or null. */
  evidenceRun: EvidenceRun | null
}

export type DraftStatus = 'drafted' | 'approved' | 'edited' | 'rejected'

/** Something the agent drafted (mirrors api/app/routers/register.py draft_out). */
export interface Draft<T> {
  id: number
  kind: string
  status: DraftStatus
  payload: T
  editedPayload: T | null
  /** The analyst's edit if there is one, else the draft. */
  effective: T
  reviewer: string | null
  reviewedAt: string | null
  agentRunId: string | null
  draftedAt: string | null
  model: string | null
  promptVersion: string | null
}

export interface QualityGap {
  field: string
  problem: string
  source: 'rule' | 'agent'
  blocking: boolean
}

export interface QualityResult {
  status: QualityStatus
  gaps: QualityGap[]
  questions: string[]
  checks: { namesAsset: boolean; namesCondition: boolean; namesLossPath: boolean }
  /** Fields and model checks ("agent:condition") that made it needs_info. */
  blockedBy: string[]
  unmetChecks?: string[]
  wouldQualify: boolean
}

export interface TriageResult {
  status: TriageStatus
  score: number | null
  threshold: number
  /** The rule that decided, in words. */
  rule: string
  reason: string | null
  advisory: string | null
  noteError: string | null
  override?: { from: TriageStatus; reason: string; by: string; at: string }
}

export interface ClassificationResult {
  primary_type: string
  secondary_type: string | null
  confidence: 'low' | 'med' | 'high'
  reason: string
}

export interface AgentRun {
  id: string
  task: string
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  model: string | null
  promptVersion: string | null
  inputHash: string | null
  inputTokens: number
  outputTokens: number
  startedAt: string
  finishedAt: string | null
  error: string | null
}

export interface RegisterImportResult {
  importId: string
  filename: string
  importedAt: string
  rowCount: number
  riskCount: number
  created: number
  updated: number
  /** Risks queued for the intake checks, or why none were (agent off). */
  checks: { queued: string[]; agentOff: string | null }
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
  triageMinScore?: number
  analystName?: string | null
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

// --- Scenario and vectors drafts (mirror agent/app/schemas.py) ---

export const THREAT_TYPES_LIST = [
  'Malicious, external',
  'Malicious, internal',
  'Error (accidental)',
  'Failure (system or vendor)',
  'Natural',
] as const
export const EFFECTS_LIST = ['Confidentiality', 'Integrity', 'Availability'] as const

export type ControlFactor = 'frequency' | 'susceptibility' | 'magnitude'

export interface ScenarioControl {
  control: string
  factor: ControlFactor
  helps: boolean
  note: string | null
}

export interface ScenarioAlternative {
  title: string
  asset: string
  threat_community: string
  threat_type: string
  effect: string
  split_reason: 'threat_type_or_effect_differs' | 'data_exposure_differs' | 'mitigation_differs'
  reason: string
}

export interface ScenarioDraft {
  asset: string
  threat_community: string
  threat_type: string
  effect: string
  condition: string
  controls: ScenarioControl[]
  scenario_sentence: string
  notes: string[]
  alternatives: ScenarioAlternative[]
}

export interface PathStep {
  text: string
  controls: string[]
}

export interface ThreatPath {
  title: string
  origin: 'from_register' | 'agent_drafted' | 'analyst'
  steps: PathStep[]
  what_fails: string | null
  makes_worse: string[]
  limits: string[]
}

export interface VectorsDraft {
  kind: 'attack_vectors' | 'failure_paths'
  paths: ThreatPath[]
  basedOn?: { scenarioDraftId: number; scenarioHash: string }
}

export type ReviewAction = 'approve' | 'edit' | 'reject'

// --- Evidence, data requests, settings and the reference library ---

export type FactorGroup = 'frequency' | 'susceptibility' | 'primary' | 'secondary'

export interface EvidenceItem {
  id: number
  origin: 'internal' | 'external'
  sourceType: string
  sourceName: string
  /** A sheet and record ID, a URL, or "Data request answered by …". */
  citation: string
  publishedAt: string | null
  retrievedAt: string
  summary: string
  value: number | null
  unit: string | null
  factors: string[]
  stale: boolean
  groups: FactorGroup[]
  /** Set when the item is an answer to this data request. */
  fromDataRequest: number | null
  /** Whether `value` was found in the cited record; null for items stored before the check. */
  valueCheck?: 'found' | 'not_found' | 'not_checked' | null
  /** The cited record's fields (internal rows, library entries); null when there is none. */
  sourceFields?: Record<string, unknown> | null
}

export interface DataRequest {
  id: number
  team: string
  question: string
  factor: string
  reason: string
  status: 'open' | 'answered'
  answer: string | null
  answeredBy: string | null
  answeredAt: string | null
  groups: FactorGroup[]
}

export interface EvidenceRun {
  id: string
  finishedAt: string | null
  model: string | null
  toolCalls: number | null
  /** Items dropped because no tool returned their citation. */
  rejected: { citation: string; summary?: string; reason: string }[]
  notes: { toolsOffered?: string[]; cveLookupsOffered?: boolean; cveLookupsMade?: number; backstopGroups?: string[] }
  /** What each source did in this run; null for runs from before it was recorded. */
  coverage?: SourceCoverage | null
}

export type CoverageReason = 'external_off' | 'threat_type' | 'blocked' | 'failed' | 'budget' | 'not_called'

export interface ToolCoverage {
  offered: boolean
  required: boolean
  calls: number
  blocked: number
  failed: number
  /** Calls that ran: not blocked, not failed. */
  checks: number
  /** Accepted evidence items citing what this tool returned. */
  items: number
  reason: CoverageReason | null
}

export interface SourceCoverage {
  tools: Record<string, ToolCoverage>
  budgetSpent: boolean
  /** The reference library had no approved entries when the run looked. */
  libraryEmpty?: boolean
}

export interface AppSettings {
  analystName: string | null
  triageMinScore: number
  /** null: follow .env (AGENT_EXTERNAL_ENABLED). */
  externalEnabled: boolean | null
  extraDomains: string[]
  removedDomains: string[]
}

export interface LibraryEntry {
  id: number
  metric: string
  value: number
  unit: string
  segment: string | null
  source: string
  edition: string
  url: string
  page: string | null
  retrievedAt: string
  approvedBy: string | null
  status: 'proposed' | 'approved' | 'rejected'
  quote: string | null
  agentRunId: string | null
  citation: string
}

export type LibraryEntryInput = Pick<LibraryEntry, 'metric' | 'value' | 'unit' | 'segment' | 'source' | 'edition' | 'url' | 'page' | 'quote'>

// --- Estimates, the anchoring guard and provenance ---

export interface RangeValue {
  min: number | null
  ml: number | null
  max: number | null
  conf: Conf
}

export interface EstimateDecision {
  choice: 'agent' | 'analyst'
  min: number
  ml: number
  max: number
  conf: Conf
  /** The analyst's reasoning, or the agent's rationale when its range was taken. */
  rationale: string | null
  evidenceIds: number[]
  /** A stand-in until better data arrives; absent on decisions from before it was recorded. */
  placeholder?: boolean
  /** The analyst's optional note on taking the agent's range. */
  note?: string | null
  by: string
  at: string
  revealedFirst?: boolean
  evidenceMatch?: 'direct' | 'related'
}

/** The reasoning sent with a decision. */
export interface DecisionWhy {
  rationale?: string
  evidenceIds?: number[]
  placeholder?: boolean
  note?: string
}

/** One row of a risk's decision record (append-only). */
export interface DecisionLogEntry {
  id: number
  at: string
  by: string
  step: 'quality' | 'triage' | 'classification' | 'scenario' | 'vectors' | 'evidence' | 'estimate' | 'analysis'
  subject: string | null
  action:
    | 'approve'
    | 'edit'
    | 'reject'
    | 'override'
    | 'reveal'
    | 'decide'
    | 'clear'
    | 'answer'
    | 'create_analysis'
  reason: string | null
  detail: Record<string, unknown> | null
}

export interface EstimateFactor {
  factor: string
  status: 'estimated' | 'unestimated'
  revealed: boolean
  /** Null until revealed. */
  agent: {
    min: number
    ml: number
    max: number
    conf: Conf
    rationale: string
    evidenceIds: number[]
    basis: string
    /** related: no cited item is tagged to this factor. Absent on older drafts. */
    evidenceMatch?: 'direct' | 'related'
  } | null
  unestimated: { reason: string; dataRequestId: number | null } | null
  reveal: { analystRange: RangeValue | null; enteredBeforeReveal: boolean; revealedAt: string } | null
  decision: EstimateDecision | null
}

export interface EstimatesView {
  draftId: number
  method: { mode: LefMode; vuln_mode: VulnMode; reason: string }
  factors: EstimateFactor[]
  decided: number
  agentRunId: string | null
  /** What changed since these estimates were drafted. */
  stale: { scenario: boolean; evidence: boolean }
}

export interface ProvenanceFactor {
  stateId: string
  factor: string
  origin: 'agent' | 'analyst'
  approvedBy: string | null
  approvedAt: string | null
  range: { min: number; ml: number; max: number; conf: Conf; placeholder?: boolean } | null
  /** Marked as a stand-in until better data arrives. */
  placeholder?: boolean
  evidence: { id: number; citation: string; summary: string; origin: string }[]
}

export type Provenance =
  | { linked: false }
  | { linked: true; riskId: string; riskTitle: string | null; mitigationPlan: string | null; createdAt: string;
      factors: ProvenanceFactor[] }

// --- Input review and reports (task 7) ---

export type FindingKind = 'no_rationale' | 'evidence_conflict' | 'scope_drift' | 'unexplained_change' | 'unit_mistake' | 'other'

export interface Finding {
  kind: FindingKind
  state_id: string | null
  factor: string | null
  message: string
  suggestion: string | null
  evidence_ids: number[]
}

export interface ReviewPayload {
  summary: string
  findings: Finding[]
}

export interface ReportPayload {
  leadershipSummary: string
  exceptionJustification: string | null
  residualStateId: string | null
  residualName: string | null
}

export type AnalysisDraft<T> = Draft<T> & {
  runId: string | null
  /** Reviews: the inputs changed after the review. */
  stale?: boolean
  /** Reports: numbers in the shown text that aren't in the run (only possible after an edit). */
  numberCheck?: string[]
}

export interface AnalysisAgentView {
  busy: boolean
  runs: AgentRun[]
  review: AnalysisDraft<ReviewPayload> | null
  /** The latest report per simulation run, keyed by run ID. */
  reports: Record<string, AnalysisDraft<ReportPayload>>
}

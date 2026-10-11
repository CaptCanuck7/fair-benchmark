import type {
  AgentRun,
  AgentStatus,
  AppSettings,
  Analysis,
  AnalysisListItem,
  Check,
  Content,
  LibraryEntry,
  LibraryEntryInput,
  OutboundLogEntry,
  RegisterImport,
  RegisterImportResult,
  RegisterRisk,
  RegisterRiskDetail,
  ReviewAction,
  Run,
  RunSummary,
  TriageStatus,
} from '../types'

export interface FieldError {
  path: string
  message: string
  stateIndex?: number
}

/** An error from the API, with the message to show and any field-level errors. */
export class ApiError extends Error {
  constructor(public status: number, message: string, public errors: FieldError[] = []) {
    super(message)
  }
}

export interface ValidateResult {
  valid: boolean
  inputHash: string
  states: { stateId: string; index: number; checks: Check[] }[]
}

/** A document response plus the input hash the API sends in a header. */
export interface DocResponse {
  doc: Analysis
  inputHash: string
}

async function request(method: string, path: string, body?: unknown): Promise<Response> {
  let res: Response
  try {
    const form = body instanceof FormData
    res = await fetch(`/api${path}`, {
      method,
      // The browser sets the multipart Content-Type (with its boundary) for FormData.
      headers: body === undefined || form ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : form ? body : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'Can’t reach the server. Check that the containers are running.')
  }
  if (!res.ok) {
    let detail = `The server returned an error (${res.status}).`
    let errors: FieldError[] = []
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') detail = data.detail
      if (Array.isArray(data.errors)) errors = data.errors
    } catch {
      /* not JSON */
    }
    if (res.status === 413)
      detail = path === '/register/import' ? 'That workbook is larger than the 5 MB limit.' : 'That is larger than the 1 MB limit.'
    throw new ApiError(res.status, detail, errors)
  }
  return res
}

async function json<T>(method: string, path: string, body?: unknown): Promise<T> {
  return (await request(method, path, body)).json() as Promise<T>
}

async function doc(method: string, path: string, body?: unknown): Promise<DocResponse> {
  const res = await request(method, path, body)
  return { doc: (await res.json()) as Analysis, inputHash: res.headers.get('X-Input-Hash') ?? '' }
}

export const api = {
  content: () => json<Content>('GET', '/content/factors'),

  listAnalyses: () => json<AnalysisListItem[]>('GET', '/analyses'),
  createAnalysis: () => doc('POST', '/analyses'),
  getAnalysis: (id: string) => doc('GET', `/analyses/${encodeURIComponent(id)}`),
  saveAnalysis: (a: Analysis) => doc('PUT', `/analyses/${encodeURIComponent(a.id)}`, a),
  deleteAnalysis: (id: string) => request('DELETE', `/analyses/${encodeURIComponent(id)}`).then(() => undefined),
  duplicateAnalysis: (id: string) => doc('POST', `/analyses/${encodeURIComponent(id)}/duplicate`),
  importAnalysis: (raw: unknown) => doc('POST', '/import', raw),

  validate: (a: Analysis) => json<ValidateResult>('POST', '/validate', a),
  runAnalysis: (id: string) => json<Run>('POST', `/analyses/${encodeURIComponent(id)}/runs`),
  listRuns: (id: string) => json<RunSummary[]>('GET', `/analyses/${encodeURIComponent(id)}/runs`),
  getRun: (id: string, runId: string) =>
    json<Run>('GET', `/analyses/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}`),

  importRegister: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return json<RegisterImportResult>('POST', '/register/import', form)
  },
  listRegisterImports: () => json<RegisterImport[]>('GET', '/register/imports'),
  listRisks: () => json<RegisterRisk[]>('GET', '/register/risks'),
  getRisk: (riskId: string) => json<RegisterRiskDetail>('GET', `/register/risks/${encodeURIComponent(riskId)}`),

  agentStatus: () => json<AgentStatus>('GET', '/agent/status'),
  /** Re-run the quality check, triage and classification for one risk. */
  rerunIntake: (riskId: string) =>
    json<{ runId: string | null; riskId: string }>('POST', `/agent/risks/${encodeURIComponent(riskId)}/intake`),
  /** Start the scenario, vectors or evidence task for one risk. */
  startRiskTask: (riskId: string, task: 'scenario' | 'vectors' | 'evidence') =>
    json<{ runId: string; riskId: string }>('POST', `/agent/risks/${encodeURIComponent(riskId)}/${task}`),
  /** Approve, edit or reject a draft. Returns the updated risk. */
  reviewDraft: (draftId: number, action: ReviewAction, payload?: unknown) =>
    json<RegisterRiskDetail>('PUT', `/drafts/${draftId}`, payload === undefined ? { action } : { action, payload }),
  /** Record an answer to a data request. Returns the updated risk. */
  answerDataRequest: (id: number, answer: string) =>
    json<RegisterRiskDetail>('PUT', `/data-requests/${id}`, { answer }),
  agentRun: (id: string) => json<AgentRun & { riskId: string | null }>('GET', `/agent/runs/${encodeURIComponent(id)}`),
  getSettings: () => json<AppSettings>('GET', '/settings'),
  putSettings: (changes: Partial<AppSettings>) => json<AppSettings>('PUT', '/settings', changes),
  listLibrary: () => json<LibraryEntry[]>('GET', '/library'),
  addLibraryEntry: (entry: LibraryEntryInput) => json<LibraryEntry>('POST', '/library', entry),
  reviewLibraryEntry: (id: number, action: 'approve' | 'reject' | 'edit', entry?: LibraryEntryInput) =>
    json<LibraryEntry>('PUT', `/library/${id}`, entry === undefined ? { action } : { action, entry }),
  refreshLibrary: () => json<{ runId: string }>('POST', '/library/refresh'),
  /** Run the intake checks for every risk not yet checked on its current entry. */
  runRegisterIntake: () => json<{ queued: string[]; agentOff: string | null }>('POST', '/agent/register/intake'),
  triageOverride: (riskId: string, body: { status: TriageStatus; reason: string }) =>
    json<RegisterRiskDetail & { classificationNote: string | null }>(
      'POST',
      `/register/risks/${encodeURIComponent(riskId)}/triage-override`,
      body,
    ),
  outboundLog: (limit = 200) => json<OutboundLogEntry[]>('GET', `/agent/outbound-log?limit=${limit}`),

  exportJsonUrl: (id: string) => `/api/analyses/${encodeURIComponent(id)}/export.json`,
  exportCsvUrl: (id: string, runId: string) =>
    `/api/analyses/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}/export.csv`,
}

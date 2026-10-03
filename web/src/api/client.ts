import type { Analysis, AnalysisListItem, Check, Content, Run, RunSummary } from '../types'

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
    res = await fetch(`/api${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
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
    if (res.status === 413) detail = 'That is larger than the 1 MB limit.'
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

  exportJsonUrl: (id: string) => `/api/analyses/${encodeURIComponent(id)}/export.json`,
  exportCsvUrl: (id: string, runId: string) =>
    `/api/analyses/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}/export.csv`,
}

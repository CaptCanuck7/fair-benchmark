import type { Analysis, Dist, Kind, State } from '../types'

export const MAX_STATES = 4

export const THREAT_TYPES = [
  'Malicious, external',
  'Malicious, internal',
  'Error (accidental)',
  'Failure (system or vendor)',
  'Natural',
]
export const EFFECTS = ['Confidentiality', 'Integrity', 'Availability']
export const ITERATION_CHOICES = [1000, 10000, 50000, 100000]

export const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8)

// ---------------------------------------------------------------- paths

/** Read a dotted path such as "lef.tef.min". */
export function getPath(obj: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((x, k) => (x == null ? x : (x as Record<string, unknown>)[k]), obj)
}

/** Return a copy of obj with the value at a dotted path replaced, copying only along the path. */
export function setPath<T>(obj: T, path: string, value: unknown): T {
  const [head, ...rest] = path.split('.')
  const src = (obj ?? {}) as Record<string, unknown>
  const copy: Record<string, unknown> = Array.isArray(src) ? ([...src] as unknown as Record<string, unknown>) : { ...src }
  copy[head] = rest.length ? setPath(src[head], rest.join('.'), value) : value
  return copy as T
}

export function updateState(a: Analysis, index: number, path: string, value: unknown): Analysis {
  const states = a.states.slice()
  states[index] = setPath(states[index], path, value)
  return { ...a, states }
}

// ---------------------------------------------------------------- ranges

// The API runs the authoritative checks; this mirrors the prototype's
// distStatus() so a factor row can show its message as the analyst types.
export type DistState = { state: 'empty' } | { state: 'ok' } | { state: 'error'; msg: string }

export function distStatus(d: Dist | null | undefined, kind: Kind): DistState {
  if (!d) return { state: 'empty' }
  const v = [d.min, d.ml, d.max]
  if (v.every((x) => x == null)) return { state: 'empty' }
  if (v.some((x) => x == null || !isFinite(x))) return { state: 'error', msg: 'Enter all three values: minimum, most likely and maximum.' }
  const [min, ml, max] = v as number[]
  if (v.some((x) => (x as number) < 0)) return { state: 'error', msg: 'Values can’t be negative.' }
  if ((kind === 'pct' || kind === 'score') && max > 100) return { state: 'error', msg: 'Use values between 0 and 100.' }
  if (!(min <= ml && ml <= max)) return { state: 'error', msg: 'Keep minimum ≤ most likely ≤ maximum.' }
  return { state: 'ok' }
}

export const isOk = (d: Dist | null | undefined, kind: Kind) => distStatus(d, kind).state === 'ok'

/** Element id of a factor row, e.g. "f-primary-response". Matches the prototype. */
export const factorAnchor = (key: string) => 'f-' + key.replace('.', '-')

/** "states[1].lef.tef" -> { index: 1, key: "tef" } using the factor paths. */
export function parseCheckPath(path: string, factorPaths: Record<string, string>): { index: number; key: string | null } | null {
  const m = /^states\[(\d+)\](?:\.(.+))?$/.exec(path)
  if (!m) return null
  const rest = m[2] ?? ''
  const key = Object.keys(factorPaths).find((k) => factorPaths[k] === rest) ?? null
  return { index: Number(m[1]), key }
}

// ---------------------------------------------------------------- states

export function treatmentCopy(from: State, count: number): State {
  const copy = JSON.parse(JSON.stringify(from)) as State
  return { ...copy, id: newId(), name: 'Treatment option ' + count, notes: '', cost: null }
}

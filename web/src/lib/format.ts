// Number parsing and formatting, ported from the prototype so values read
// the same way: $150K, $1.5M, 8%, "about once every 5 years".

import type { Kind } from '../types'

export function trim(x: number): string {
  const s = x >= 100 ? x.toFixed(0) : x >= 10 ? x.toFixed(1) : x.toFixed(2)
  return s.replace(/\.0+$/, '').replace(/(\.\d*[1-9])0+$/, '$1')
}

export function money(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '—'
  const a = Math.abs(v)
  if (a >= 1e9) return '$' + trim(v / 1e9) + 'B'
  if (a >= 1e6) return '$' + trim(v / 1e6) + 'M'
  if (a >= 1e3) return '$' + trim(v / 1e3) + 'K'
  return '$' + Math.round(v)
}

export function pct(p: number | null | undefined): string {
  if (p == null || !isFinite(p)) return '—'
  if (p > 0 && p < 0.001) return '<0.1%'
  const x = p * 100
  return (x < 10 ? x.toFixed(1).replace(/\.0$/, '') : x.toFixed(0)) + '%'
}

export function freq(f: number): string {
  if (!isFinite(f)) return '—'
  if (f >= 10) return f.toFixed(0)
  if (f >= 1) return f.toFixed(1).replace(/\.0$/, '')
  if (f >= 0.1) return f.toFixed(2)
  return f.toPrecision(2)
}

export function every(f: number): string {
  if (!(f > 0)) return 'never in the simulation'
  if (f >= 1) return 'about ' + freq(f) + ' times a year'
  const y = 1 / f
  return 'about once every ' + (y < 10 ? y.toFixed(1).replace(/\.0$/, '') : Math.round(y)) + ' years'
}

export function fmtVal(kind: Kind, v: number | null): string {
  if (v == null) return ''
  if (kind === 'money') return money(v)
  if (kind === 'pct') return trim(v) + '%'
  if (kind === 'score') return trim(v)
  return freq(v) + '/yr'
}

export function withCommas(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return ''
  return Math.abs(v) >= 1000 ? Math.round(v).toLocaleString('en-US') : String(v)
}

/**
 * Parse what an analyst types: "150k", "1.5m", "2b", "1,200", "$80,000", "8%".
 * Returns null for an empty field and NaN for something that isn't a number.
 */
export function parseNum(input: string | null | undefined): number | null {
  if (input == null) return null
  let s = String(input).trim().toLowerCase().replace(/[$,\s%]/g, '')
  if (s === '') return null
  let m = 1
  const last = s.slice(-1)
  if (last === 'k') { m = 1e3; s = s.slice(0, -1) }
  else if (last === 'm') { m = 1e6; s = s.slice(0, -1) }
  else if (last === 'b') { m = 1e9; s = s.slice(0, -1) }
  if (!/^-?\d*\.?\d+$/.test(s)) return NaN
  return parseFloat(s) * m
}

/** How a stored value is shown in an input box. */
export function inputText(kind: Kind, v: number | null): string {
  if (v == null) return ''
  return kind === 'money' ? withCommas(v) : String(v)
}

export const NUMBER_HINT = 'Enter numbers only. You can use k, m or b for thousands, millions or billions.'

export function dateTime(iso: string): string {
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleString()
}

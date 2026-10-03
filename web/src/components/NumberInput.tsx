import { useState, type InputHTMLAttributes } from 'react'
import type { Kind } from '../types'
import { inputText, parseNum, withCommas } from '../lib/format'

interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'type'> {
  value: number | null
  kind: Kind | 'int'
  /** Called with the parsed number, null when empty, or null plus invalid=true for text that isn't a number. */
  onValue: (v: number | null, invalid: boolean) => void
}

/**
 * A text box for numbers that accepts 150k, 1.5m, 2b, 1,200, $80,000 and 8%.
 * It keeps what the analyst typed while they type, and tidies money values
 * (1500000 -> 1,500,000) when they leave the field.
 */
export function NumberInput({ value, kind, onValue, onBlur, ...rest }: Props) {
  const show = (v: number | null) => (kind === 'int' ? (v == null ? '' : String(v)) : inputText(kind, v))
  const [text, setText] = useState(() => show(value))
  const [invalid, setInvalid] = useState(false)

  function parse(s: string): number | null {
    if (kind !== 'int') return parseNum(s)
    const t = s.trim()
    return t === '' ? null : /^\d+$/.test(t) ? parseInt(t, 10) : NaN
  }

  return (
    <input
      {...rest}
      type="text"
      inputMode="decimal"
      autoComplete="off"
      value={text}
      aria-invalid={invalid || undefined}
      onChange={(e) => {
        const s = e.target.value
        setText(s)
        const n = parse(s)
        const bad = n != null && Number.isNaN(n)
        setInvalid(bad)
        onValue(bad ? null : n, bad)
      }}
      onBlur={(e) => {
        if (kind === 'money' && !invalid) {
          const n = parseNum(text)
          if (n != null && !Number.isNaN(n)) setText(withCommas(n))
        }
        onBlur?.(e)
      }}
    />
  )
}

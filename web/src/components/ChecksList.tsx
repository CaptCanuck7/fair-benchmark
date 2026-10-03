import type { Check } from '../types'

/** Checks with the bold lead-in the prototype uses. */
export function ChecksList({ checks }: { checks: Check[] }) {
  if (!checks.length) return null
  return (
    <div className="checks">
      {checks.map((c, i) => {
        const sep = c.message.slice(c.title.length, c.title.length + 2) === ': ' ? ':' : ''
        return (
          <div key={`${c.code}-${i}`} className={`check ${c.level}`}>
            <b>
              {c.title}
              {sep}
            </b>{' '}
            {c.detail}
          </div>
        )
      })}
    </div>
  )
}

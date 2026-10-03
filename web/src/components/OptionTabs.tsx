import { useEffect, useState } from 'react'
import type { State } from '../types'
import { MAX_STATES } from '../lib/model'
import { NumberInput } from './NumberInput'

interface Props {
  states: State[]
  active: number
  onSelect: (index: number) => void
  onAdd: () => void
  onDelete: () => void
  onChange: (field: 'name' | 'notes' | 'cost', value: unknown) => void
}

/** Tabs for the current state and up to three treatments, plus the active option's own fields. */
export function OptionTabs({ states, active, onSelect, onAdd, onDelete, onChange }: Props) {
  const st = states[active]
  const [confirming, setConfirming] = useState(false)
  useEffect(() => setConfirming(false), [st.id])

  return (
    <section className="panel sec statebar" id="sec-state" aria-label="Options to compare">
      <div className="tabs" role="tablist" aria-label="Options to compare">
        {states.map((s, i) => (
          <button
            key={s.id}
            type="button"
            className={'tab' + (i === active ? ' on' : '')}
            role="tab"
            aria-selected={i === active}
            onClick={() => onSelect(i)}
          >
            {s.name || 'Option ' + (i + 1)}
          </button>
        ))}
        {states.length < MAX_STATES && (
          <button type="button" className="tab add" onClick={onAdd}>
            Add treatment option
          </button>
        )}
      </div>
      <p className="lede">
        Each option is a complete set of estimates for the same scenario. Start with the current state. To compare a
        fix, add a treatment option: it copies the option you’re viewing, and you change only the factors the fix
        affects.
      </p>
      <div className="grid2">
        <label className="fld">
          <span>Option name</span>
          <input value={st.name} onChange={(e) => onChange('name', e.target.value)} />
        </label>
        {active > 0 && (
          <label className="fld">
            <span>
              Annual cost of this option{' '}
              <span className="hint">one-time cost ÷ years of use, plus yearly running cost</span>
            </span>
            <NumberInput
              key={st.id}
              kind="money"
              value={st.cost}
              placeholder="e.g. 80k"
              onValue={(v) => onChange('cost', v)}
            />
          </label>
        )}
      </div>
      <label className="fld" style={{ marginTop: 12 }}>
        <span>{active === 0 ? 'Notes on the current state' : 'What this option changes, and which factors it affects'}</span>
        <textarea rows={2} value={st.notes} onChange={(e) => onChange('notes', e.target.value)} />
      </label>
      {active > 0 && (
        <div style={{ marginTop: 10 }}>
          {confirming ? (
            <>
              <button type="button" className="btn danger" onClick={onDelete}>
                Confirm: delete {st.name}
              </button>{' '}
              <button type="button" className="btn quiet" onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </>
          ) : (
            <button type="button" className="btn quiet danger" onClick={() => setConfirming(true)}>
              Delete this option
            </button>
          )}
        </div>
      )}
    </section>
  )
}

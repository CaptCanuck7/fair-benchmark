import { useCallback, useEffect, useRef, useState } from 'react'
import type { Analysis } from '../types'
import { api, ApiError } from '../api/client'

export const SAVE_DELAY_MS = 1000

export type SaveStatus =
  | { kind: 'idle' }
  | { kind: 'pending' }
  | { kind: 'saving' }
  | { kind: 'saved' }
  | { kind: 'error'; message: string }

export function saveStatusText(s: SaveStatus): string {
  switch (s.kind) {
    case 'pending': return 'Unsaved changes'
    case 'saving': return 'Saving…'
    case 'saved': return 'Saved'
    case 'error': return `Couldn’t save: ${s.message}`
    default: return ''
  }
}

/**
 * Debounced autosave with PUT. Call `schedule(doc)` after every edit; the
 * latest document is saved 1 second after the last change. Only one save is
 * in flight at a time, and a change made during a save triggers another.
 * `flush()` saves immediately (used before leaving the page).
 */
export function useAutosave(onSaved: (inputHash: string, doc: Analysis) => void) {
  const [status, setStatus] = useState<SaveStatus>({ kind: 'idle' })
  const latest = useRef<Analysis | null>(null)
  const dirty = useRef(false)
  const timer = useRef<number | undefined>(undefined)
  const inFlight = useRef<Promise<void> | null>(null)
  const onSavedRef = useRef(onSaved)
  onSavedRef.current = onSaved

  /** Save now if there are unsaved changes. Resolves to false if the save failed. */
  const save = useCallback(async (): Promise<boolean> => {
    window.clearTimeout(timer.current)
    timer.current = undefined
    if (inFlight.current) {
      await inFlight.current
      if (!dirty.current) return true
    }
    const doc = latest.current
    if (!doc || !dirty.current) return true
    dirty.current = false
    setStatus({ kind: 'saving' })
    let failed = false
    const p = (async () => {
      try {
        const res = await api.saveAnalysis(doc)
        onSavedRef.current(res.inputHash, doc)
        setStatus(dirty.current ? { kind: 'pending' } : { kind: 'saved' })
      } catch (e) {
        // Keep the changes marked unsaved; the next edit (or leaving the page) tries again.
        failed = true
        dirty.current = true
        const message = e instanceof ApiError ? describe(e) : 'unexpected error'
        setStatus({ kind: 'error', message })
      }
    })()
    inFlight.current = p
    await p
    inFlight.current = null
    // An edit made while saving has its own timer; this catches one whose timer already fired.
    if (!failed && dirty.current && timer.current === undefined) {
      timer.current = window.setTimeout(() => {
        timer.current = undefined
        void save()
      }, SAVE_DELAY_MS)
    }
    return !failed
  }, [])

  const schedule = useCallback((doc: Analysis) => {
    latest.current = doc
    dirty.current = true
    setStatus((s) => (s.kind === 'error' ? s : { kind: 'pending' }))
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      timer.current = undefined
      void save()
    }, SAVE_DELAY_MS)
  }, [save])

  /** Forget pending state, for when a different analysis is loaded. */
  const reset = useCallback((doc: Analysis | null) => {
    window.clearTimeout(timer.current)
    timer.current = undefined
    latest.current = doc
    dirty.current = false
    setStatus({ kind: 'idle' })
  }, [])

  // Save on the way out: when navigating within the app (unmount) and when
  // the tab is closed or reloaded (keepalive lets the request finish).
  useEffect(() => {
    const onHide = () => {
      if (!dirty.current || !latest.current) return
      const doc = latest.current
      void fetch(`/api/analyses/${encodeURIComponent(doc.id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(doc),
        keepalive: true,
      })
      dirty.current = false
    }
    window.addEventListener('pagehide', onHide)
    return () => {
      window.removeEventListener('pagehide', onHide)
      window.clearTimeout(timer.current)
      onHide()
    }
  }, [])

  return { status, schedule, flush: save, reset }
}

function describe(e: ApiError): string {
  const first = e.errors[0]
  return first ? `${first.path}: ${first.message}` : e.message
}

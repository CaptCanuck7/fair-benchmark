import { createContext, useContext } from 'react'
import type { Content } from './types'

// Factor labels, units and help text, loaded once from GET /api/content/factors.
export const ContentContext = createContext<Content | null>(null)

export function useContent(): Content {
  const c = useContext(ContentContext)
  if (!c) throw new Error('Factor content has not loaded.')
  return c
}

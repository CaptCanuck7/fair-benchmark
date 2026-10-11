import { createContext, useContext } from 'react'
import type { ProvenanceFactor } from './types'

// Where each factor of the active option came from, when the analysis was
// created from a register risk. Keyed by factor key ("tef", "primary.response").
export const ProvenanceContext = createContext<Record<string, ProvenanceFactor>>({})

export const useProvenance = (factorKey: string): ProvenanceFactor | undefined => useContext(ProvenanceContext)[factorKey]

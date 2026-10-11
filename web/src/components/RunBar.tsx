import type { ReactNode } from 'react'

interface RunBarProps {
  message: string
  /** Shown beside the run button, such as "Review inputs". */
  extra?: ReactNode
  running: boolean
  onRun: () => void
}

/** The sticky bar at the bottom of the workspace. */
export function RunBar({ message, running, onRun, extra }: RunBarProps) {
  return (
    <div className="runbar">
      <div className="in">
        <div className="msg" role="status" aria-live="polite" title={message}>
          {message}
        </div>
        <div className="runbtns">
          {extra}
          <button type="button" className="btn primary" disabled={running} onClick={onRun}>
            {running ? 'Running…' : 'Run simulation'}
          </button>
        </div>
      </div>
    </div>
  )
}

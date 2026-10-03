interface RunBarProps {
  message: string
  running: boolean
  onRun: () => void
}

/** The sticky bar at the bottom of the workspace. */
export function RunBar({ message, running, onRun }: RunBarProps) {
  return (
    <div className="runbar">
      <div className="in">
        <div className="msg" role="status" aria-live="polite" title={message}>
          {message}
        </div>
        <button type="button" className="btn primary" disabled={running} onClick={onRun}>
          {running ? 'Running…' : 'Run simulation'}
        </button>
      </div>
    </div>
  )
}

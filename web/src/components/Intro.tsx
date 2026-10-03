/** "How this tool works", including the Open FAIR conformance statement. */
export function Intro({ open = false }: { open?: boolean }) {
  return (
    <details className="intro" open={open}>
      <summary>How this tool works</summary>
      <p>
        This follows the Open FAIR risk taxonomy (O-RT) and analysis approach (O-RA). Risk is the probable frequency and
        probable magnitude of future loss. You estimate each factor as a range (minimum, most likely, maximum) and a
        confidence level. The tool turns each range into a PERT distribution and runs a Monte Carlo simulation: it
        simulates thousands of years, drawing a random value for every factor in each year, and reports the spread of
        outcomes.
      </p>
      <p>
        Work top to bottom: scope the scenario, estimate how often the loss event happens, estimate what one event
        costs, then run the simulation and read the results and checks. Add treatment options to compare the current
        state against proposed changes. The taxonomy tree shows which factors you are estimating and which are
        calculated.
      </p>
      <p>
        It is a learning and prototyping tool. The math follows the Open FAIR structure, but it is not a certified Open
        FAIR product.
      </p>
    </details>
  )
}

/** Always-visible conformance note. */
export function ConformanceNote() {
  return (
    <p className="conformance">
      Follows the Open FAIR taxonomy (O-RT) and analysis approach (O-RA). Not a certified Open FAIR product.
    </p>
  )
}

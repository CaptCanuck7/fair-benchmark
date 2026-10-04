/** The persistent notice on every register page (AGENT_BUILD.md section 2, rule 7). */
export function TestDataNotice() {
  return (
    <div className="banner notice" role="note">
      <b>Test data only.</b> Do not load real register data until your organization has approved this use. When the
      agent runs, risk text is sent to the Claude API.
    </div>
  )
}

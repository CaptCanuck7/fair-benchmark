# FAIR Risk Workbench: agent fixes after review

Four fixes from the review of the agent extension (milestones 1 to 7). Read this whole file, then inspect the code named in each fix before changing it. Where the code differs from what this file describes, follow the code and say so in the README.

## Rules for this work

- Do not change any file under `api/app/engine/`.
- Change only what each fix needs. Do not refactor nearby code.
- Every fix adds tests. All existing tests must still pass: `pytest` in `api/` and in `agent/`, and `tsc -b` in `web/`.
- Do not hand-edit recorded model output in `api/tests/fixtures/*_recorded.json`. If a fix changes what a replay test sends or expects, re-record through the live path and say so.
- Commit after each fix, in the order below. Add each decision to the README under "Decisions".

## Fix 1. Estimates must never pass without evidence (high)

**Problem.** `EstimatesOutput._rules` in `agent/app/schemas.py` wraps its evidence checks in `if evidence:`. When the request has no evidence items the dict is empty, the checks are skipped, and ranges that cite invented evidence IDs are accepted at any confidence. `basis()` in `agent/app/tasks/estimates.py` then labels them "internal". An evidence run that returns only data requests produces this state. It breaks rule 4 of `AGENT_BUILD.md` (no range for a factor with no evidence).

The same pattern applies to `request_ids`: with no data requests, an invented `data_request_id` passes.

**Change.**

1. In `EstimatesOutput._rules`, run the evidence checks whenever the validation context has an `evidence` key, including when it is empty. Do the same for `request_ids`. Keep the checks skipped only when the key is absent, so the model can still be validated without a request context in tests that rely on that.
2. In `basis()`, do not default to "internal" for an empty set. An estimate with no cited evidence that is known to the request must not reach this point; raise if it does.
3. In the api, block the estimates task when the risk has no current evidence items. `task_blocker` in `api/app/register/state.py` takes `has_evidence`, which today means "an evidence run succeeded". Make the estimates gate require at least one item from `agent_pipeline.current_evidence()` as well. Message for the analyst: "No evidence was found for this risk. Answer a data request or gather evidence again before drafting estimates." Keep the existing message for the case where no evidence run exists.

**Tests.**

- Agent: an `EstimatesOutput` with one estimate, validated with `evidence: {}` in the context, fails. The same with `request_ids: set()` and an invented `data_request_id` fails.
- Api: with a succeeded evidence run that stored zero items, `POST /api/agent/risks/{id}/estimates` returns 409 with the new message. After a data request is answered (which creates an evidence item), it is accepted.

## Fix 2. Close the outbound guard's gaps on URLs (medium)

**Problem.** `Guard.check_url` in `agent/app/guard.py` is weaker than `check_query`. Confirmed by running it:

- `https://www.ibm.com/search?q=ASSET%2D4120` is allowed. Identifiers are matched against the raw path and query, so percent-encoding hides them.
- A URL of any length is allowed, so long internal text can travel in a query string to an allowlisted site. Queries are capped at 120 characters; URLs are not.
- `https://raw.githubusercontent.com/mitre/cti/../../someone/repo/main/page.html` is allowed, because fixed feeds are matched with `startswith` on the raw string. httpx then normalises the path and requests `/someone/repo/main/page.html`.
- `check_query("exploit ASSET 4120 sftp")` is allowed while `ASSET-4120` is blocked. A space, underscore or hyphen in place of an identifier's separator defeats the match.

**Change.**

1. Normalise before checking. Parse the URL once, resolve dot segments, and reject any URL whose path contains an encoded dot, slash or backslash (`%2e`, `%2f`, `%5c`, any case) or a literal backslash. Run every check against the normalised form, and make `OutboundClient.get` send exactly the string that was checked. Apply the same to each redirect hop.
2. Match fixed feeds against the normalised URL.
3. Decode before the identifier check. Percent-decode the path and query (treat `+` as a space) until the text stops changing, with a small cap on passes, and run the identifier match on both the raw and the decoded text.
4. Cap URL size for hosts that are not fixed feeds: the decoded query string at `MAX_QUERY_LENGTH` (120) and the whole URL at 500 characters. New block reasons: `url_query_too_long`, `url_too_long`. Fixed feed URLs are built by code and stay exempt (an EPSS request for 20 CVEs is longer than 120).
5. In `Guard._compile`, treat a run of spaces, hyphens or underscores inside an identifier as interchangeable, so `ASSET 4120`, `ASSET_4120` and `ASSET-4120` all match. Keep the existing word-boundary behaviour (`Asset-412` must still not match inside `Asset-4120`, and `Nova` not inside `renovate`).
6. Add labels for the new block reasons where the Settings page maps reason codes to text (`web/src/pages/Settings.tsx`).

**Tests** (`agent/tests/test_guard.py`). Each of the four cases above is blocked and logged. Existing allowed cases still pass, including the real NVD, KEV, EPSS and ATT&CK feed URLs with their query parameters, and a redirect to an allowlisted host.

## Fix 3. Mark estimates out of date (medium)

**Problem.** Vectors record the scenario they were built from (`basedOn`) and are flagged when it changes (`vectors_stale` in `api/app/routers/register.py`). Estimates record nothing. An analyst can edit the scenario, gather evidence again, or answer a data request, and the earlier decided ranges still push into a new analysis with no warning.

**Change.**

1. When an estimate draft is stored (`_draft_estimates` in `api/app/agent_pipeline.py`), add `basedOn` to its payload: the scenario draft ID, the scenario hash (`scenario_hash`, as vectors use), the evidence run ID, and the sorted IDs of the evidence items that were sent.
2. Add a function that compares `basedOn` with the current state and returns two flags: `scenario` (the usable scenario is a different draft, has different content, or is no longer approved) and `evidence` (the set of current evidence item IDs differs, which covers both a new evidence run and a newly answered data request). A draft without `basedOn` (created before this change) reports neither flag.
3. Return the flags from `estimates_out` as `stale: { scenario, evidence }`.
4. Estimates tab (`web/src/components/EstimatesTab.tsx`): when either flag is set, show a warning above the factors that says what changed and offers "Draft estimates again". Decided ranges stay visible and usable.
5. Create analysis: when either flag is set, `POST /api/register/risks/{id}/create-analysis` returns 409 with a message naming what changed, unless the request body has `acknowledgeStale: true`. The page shows the message with a "Create anyway" button that resends with the flag. When acknowledged, add one line to the new analysis's scope notes: "Estimates were drafted before the scenario changed." or "…before the evidence changed." as applies.

**Tests.** Editing the approved scenario after estimates sets `stale.scenario`. A new evidence run sets `stale.evidence`. Answering a data request sets `stale.evidence`. Create analysis returns 409 when stale and 201 with `acknowledgeStale`. A draft without `basedOn` is not stale.

## Fix 4. Stop the false "no risk owner" gap (low)

**Problem.** People's names are withheld from the model, correctly. But `render_risk` in `agent/app/tasks/common.py` sends nothing about the owner at all, so the quality check reports that the entry has no named risk owner and asks who it is. TR-6 shows this in `intake_recorded.json`, although the register names an owner.

**Change.**

1. Add `has_risk_owner: bool` to `RiskEntry` (`agent/app/schemas.py`) and set it in `risk_entry()` (`api/app/agent_pipeline.py`) from whether the register's risk owner field is non-blank. Do not send the name.
2. In `render_risk`, add a line: "Risk owner: recorded (name withheld)" or "Risk owner: not recorded".
3. Add a new prompt version `agent/app/prompts/quality.v2.md`, copied from v1, with one added instruction: people's names are withheld from the entry on purpose; do not report a missing owner or ask who the owner is when the entry says one is recorded. Point `PROMPT_VERSION` in `agent/app/tasks/quality.py` at it. Keep `quality.v1.md` in place.
4. The deterministic rule in `api/app/register/quality.py` already reports a missing owner and stays as it is.

**Note.** The quality input hash includes the risk payload, so every risk's hash changes and the next import or "run checks" re-runs intake for all risks. That is expected. Say so in the README.

**Tests.** `render_risk` output contains the right line for each case and never the owner's name. The api's quality payload carries `has_risk_owner` and no name. Check how the replay tests key `intake_recorded.json`; if they depend on the payload or the prompt version, re-record rather than edit.

## When all four are done

Run all three test suites and report the counts. List any place where the code differed from this file, and anything you chose not to change.

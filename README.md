# FAIR Risk Workbench

A local web app for Open FAIR cyber risk quantification. Scope a loss event
scenario, estimate each factor as a range, run a Monte Carlo simulation, read
the results and automatic checks, and compare treatment options.

It follows the Open FAIR risk taxonomy (O-RT) and analysis approach (O-RA).
It is a learning and prototyping tool, **not a certified Open FAIR product.**

## Quick start

You need Docker with Docker Compose.

```sh
docker compose up --build
```

Then open <http://localhost:8080>. The first build takes a few minutes.

To stop it, press Ctrl+C, or run `docker compose down` if you started it with
`-d`. Your analyses are kept in the `fair_data` volume between runs.

## Running the tests

With the app running:

```sh
docker compose exec api pytest
```

The tests use an in-memory database, so they never touch your saved analyses.
They cover the PERT sampling, the simulation (including the Product X
reference case at 100,000 years), every check rule, and the API endpoints,
including importing prototype exports.

The agent has its own suite, with the Claude API mocked and no network use:

```sh
docker compose exec agent pytest
```

Tests marked `live` call the Claude API and the internet, and are skipped
unless you ask for them with `docker compose exec agent pytest -m live`.

The api suite never calls the agent either. The agent's answers are faked, or
replayed from `api/tests/fixtures/intake_recorded.json`, which holds real model
output from a live run.

**Live evaluation** runs the quality check, triage and condition
classification on the test register through the real agent and the Claude API,
and checks the results against `AGENT_BUILD.md` section 14. It needs the agent
configured. It spends tokens (about 60,000 input and 7,000 output on the
current model), and uses a throwaway in-memory database, not your saved data.

```sh
docker compose exec api pytest -m live -s
```

To refresh the recorded fixture from a live run, add
`-e RECORD_DIR=/tmp` after `exec`, then copy it out with
`docker compose exec api cat /tmp/intake_recorded.json > api/tests/fixtures/intake_recorded.json`.
In Git Bash, run `export MSYS_NO_PATHCONV=1` first so `/tmp` isn't rewritten.

## Using it

1. **Analyses list.** Start a new analysis or import a JSON file exported from
   this app or from the prototype (`reference/fair-workbench.html`).
2. **Scope the scenario:** asset, threat community, threat type and effect.
3. **Options.** The current state comes first. "Add treatment option" copies
   the option you're viewing; change only the factors the fix affects, and
   enter its annual cost.
4. **Estimate the factors** as minimum, most likely and maximum, with a
   confidence level. Inputs accept `150k`, `1.5m`, `1,200` and `8%`. Record a
   rationale and source for each.
5. **Run the simulation** from the bar at the bottom. If an input is missing or
   invalid, the app takes you to it.
6. **Read the results:** summary, key numbers, checks, loss exceedance curve,
   single-event histogram and loss breakdown. With two or more options,
   **Compare options** shows reduction, net benefit and return.
7. **Run history** keeps every run with a copy of its inputs. Open one to see
   it read-only, or download its CSV.

Everything saves automatically about a second after you stop typing.
**Export JSON** in the workspace header downloads the analysis plus the latest
results in the prototype's format.

### Risk register

**Risk register** on the home page opens the tactical risk register. Import a
register workbook (.xlsx, up to 5 MB); `agent-data/tactical_risk_register_test.xlsx`
is a test register. Rows that share a risk ID become one risk with a list of
monitoring updates, and scores are recalculated as impact × likelihood. Open a
risk to see its entry, with the Risk Analysis text split into its sections.

**Checks on import.** When the agent is on, importing starts three checks for
each risk, in the background. The list refreshes itself while they run (a
minute or two for the test register).

1. **Quality check.** Automatic rules look for missing fields and short or
   unstructured analysis text. The agent then judges whether the text names
   what is at risk, the weakness, and how loss could happen. A risk that
   **needs info** stops here, with its gaps and questions for you.
2. **Triage.** A fixed rule decides: a ready risk **qualifies** when its
   baseline score is at least `TRIAGE_MIN_SCORE` (6 by default) or its impact
   is 5. Otherwise it is **screened out**. The agent only explains the result
   and may add an advisory note, which never changes it. You can override
   triage either way on the risk's Quality tab, with a reason. Your name
   (`ANALYST_NAME`) and the date are recorded.
3. **Condition type.** For risks that qualify, the agent names the kind of
   weakness: unsupported software, missing control, misconfiguration, process
   gap, third party or other. Evidence gathering will use it to decide where to
   look first.

Everything the agent writes is labeled **Agent draft**. A risk's Quality tab
shows each result, the agent runs behind it (model, prompt version and tokens),
and **Run checks again**. Importing the same register again doesn't re-check
risks whose entries haven't changed.

**Test data only.** Do not load real register data until your organization has
approved this use. When the agent runs, risk text is sent to the Claude API.
People's names from the register (analyst, owner, managers) are not sent.

**Settings** (from the register page) shows whether the agent is on, the
triage threshold, the reviewer name, and the log of every outbound request the
agent attempted.

### The agent

The agent prepares FAIR analyses from the register, and analysts approve
everything it drafts. It needs a Claude API key: copy `.env.example` to `.env`,
set `ANTHROPIC_API_KEY`, and run `docker compose up -d`. Without a key the
rest of the app works and the agent is shown as off.

The api container also loads `agent-data/mock_internal_evidence.xlsx` on every
start. It stands in for records the SOC, Asset Management and other teams would
supply, and the agent will read it through internal-only endpoints.

## Configuration

No configuration is needed. To override defaults, copy `.env.example` to
`.env`. It documents `DATABASE_URL`, `CORS_ORIGIN`, `MAX_BODY_BYTES` and
`MAX_UPLOAD_BYTES`.

## Your data: back up, restore, reset

Analyses and runs live in a SQLite database in the Docker volume
`fair-workbench_fair_data`. (Compose prefixes the volume with the project
name, which is the folder name. If you cloned into a differently named folder,
run `docker volume ls` to find it.)

Stop the API before a backup or restore so the database isn't being written
to. The web page will show errors until you start it again.

**Back up** to `fair-data-backup.tgz` in the current folder:

```sh
docker compose stop api
docker run --rm -v fair-workbench_fair_data:/data -v "$(pwd)":/backup alpine:3.21 \
  tar czf /backup/fair-data-backup.tgz -C /data .
docker compose start api
```

**Restore** from that file. This replaces everything currently saved:

```sh
docker compose stop api
docker run --rm -v fair-workbench_fair_data:/data -v "$(pwd)":/backup alpine:3.21 \
  sh -c "rm -rf /data/* && tar xzf /backup/fair-data-backup.tgz -C /data"
docker compose start api
```

In **PowerShell**, write `${PWD}` instead of `"$(pwd)"` and put each
`docker run` command on one line. In **Git Bash on Windows**, run
`export MSYS_NO_PATHCONV=1` first so the paths aren't rewritten.

**Reset** to an empty app. This deletes every saved analysis and run:

```sh
docker compose down -v
docker compose up --build
```

## Architecture

| Service | Stack | Role |
|---|---|---|
| `api` | Python 3.12, FastAPI, Pydantic v2, NumPy, SQLAlchemy 2, SQLite | Simulation engine, validation, checks, persistence, import and export |
| `web` | React 18, TypeScript, Vite, served by nginx | The UI. nginx also proxies `/api/*` to `api`. |
| `agent` | Python 3.12, FastAPI, Anthropic Python SDK, httpx | Stateless workers for the agent tasks. Holds no data: `api` sends it inputs and stores what comes back. |

**Networks.** `backend` is an internal Compose network with no route out of
the host, and all three services are on it. `api` is on `backend` only, so it
can't reach the internet. `agent` is also on `egress`, for the Claude API and
the allowlisted sources. `web` is also on `frontend`, which carries the
published port. Only `web` is published.

- **The simulation runs on the server** in NumPy, vectorized across simulated
  years. The browser never computes results.
- **The checks run on the server** and come back with the results, so the rules
  live in one tested place (`api/app/engine/checks.py`).
- **Factor labels, units, help text and data sources** live in
  `api/app/content/factors.py` and reach the UI through `GET /api/content/factors`.
- **Every stored run** keeps a snapshot of the inputs it used and a SHA-256
  hash of those inputs. The hash drives the "inputs changed since the last run"
  banner.

```
api/app/
  main.py            app, routers, CORS, body size limit
  schemas.py         the analysis document (Pydantic), import normalization, input hash
  models.py, db.py   tables and sessions
  engine/            distributions, simulate, stats, checks, fmt (message formatting)
  routers/           analyses, simulate (runs, validate), io (import/export)
  content/factors.py factor text
  register/          register parser and section splitter
  evidence.py        mock internal evidence loader and queries
  identifiers.py     identifier denylist for the agent's outbound guard
api/tests/           pytest suite and fixtures
agent/app/
  main.py            agent service: health and status (task endpoints come later)
  config.py          settings from the environment
  llm.py             Claude wrapper: structured output, one retry, token counts
  guard.py           outbound guard: allowlist, identifier denylist, logging
  api_client.py      calls to api's internal endpoints
agent/tests/         pytest suite (Claude API mocked)
web/src/
  App.tsx            routing: "/" list, "/analyses/:id" workspace
  api/client.ts      fetch wrapper
  types.ts           mirrors api/app/schemas.py and the run results
  components/        one file per section or component
  hooks/             autosave, run history
  lib/               number parsing and formatting, document helpers
  styles/app.css     the prototype's design tokens and styles
```

### API

All under `/api`, JSON throughout.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/content/factors` | Factor labels, units, help and data sources |
| GET, POST | `/analyses` | List analyses, or create one (an empty body gives a blank analysis) |
| GET, PUT, DELETE | `/analyses/{id}` | Fetch, replace or delete an analysis |
| POST | `/analyses/{id}/duplicate` | Copy as a new analysis |
| POST | `/validate` | Pre-run checks for a document in the body |
| POST, GET | `/analyses/{id}/runs` | Run the saved document, or list past runs |
| GET | `/analyses/{id}/runs/{runId}` | A stored run, with its input snapshot |
| POST | `/simulate` | Run a document in the body without saving it |
| GET | `/analyses/{id}/export.json` | Document plus latest results, in the prototype's format |
| GET | `/analyses/{id}/runs/{runId}/export.csv` | Results table, with the prototype's columns |
| POST | `/import` | Create an analysis from an exported JSON file |
| POST | `/register/import` | Upload a register workbook (multipart field `file`, `.xlsx`, 5 MB) |
| GET | `/register/imports` | Past register imports, newest first |
| GET | `/register/risks` | Register risks with their scores and statuses |
| GET | `/register/risks/{riskId}` | One risk: fields, sections, monitoring updates |
| GET | `/agent/status` | Whether the agent is configured, and why not |
| GET | `/agent/outbound-log` | The agent's outbound requests, newest first, identifiers redacted |
| GET | `/openapi.json` | The OpenAPI schema |

The api also serves read-only `/internal/evidence/{sheet}?asset_id=...` (sheets:
`assets`, `telemetry`, `incidents`, `findings`, `control-tests`, `vendors`,
`about`), `/internal/evidence/incidents?type=...`,
`/internal/guard/identifiers` and `POST /internal/outbound-log` for the agent. nginx
doesn't proxy `/internal/`, so the browser can't reach them.

Validation errors return 422 as
`{"detail": "...", "errors": [{"path": "states[1].lef.tef", "message": "..."}]}`.

## Security

This is a risk tool, so it follows the baseline in `CLAUDE.md`:

- **Only nginx is published, and only on `127.0.0.1:8080`.** The API and the
  agent aren't reachable from the host.
- **The API has no internet access.** It sits on an internal-only network.
- **Only the agent gets the Claude API key.** Compose passes it to that one
  container. The key is never logged or returned by an endpoint.
- **The agent's outbound requests go through one guard** (`agent/app/guard.py`):
  https only, allowlisted domains and fixed feed addresses only, searches of at
  most 120 characters, and nothing containing a register or evidence identifier.
  Redirects are re-checked, responses are size-capped, and every attempt is
  logged (redacted) before it is sent. If the log can't be written, the request
  isn't sent.
- **All containers run as non-root users** (`app` and `nginx`), with:
  - read-only root filesystems
  - every Linux capability dropped
  - `no-new-privileges`
  - writable space limited to the data volume (API) and small in-memory
    mounts for nginx's cache and pid file
- **Base images are pinned** to exact versions: `python:3.12.15-slim-bookworm`,
  `node:20.20.2-alpine3.23` and `nginx:1.27.5-alpine3.21`. npm packages are
  locked by `package-lock.json`.
- **nginx sets these headers:**
  - `X-Content-Type-Options`
  - `Referrer-Policy: no-referrer`
  - a same-origin CSP with `frame-ancestors 'none'`
  - `X-Frame-Options`
  - `Permissions-Policy`

  It also hides its version.
- **CORS** allows only the web origin. In compose, everything is same-origin
  through nginx anyway.
- **Limits are enforced on the server:**
  - 1 MB request bodies, in both nginx and the API
  - at most 200,000 simulated years
  - at most 20 million simulated loss events per option
- **The only secret** is the optional `ANTHROPIC_API_KEY`, kept in the
  gitignored `.env`.

## Decisions

Choices made where the spec was open. Each follows the rule "check the
prototype first; otherwise choose the simpler option."

**Engine and checks**
- **Simulated years** must be between 100 and 200,000, or the document is
  rejected with a 422 on `settings.iterations`. The UI offers only 1,000,
  10,000, 50,000 and 100,000. The 100 minimum matches the prototype.
- **Check results** carry `title`, `detail` and `message`, where `message` is
  title and detail joined. The extra fields let the UI show the prototype's
  bold lead-in. Pre-run checks from `/validate` and failed runs also carry
  `stateIndex` and `stateId`.
- **The seed** is reduced to 32 bits (`seed & 0xFFFFFFFF`) before seeding
  NumPy, matching the prototype's `seed >>> 0`.
- **Results also include `secondaryShareOfEvents`**, because the prototype
  calculates it too.
- **Run timestamps** come from the server clock in UTC.

**Persistence and import**
- **Timestamps are ISO-8601 strings in the database**, matching the
  document's own `createdAt` and `updatedAt`.
- **The input hash** covers scope, states and settings, leaving out option
  names, option notes and scope notes. Rationale text (`src`) and treatment
  costs are included: rationale affects the "undocumented estimates" check,
  and cost affects the comparison. Editing either marks results as out of date.
- **The current input hash** comes back in an `X-Input-Hash` response header on
  document responses. That keeps the document itself in the prototype's format.
- **Imports get a new id and fresh created and updated dates**, and any
  exported `summary` is dropped. Like the prototype, import also accepts a file
  shaped `{"analysis": {...}}`.
- **The analyses list** includes the latest run's mean annual loss per option,
  and whether that run is out of date.
- **Duplicating an analysis** copies the document but not its run history.

**Frontend**
- **Changing the threshold, simulated years or seed asks for a rerun.** The
  prototype recomputed the threshold figures instantly. Here every number comes
  from the server, which keeps the full results, so the browser can't
  recompute them.
- **Inline validation on factor rows** runs in the browser, with the same rules
  and wording as the server. The issue count in the run bar comes from the
  server's `/validate`, called after each save.
- **Public Sans is bundled** (`@fontsource/public-sans`) rather than loaded from
  Google Fonts, because the CSP allows only the app's own origin.
- **Pending changes are saved when you close or reload the page**, using a
  `keepalive` request, so the last second of typing isn't lost.
- **Charts are hand-built SVG**, as in the prototype, using the server's curve
  and histogram data. The legend is HTML so it wraps on narrow screens, and
  chart labels get larger on phones.
- **"Taxonomy" links to factors the current method doesn't show** jump to the
  loss event frequency section instead.

**Packaging**
- **The API image includes pytest**, so `docker compose exec api pytest` works
  as the spec asks. It adds a few MB.
- **pydantic is held below 2.12** to match the pinned FastAPI 0.115. Newer
  pydantic versions trigger warnings inside FastAPI.
- **FastAPI's Swagger UI is turned off.** It loads scripts from a CDN, which the
  CSP blocks. The schema is still served at `/api/openapi.json`.
- **nginx resolves `api` through Docker's DNS on each request** (re-checked
  every 10 seconds), so recreating the API container doesn't break the proxy.

**Risk register and internal evidence** (`AGENT_BUILD.md`, milestone 1)
- **The data folder is `agent-data/`**, as `AGENT_BUILD.md` lays it out. It was
  delivered as `agent data/` and renamed. Compose mounts it read-only into the
  api container at `/agent-data`.
- **Importing a register again updates risks with the same risk ID in place**,
  rather than adding duplicates. That keeps drafts, evidence and analyses linked
  to a risk across re-imports. Risks missing from a later import are kept. Each
  import is still recorded in `register_imports`.
- **Risks are addressed by their register ID** in URLs (`/register/TR-7`,
  `/api/register/risks/TR-7`), which is unique after the rule above.
- **Unstructured analysis text** is stored as `{"raw": text}` in `sections`.
  Text before the first label in structured text is kept as `preamble`.
- **A score input that isn't a whole number from 1 to 5 counts as missing**, so
  its score is null.
- **A risk's residual score** comes from the most recently completed monitoring
  update that has both residual inputs.
- **The register's first sheet is read.** Up to 10,000 rows and 60 columns.
  openpyxl uses defusedxml for the XML.
- **Evidence record IDs** come from each sheet's ID column: Incident ID,
  Finding ID, Record ID, Asset ID (Asset Inventory and Vendor Assessments) and
  Item (About). Security Telemetry has no ID column, so its rows are cited by
  spreadsheet row, for example "Security Telemetry Row 10".
- **Telemetry rows marked "Organization-wide"** are returned for every asset
  query, flagged `organizationWide`, since they apply to every asset.
- **The incident `type` filter** matches any incident whose Type contains the
  text, ignoring case, so `type=phishing` finds "Credential phishing".
- **Evidence tables are reloaded from the workbook on every api start.**
  Formula cells are read from their cached values and never recalculated.
- **The upload limit is 5 MB on `/api/register/import` only**, in both nginx
  and the API. Every other path keeps the 1 MB limit.

**Agent service and guard** (`AGENT_BUILD.md`, milestone 2)
- **No `temperature` setting.** The spec asks for a low temperature, but current
  Sonnet models reject non-default sampling settings with an error. Each run
  uses structured outputs (a JSON schema the reply must follow), Pydantic
  validation and a fixed `effort` level instead. The model, prompt version
  and input hash are still stored with each run.
- **Refusal fallback is on.** Requests opt into the API's server-side fallback
  (`fallbacks: "default"`), so a request that a safety classifier declines is
  retried on the fallback model. Security wording can trigger the cyber
  classifier. The model that actually answered is recorded.
- **Validation happens twice.** The API's structured outputs guarantee the JSON
  shape. Pydantic then checks what the API's schema can't express (number
  ranges, min ≤ most likely ≤ max). A failure gets one corrective retry quoting
  the error, and a second failure fails the run.
- **Domain restriction is enforced in code, not by the network.** Docker can't
  filter egress by domain without an extra proxy container, so the agent's
  `egress` network can reach any host and the guard decides. The api, which
  holds the data, has no egress at all. A filtering egress proxy would be a
  sensible later hardening step.
- **The guard's identifier list comes from api** (`/internal/guard/identifiers`)
  and is fetched at the start of each task, so a new register import is picked
  up. People's names are matched as written, without a leading title such as
  "VP", and by surname. First names alone aren't blocked because they're too
  common.
- **Business unit names are blocked as the spec says**, including "Product".
  A search such as "product end-of-support exploitation" is therefore blocked.
  Prompts steer searches toward generic terms.
- **Matching respects word boundaries**, so "Asset-412" doesn't block
  "Asset-4120" and "Nova" doesn't block "renovate".
- **The agent redacts outbound log entries** before they are stored: each
  identifier becomes a placeholder such as `[asset_id]`. That keeps register
  identifiers out of the log, including blocked attempts.
- **Fixed feed addresses** (NVD API, CISA KEV feed, EPSS API and the MITRE
  ATT&CK repository on raw.githubusercontent.com) are allowed by URL prefix
  even if their domains are removed from `ALLOWED_DOMAINS`. Turning external
  sources off blocks them too.
- **The agent status endpoint only checks that the key and model are set.**
  The agent's internal `/status/check` confirms that the key and model work
  with a models lookup, which spends no tokens.
- **Allowed domains are read-only on the Settings page for now.** They come
  from `.env`.

**Quality, triage and classification** (`AGENT_BUILD.md`, milestone 3)
- **Gaps below the triage threshold don't block.** Section 9.1 says a missing
  asset always makes a risk `needs_info`. Section 14 expects TR-16, which lists
  no assets or environment, to be ready and then screened out. We chose
  section 14. Missing impact, likelihood or risk statement always blocks.
  Missing assets or environment, and the model's three text checks (names an
  asset, a condition, a loss path), block only a risk that would qualify: a
  score at or above the threshold, or impact 5. For other risks they are listed
  as gaps but don't block, since triage screens those risks out anyway.
- **The rules live in api and the model's part lives in the agent.** The
  quality rules (`api/app/register/quality.py`) and the triage rule
  (`api/app/register/triage.py`) are plain tested code. The agent's three
  tasks only judge text, explain and classify. A triage explanation that fails
  leaves the rule's result in place, with a note.
- **Classification runs only for risks that qualify**, including risks an
  analyst overrides into the pipeline (section 6: screened-out risks stop).
  Overriding a risk out of the pipeline keeps any condition type it already
  had, but hides it.
- **Jobs run in a small thread pool inside api** (`AGENT_WORKERS`, default 3).
  Import returns at once and the UI polls. Runs left queued or running when
  api restarts are marked failed at the next start, with a message to run the
  checks again. Run timestamps carry microseconds so runs sort in order.
- **Re-checking.** `POST /api/agent/risks/{id}/intake` re-runs the three
  checks for one risk. `POST /api/agent/register/intake` runs them for every
  risk not yet checked on its current entry. These add an `intake` task to
  section 11's list. Import skips risks whose quality check already succeeded
  on the same input (the run's input hash, which includes the threshold).
- **A new check makes new drafts.** Older ones are kept for the record. A
  triage override applies to the triage draft it was made on, so re-checking a
  changed risk clears it.
- **Only what the tasks need is sent to the model.** That is the title,
  category, asset IDs, environment, risk action, scores, mitigation plan and
  analysis text. People's names are left out.
- **The model's gap `field` comes from a fixed list** of register fields and
  analysis sections, so gaps can be labeled. The register list's note shows the
  rule gaps and the checks that blocked. The agent's extra comments appear on
  the risk's Quality tab.
- **Classification wording.** The prompt says a gap in overseeing a supplier
  (such as an overdue vendor assessment) is `third_party`, not `process_gap`.
  The condition type routes evidence gathering, and section 7 sends
  `third_party` to vendor assessments and breach disclosures.
- **Reviewer name.** With `ANALYST_NAME` unset, reviews are recorded as
  "Analyst (name not set)".
- **Unit tests can't reach the agent.** An automatic fixture makes the agent
  read as off and runs jobs inline in every api test except those marked
  `live`, so importing a register in a test never calls the Claude API.

## Later extensions

The code leaves room for these. They are not built:

- **AI assistance** (an estimation coach, scenario drafting, rationale review)
  as a separate service. It must not change the calculation, which stays in
  `engine/`.
- **Sensitivity analysis.** `simulate_state()` takes a single state, so swinging
  one factor to its P10 and P90 and drawing a tornado chart is a loop over
  modified copies.
- **FAIR-CAM** control modeling.
- **Authentication with roles, and Postgres.** Database access goes through
  SQLAlchemy and `DATABASE_URL`, so Postgres needs a driver and a new URL.
- **GRC integration and aggregate risk** across scenarios, as new routers over
  the same stored analyses and runs.

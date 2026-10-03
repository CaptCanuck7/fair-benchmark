# FAIR Risk Workbench: local Docker build

You are building a local web application for Open FAIR cyber risk quantification. It runs on the developer's machine with `docker compose up --build`. A working single-file prototype exists at `reference/fair-workbench.html`. Treat it as the behavioral and content reference: match its workflow, help text, checks, and results. Re-architect it into a proper frontend, API, and database as described below.

Read this whole file before writing code. Work through the milestones in order, and verify each one before moving on.

## 1. Purpose and scope

The app is a learning and prototyping tool for a cyber risk team. An analyst uses it to:

1. Scope a loss event scenario (asset, threat community, threat type, effect).
2. Estimate FAIR factors as ranges (minimum, most likely, maximum) with a confidence level, plus a rationale and source for each.
3. Run a Monte Carlo simulation and read the results, the automatic sanity checks, and the charts.
4. Add treatment options (copies of the current state with changed factors and an annual cost) and compare them.
5. Save analyses, keep a history of simulation runs, and export or import analyses as JSON, with results also exportable as CSV.

**Out of scope for this build:** authentication and multi-user support, cloud deployment, AI features, FAIR-CAM, and integration with external GRC systems. Leave the code structured so these can be added later (see section 11).

The app must state on screen that it follows the Open FAIR taxonomy (O-RT) and analysis approach (O-RA) but is not a certified Open FAIR product.

## 2. Architecture

Two containers, orchestrated by Docker Compose:

| Service | Stack | Role |
|---|---|---|
| `api` | Python 3.12, FastAPI, Pydantic v2, NumPy, SQLAlchemy 2, SQLite | Simulation engine, validation, checks, persistence, export |
| `web` | React 18 + TypeScript + Vite, built to static files and served by nginx | UI; nginx proxies `/api/*` to `api` |

Decisions and reasons:
- **The simulation runs server-side in NumPy.** It's vectorized, unit-testable, and auditable. The browser never computes results.
- **SQLite on a named Docker volume** keeps setup to a single command. Access goes through SQLAlchemy so Postgres can be swapped in later by changing the connection URL.
- **The checks run server-side** and are returned with the results, so the rules live in one tested place.

### Repository layout

```
fair-workbench/
  CLAUDE.md
  README.md
  docker-compose.yml
  .env.example
  reference/
    fair-workbench.html        # prototype; do not modify
  api/
    Dockerfile
    pyproject.toml
    app/
      main.py                  # FastAPI app, routers, CORS, limits
      config.py
      db.py                    # engine, session, init
      models.py                # SQLAlchemy tables
      schemas.py               # Pydantic models (the analysis document)
      engine/
        distributions.py       # PERT sampling
        simulate.py            # Monte Carlo
        stats.py               # percentiles, exceedance, summaries
        checks.py              # pre-run and post-run checks
      routers/
        analyses.py
        simulate.py
        io.py                  # import/export
      content/
        factors.py             # factor labels, units, help text, data sources
    tests/
      test_distributions.py
      test_simulate.py
      test_checks.py
      test_api.py
      fixtures/product_x.json
  web/
    Dockerfile
    nginx.conf
    package.json
    vite.config.ts
    src/
      main.tsx
      App.tsx
      api/client.ts
      types.ts                 # mirrors api/app/schemas.py
      components/              # one file per section/component
      styles/
```

## 3. Domain model

The analysis document must stay **compatible with the prototype's JSON export**, so a file exported from `reference/fair-workbench.html` imports cleanly. Define it in Pydantic (`schemas.py`) and mirror it in `web/src/types.ts`.

```jsonc
{
  "format": "fair-workbench",
  "version": 1,
  "id": "string",
  "title": "string",
  "createdAt": "ISO-8601",
  "updatedAt": "ISO-8601",
  "scope": {
    "asset": "", "threatCommunity": "",
    "threatType": "Malicious, external | Malicious, internal | Error (accidental) | Failure (system or vendor) | Natural",
    "effect": "Confidentiality | Integrity | Availability",
    "condition": "", "controls": "", "notes": ""
  },
  "settings": { "iterations": 10000, "seed": 20260930, "threshold": null },
  "states": [ /* State; index 0 is always the current state */ ],
  "active": 0,
  "summary": { /* optional, written on export; ignore on import */ }
}
```

**State**
```jsonc
{
  "id": "string", "name": "Current state", "notes": "", "cost": null,   // cost = annual cost, treatments only
  "lef": {
    "mode": "tef_vuln | cf_poa | lef",
    "vulnMode": "direct | tcap_rs",
    "lef": Dist, "tef": Dist, "cf": Dist, "poa": Dist,
    "vuln": Dist, "tcap": Dist, "rs": Dist
  },
  "primary":   { "productivity": Dist, "response": Dist, "replacement": Dist },
  "slef": Dist,
  "secondary": { "response": Dist, "fines": Dist, "competitive": Dist, "reputation": Dist }
}
```

**Dist**
```jsonc
{ "min": number|null, "ml": number|null, "max": number|null, "conf": "low|med|high", "src": "string" }
```

Units by factor:

| Factor | Kind | Unit as stored |
|---|---|---|
| lef, tef, cf | freq | events or contacts per year |
| poa, vuln, slef | pct | percent, 0–100 (divide by 100 when simulating) |
| tcap, rs | score | percentile, 0–100 |
| all primary and secondary forms | money | USD per event |

On import, fill missing fields with defaults (as the prototype's `normalize()` does), assign a new `id`, and reject documents without a `states` array with a clear error.

### Validation rules (a Dist)

- **Empty:** all three values null. This is allowed for optional factors.
- **Error** if any of these hold:
  - some values are set but not all three
  - any value is negative or not finite
  - a pct or score value is above 100
  - the values don't satisfy min ≤ ml ≤ max

Return field-level errors with the factor path (for example `states[1].lef.tef`) and the same messages the prototype uses.

### Required factors by method

- `mode = lef`: `lef`
- `mode = tef_vuln`: `tef`
- `mode = cf_poa`: `cf` and `poa`
- If mode isn't `lef`: `vuln` when `vulnMode = direct`, or `tcap` and `rs` when `vulnMode = tcap_rs`
- At least one valid primary form
- If any secondary form is valid, `slef` must be valid (error)
- If `slef` is valid but no secondary form is, secondary loss is treated as zero (warning)

## 4. Simulation engine

This section defines the calculation precisely. Implement it with NumPy, vectorized across years. Don't loop over years in Python.

### 4.1 PERT sampling

For a Dist with values a = min, m = ml, b = max, and λ from confidence (low = 2, med = 4, high = 6):

- If b − a ≤ 0, return the constant m.
- Otherwise α = 1 + λ(m − a)/(b − a), β = 1 + λ(b − m)/(b − a), and sample = a + Beta(α, β) × (b − a).
- Scale pct factors by 0.01 before sampling.

Use `rng = np.random.default_rng(seed)`, and use the same seed for every state in a run. This is the common random numbers method, so differences between options come from inputs, not noise.

### 4.2 Loss event frequency, per simulated year (N years)

- `mode = lef`: `lef_y = PERT(lef)`
- Otherwise:
  - TEF: `tef_y = PERT(tef)`, or for `cf_poa`, `tef_y = PERT(cf) × PERT(poa)/100`
  - Vulnerability:
    - `direct`: `vuln_y = PERT(vuln)/100`
    - `tcap_rs`: estimate one scalar `p = mean(PERT(tcap, 20000) > PERT(rs, 20000))`, set `vuln_y = p` for all years, and report `p` as `derivedVulnerability`
  - `lef_y = tef_y × vuln_y`
- Event count: `n_y ~ Poisson(lef_y)`. Thinning a Poisson process makes this equivalent to simulating each threat event and testing it for success.

### 4.3 Loss magnitude, per event

Let E = sum(n_y), and build `year_idx = np.repeat(arange(N), n_y)`.

- **Primary:** for each valid primary form, draw E samples. The per-event primary loss is their sum.
- **Secondary:** draw `slef_y = PERT(slef)/100` once per year. For each event, the secondary loss is triggered if `uniform < slef_y[year_idx]`. For triggered events, draw each valid secondary form and add it to that event's loss.
- **Annual loss:** `ale = np.bincount(year_idx, weights=event_loss, minlength=N)`.
- Track total loss by form (for the breakdown), the share of loss that is secondary, and the per-event losses (for the single-loss histogram). Keep at most 200,000 per-event values for the histogram; the stats can use all of them.

### 4.4 Outputs per state

| Field | Meaning |
|---|---|
| meanAnnualLoss | mean of ale |
| p10, p50, p90, p95, p99, max | percentiles of ale (NumPy linear interpolation) |
| chanceAnyLoss | share of years with ale > 0 |
| chanceAboveThreshold | share of years with ale > threshold, if a threshold is set |
| lefMean, lefP10, lefP90 | stats of lef_y |
| singleLossMean, singleLossP10, singleLossP50, singleLossP90 | stats of per-event loss |
| derivedVulnerability | p, or null |
| secondaryShareOfLoss | secondary total ÷ all loss |
| events | E |
| breakdown | mean annual loss by form, keyed like `primary.response` |
| exceedanceCurve | 121 points (x from 0 to niceMax(max(p99.5, threshold × 1.15)), y = share of years with ale > x) |
| histogram | 24 bins of single-event loss from 0 to niceMax(p99 of single loss), last bin catches the overflow |

Implement `niceMax` exactly as the prototype does: round up to 1, 2, 2.5, 5, or 10 × 10ⁿ. For the comparison chart, compute the curves server-side on a shared x-axis across all states in the run.

### 4.5 Comparison, for each treatment vs state 0

- reduction = mean(state 0) − mean(treatment)
- reductionPct = reduction ÷ mean(state 0)
- netBenefit = reduction − cost (only if cost is set)
- return = reduction ÷ cost (only if cost > 0)

### 4.6 Limits and performance

- Iterations are one of 1,000, 10,000, 50,000, or 100,000. Reject anything above 200,000.
- A run of 100,000 years with 4 states and a loss event frequency up to about 50 per year must finish in under 5 seconds. If E would exceed 20 million events, return a 422 error explaining that the frequency is implausibly high for a loss event.

## 5. Checks

Port the rules from the prototype's `preChecks()`, `postChecks()`, and compare-section checks into `engine/checks.py`. Each check returns `{level: error|warn|info|ok, code, message, path?}`. Keep the prototype's thresholds and wording:

**Pre-run checks** (errors block the run): missing or invalid required factors, invalid optional factors, no primary form, secondary amounts without SLEF, and SLEF without amounts (warning).

**Post-run checks:**
- lefMean > 1 per year: warn that these may be attempts or incidents, not loss events.
- lefMean < 0.01: info about a very rare event.
- Direct vulnerability with ml ≥ 50% while existing controls are listed: warn.
- Derived vulnerability: info telling the analyst to sense-check it.
- p50 = 0 and mean > 0: info to report the mean and tail, not the median.
- p95 ÷ mean > 5: info about a heavy tail.
- secondaryShareOfLoss > 0.7: info that secondary loss drives the result.
- Any money factor with max ÷ min > 100 (min > 0): info about very wide ranges.
- Any factor with min = max: warn that no uncertainty is expressed.
- Any populated factor with an empty `src`: warn about undocumented estimates, showing the count.
- events < 50: info about few simulated events.
- None of the above: an `ok` message saying the checks passed but that doesn't make the inputs right.

**Compare checks:**
- A treatment with more loss than the current state: warn.
- Reduction under 5%: info.
- Cost greater than reduction: info pointing to the tail columns.
- Cost not entered: info.

## 6. API

Base path `/api`. JSON throughout. Pydantic validates every request. Cap request bodies at 1 MB.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness check |
| GET | `/api/analyses` | List: id, title, number of states, updatedAt, latest mean annual loss per state |
| POST | `/api/analyses` | Create (an empty body gives a blank analysis) |
| GET | `/api/analyses/{id}` | Fetch the document |
| PUT | `/api/analyses/{id}` | Replace the document (the frontend autosaves, debounced) |
| DELETE | `/api/analyses/{id}` | Delete the analysis and its runs |
| POST | `/api/analyses/{id}/duplicate` | Copy as a new analysis |
| POST | `/api/validate` | Body: analysis. Returns pre-run checks per state |
| POST | `/api/analyses/{id}/runs` | Run the simulation on the saved document. Stores and returns the run |
| GET | `/api/analyses/{id}/runs` | Run history: runAt, settings, headline numbers |
| GET | `/api/analyses/{id}/runs/{runId}` | Full stored run |
| POST | `/api/simulate` | Stateless run on a document in the body (used for previews and tests) |
| GET | `/api/analyses/{id}/export.json` | Document plus the latest run summary, in prototype format |
| GET | `/api/analyses/{id}/runs/{runId}/export.csv` | Results table, same columns as the prototype's CSV |
| POST | `/api/import` | Body: an exported JSON document. Creates a new analysis |

**Tables**
- `analyses(id TEXT PK, title TEXT, document JSON, created_at, updated_at)`
- `runs(id TEXT PK, analysis_id FK, run_at, iterations INT, seed INT, input_hash TEXT, document_snapshot JSON, results JSON)`

`input_hash` is a SHA-256 of the canonical JSON of the scope, states, and settings, excluding notes and names. The UI uses it to show that "inputs changed since the last run." The snapshot means every stored run can be reproduced and audited.

## 7. Frontend

Match the prototype's flow and copy. Copy every factor's label, unit, help text, and data-source text from the `F` object in `reference/fair-workbench.html` into `api/app/content/factors.py`, and serve it from `GET /api/content/factors` so the text lives in one place.

**Pages**
- **Analyses list:** new, open, duplicate, delete (with an inline confirm), import, and the latest headline numbers for each.
- **Analysis workspace.** A single page with these sections, in order:
  1. **Scope the scenario:** the fields plus the "What makes a good scenario" guidance.
  2. **Option tabs:** current state plus up to 3 treatments. "Add treatment option" copies the active state. Fields for name, notes, and annual cost (treatments only), plus delete.
  3. **Loss event frequency:** method choice and vulnerability method choice, as in the prototype, with only the relevant factor rows shown.
  4. **Primary loss**
  5. **Secondary loss**
  6. **Results** for the active option: a plain-English summary paragraph, the key numbers with explanations, the checks, a loss exceedance curve, a single-event histogram, and a breakdown by form of loss. Also the threshold field and the simulation settings (iterations, seed).
  7. **Compare options:** the table and overlaid exceedance curves.
  8. **Run history:** a list of past runs. Selecting one shows its results read-only.
- **Taxonomy sidebar:** the Open FAIR tree with the estimated / calculated / not-used states and click-to-jump behavior. It's sticky on wide screens and sits above the content on narrow ones.
- **Sticky run bar:** a status message and a "Run simulation" button.

**Factor row:** min / most likely / max inputs that accept `150k`, `1.5m`, `1,200`, and `8%`; a confidence select; inline validation; an expandable "What this means and where to get it" note; and a rationale and sources textarea.

**Behavior**
- Autosave with PUT, debounced at 1 second, and show the save status.
- Show a stale-results banner when the current `input_hash` doesn't match the latest run.
- If the run fails pre-checks, switch to the failing option, scroll to the first failing factor, and show the message in the run bar.

**Charts:** use Recharts, or hand-built SVG as in the prototype. Charts take their data from the API's `exceedanceCurve` and `histogram`. Format money as $K, $M, $B and percentages as in the prototype.

**Design:** keep the prototype's tokens (palette, Public Sans with a system fallback, tabular numbers). Support light and dark themes through `prefers-color-scheme`. The layout must work at 380 px wide. Visible focus states, labels on every input, and charts with `aria-label`.

## 8. Docker

**docker-compose.yml**
- `api`: build from `./api`, serve uvicorn on port 8000 (internal only), mount the named volume `fair_data` at `/data`, set `DATABASE_URL=sqlite:////data/fair.db`, and add a healthcheck on `/api/health`.
- `web`: a multi-stage build (node:20-alpine to build, nginx:alpine to serve). Publish only **`127.0.0.1:8080:80`**. nginx serves the SPA with a fallback to `index.html` and proxies `/api/` to `http://api:8000`.
- `web` depends on `api` being healthy.

**Security baseline.** This is a risk tool, so it should model good practice:
- Both containers run as non-root users. Use slim or alpine base images with pinned versions.
- The API isn't published to the host. Only nginx is, and only on localhost.
- CORS allows only the web origin. In compose, everything is same-origin through nginx.
- No secrets are needed. `.env.example` documents the config variables.
- nginx sets basic security headers: `X-Content-Type-Options`, `Referrer-Policy`, a CSP limited to self, and `frame-ancestors 'none'`.
- Enforce the body size and iteration limits on the server.

**Commands to document in the README:**
- `docker compose up --build` to start, then open http://localhost:8080
- `docker compose exec api pytest` to run the tests
- How to back up and restore the `fair_data` volume
- How to reset by removing the volume

## 9. Tests (required)

**`test_distributions.py`**
- PERT with min = ml = max returns a constant.
- The sample mean is close to the PERT mean (a + λm + b)/(λ + 2) within 1% over 200k samples, for each confidence level.
- All samples fall within [min, max].

**`test_simulate.py`**
- **Deterministic case:** LEF fixed at 0.5 (min = ml = max) and one primary form fixed at $100,000. The mean annual loss is about $50,000 within 2%, and chanceAnyLoss is about 1 − e^(−0.5) ≈ 39.3% within 1 point, at 100k iterations.
- **Reproducibility:** the same seed gives identical results; different seeds give mean annual loss within 3% of each other at 100k iterations.
- **Reference case `fixtures/product_x.json`:**
  - TEF 0.5 / 2 / 6
  - Vulnerability 2 / 8 / 20%
  - Primary response 50K / 150K / 400K and replacement 25K / 75K / 250K
  - SLEF 30 / 60 / 90%
  - Secondary response 100K / 400K / 1.5M, fines 0 / 100K / 1M, reputation 0 / 250K / 3M
  - All confidence medium

  At 100k iterations, expect:
  - mean annual loss between $225K and $260K
  - chanceAnyLoss between 17.5% and 20.5%
  - p90 between $1.08M and $1.30M
  - lefMean between 0.20 and 0.23
  - single-loss p50 between $1.05M and $1.30M
  - secondaryShareOfLoss between 0.70 and 0.82

  (The prototype and an independent Python run both landed inside these ranges.)
- **tcap_rs:** TCap 40 / 60 / 80 vs RS 50 / 70 / 90 gives derivedVulnerability between 0.15 and 0.22.
- **Thinning check:** for the direct vulnerability method, the mean of n_y is about mean(tef_y × vuln_y).

**`test_checks.py`:** each rule fires on a crafted input and doesn't fire on the reference case where it shouldn't.

**`test_api.py`:**
- Create, update, run, list runs, export, and import round trip.
- Importing `reference` prototype exports works.
- Invalid input returns 422 with field paths.
- Iterations above the limit are rejected.

## 10. Milestones

Complete each milestone and run its verification before starting the next. Commit after each one.

1. **Scaffold:** repo layout, both Dockerfiles, compose, health endpoint, and a placeholder web page. Verify that `docker compose up --build` serves http://localhost:8080 and that `/api/health` responds through nginx.
2. **Engine:** distributions, simulation, stats, and checks, with all of `test_distributions`, `test_simulate`, and `test_checks` passing. Verify with `docker compose exec api pytest`.
3. **API and persistence:** the endpoints, tables, input hash, and import/export. Verify that `test_api` passes and that a prototype export imports.
4. **Frontend inputs:** list page, scope, option tabs, factor rows with validation, taxonomy sidebar, and autosave. Verify that state survives a page reload and a container restart.
5. **Frontend results:** run bar, results section, charts, compare, run history, and the stale banner. Verify by entering the Product X case by hand and confirming the numbers fall within the section 9 ranges.
6. **Hardening and docs:** the security baseline, a 380 px layout check, dark mode, the README, and `.env.example`. Verify with a final full rebuild from a clean volume.

If something in this spec is ambiguous, check `reference/fair-workbench.html` first. If it's still unclear, choose the simpler option and note the decision in the README under "Decisions."

## 11. Later extensions (don't build now)

Structure the code so these are easy to add later:
- **AI assistance** (an estimation coach, scenario drafting, rationale review) as a separate service. It must never change the calculation.
- **Sensitivity analysis:** swing each factor to its P10 and P90 and draw a tornado chart.
- **FAIR-CAM** control modeling.
- **Authentication** with roles, and Postgres instead of SQLite.
- **GRC system-of-record integration:** pull issues and exceptions, push results.
- **Aggregate risk** across multiple scenarios.

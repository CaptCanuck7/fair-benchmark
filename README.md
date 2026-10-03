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

## Configuration

No configuration is needed. To override defaults, copy `.env.example` to
`.env`. It documents `DATABASE_URL`, `CORS_ORIGIN` and `MAX_BODY_BYTES`.

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
api/tests/           pytest suite and fixtures
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
| GET | `/openapi.json` | The OpenAPI schema |

Validation errors return 422 as
`{"detail": "...", "errors": [{"path": "states[1].lef.tef", "message": "..."}]}`.

## Security

This is a risk tool, so it follows the baseline in `CLAUDE.md`:

- **Only nginx is published, and only on `127.0.0.1:8080`.** The API isn't
  reachable from the host.
- **Both containers run as non-root users** (`app` and `nginx`), with:
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
- **No secrets** are needed or stored.

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

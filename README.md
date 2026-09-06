# BMA National Border Targeting Centre Brief

The BMA Briefing App is a shared FastAPI and SQLite application for collecting open-source border reporting, maintaining operational watchlists, recording tracking notes, and producing rapid intelligence assessments.

The original desktop prototype stored all operational data in one browser. The supported application stores shared state in SQLite, attributes writes to authenticated users, and retains generated exports on the server.

## Access and roles

Authentication uses Microsoft Entra ID or Google OIDC. An email address must be approved before its first login; the provider's immutable issuer and subject become the durable identity.

- `viewer` reads briefs, watchlists, assessments, and retained exports.
- `analyst` can also refresh reporting, manage interests and watch items, add notes, generate assessments, and create exports.
- `admin` can additionally manage users, import legacy browser data, inspect audit events, and delete exports.

Blank databases seed `barry@ubiquitech.co.za`, `rolbaron001@gmail.com`, and `christo.bezuidenhout@bma.gov.za` as administrators. Bootstrap does not overwrite later role changes.

## Local use

Double-click `Start NBTC Brief.bat`. It installs missing Python packages, starts the application only on `127.0.0.1:8770`, and opens the development sign-in page. Development sign-in is accepted only when explicitly enabled with a localhost public URL.

For command-line development:

```powershell
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
$env:BMA_BRIEFING_PUBLIC_URL='http://localhost:8770'
$env:BMA_BRIEFING_DEVELOPMENT_AUTH='true'
.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8770
```

Run tests with `.venv\Scripts\pytest -q`.

## Production configuration

Use `.env.example` as a reference. Production needs an independent session secret, Microsoft and/or Google credentials, and persistent database/export paths. Register these callbacks:

- `https://bma-briefing.ubiquitech.co.za/auth/microsoft/callback`
- `https://bma-briefing.ubiquitech.co.za/auth/google/callback`

AI is disabled unless `BMA_BRIEFING_AI_ENABLED=true` and `ANTHROPIC_API_KEY` are both configured. Selected source records are sent to Anthropic only when an analyst explicitly requests an assessment.

The worker refreshes daily at 06:00 `Africa/Johannesburg`. Timezone, hour, and minute are configurable. A failed refresh never replaces the last successful briefing.

## Container and persistence

The image runs as an unprivileged user and listens on port `8790`. SQLite and exports use separate volumes:

```bash
docker run -d --name bma-briefing --restart unless-stopped \
  -p 127.0.0.1:8792:8790 --env-file .env.production \
  -v briefing-db:/data/db \
  -v briefing-exports:/data/exports \
  ghcr.io/barrypitman/bma-briefing-app:latest
```

Startup creates the data layout, applies forward-only Alembic migrations, seeds users idempotently, and reports healthy through `/healthz` only when the schema is current. Back up both volumes before an update. Do not delete or recreate them to solve an application problem.

GitHub builds display their branch and Actions run number in the UI footer, for example `main-4`. Local source runs display `development`.

The supported server deployment is the shared Compose/Nginx/Watchtower stack in the sibling `bma-database-app` repository. This repository deliberately does not duplicate that stack.

## Legacy browser migration

Run the new application locally on the original `http://localhost:8770` origin and sign in as an administrator. Open `/legacy-export` to download the old `nbtc_brief_v1` state, then upload that JSON file from Administration. Interests, watchlist/archive records, notes, and assessments are imported transactionally. Authentication information, UI preferences, and transient unpinned briefing data are ignored. Re-importing the same file is harmless.

## Operational security

All business routes require a current signed session; every mutation also requires CSRF and an appropriate role. External reporting is untrusted. The fetcher verifies TLS, restricts RSS fetching to Google News over HTTPS, blocks non-public destinations, and bounds redirects and response sizes. The application never accepts browser-supplied assessment grounding, actor identities, or filesystem paths.

Read `AGENTS.md` before changing persistence, authentication, fetching, migrations, AI, or deployment behavior.

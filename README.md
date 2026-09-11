# Douyin Caption

AI-assisted Douyin spoken-script rewriting workspace.

## Stack

- Backend: FastAPI, SQLAlchemy, PostgreSQL, Redis
- Frontend: Vue 3, TypeScript, Vite
- Tests: Pytest, Vitest, Playwright

## Local setup

Generate independent random values for `APP_SECRET_KEY` and `KEY_ENCRYPTION_SECRET` before starting
the API. `KEY_ENCRYPTION_SECRET` must contain at least 32 random characters. Existing installations
with a shorter value may temporarily set `ALLOW_LEGACY_WEAK_KEY_ENCRYPTION_SECRET=true` and retain the
old secret only long enough to coordinate rotation. Each member must delete the saved
setting while the old secret is active; then install a new strong secret, disable the compatibility
flag, and have members enter their API Keys again. Changing the secret without re-encrypting or first
deleting existing settings makes those settings unreadable.

```powershell
Copy-Item .env.example .env
docker compose up -d
py -3.12 -m venv backend\.venv
backend\.venv\Scripts\python -m pip install -e "backend[dev]"
Set-Location frontend
npm install
```

The repository contains only source code, migrations, documentation, and dependency
lockfiles. Local secrets (`.env`), virtual environments, databases, runtime logs, caches,
and frontend test/build output are ignored by Git. The root `development.log` is the
project change log and is intentionally versioned. After cloning, recreate local runtime
files with the commands above rather than copying them into the repository.

Redis is required by default for login throttling and AI-call coordination. For a local,
single-process backend without Redis, set `ALLOW_IN_MEMORY_COORDINATION=true`. The current fallback
applies to login throttling and the per-member AI-call lock. In-memory state is not shared between
workers and the setting is rejected when `APP_ENV=production`.

PostgreSQL remains the production database. A local single-process installation may instead set
`DATABASE_URL=sqlite+aiosqlite:///D:/path/to/development.sqlite3`; the migration chain supports both.

## Database and first administrator

Run the database migration before creating the initial administrator. From the backend virtual
environment, run the project's Alembic upgrade command, then bootstrap the account:

```powershell
backend\.venv\Scripts\alembic.exe -c alembic.ini upgrade head
$env:BOOTSTRAP_ADMIN_USERNAME = "admin"
$env:BOOTSTRAP_ADMIN_DISPLAY_NAME = "Administrator"
$env:BOOTSTRAP_ADMIN_PASSWORD = Read-Host "Initial administrator password" -AsSecureString |
  ConvertFrom-SecureString -AsPlainText
backend\.venv\Scripts\bootstrap-admin.exe
Remove-Item Env:BOOTSTRAP_ADMIN_PASSWORD
```

The password is read from the environment or from a hidden interactive prompt. There is no password
command-line argument, so it is not exposed in shell history or process arguments. Re-running the
command with the same administrator is safe and does not reset the password. If another administrator
already exists, the command refuses to create a second bootstrap account.

For an interactive password prompt, omit `BOOTSTRAP_ADMIN_PASSWORD`:

```powershell
backend\.venv\Scripts\bootstrap-admin.exe --username admin --display-name Administrator
```

## Run locally

```powershell
backend\.venv\Scripts\uvicorn.exe app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
npm --prefix frontend run dev
```

The API is available at `http://127.0.0.1:8000`; interactive API documentation is at
`http://127.0.0.1:8000/docs`. The frontend is available at `http://127.0.0.1:5173`.

AI submissions enter a durable backend queue and immediately return. The API process starts its
queue worker automatically; keep the backend running while work is pending. Each member's work is
serial, and different members can run concurrently. The floating task center follows progress
across pages and browser reloads, and provides queued cancellation, failure retry and result links.
Run `alembic upgrade head` before starting an updated backend. Queued work survives server restarts;
interrupted running requests are cancelled on graceful shutdown or recovered as failed after a
hard exit, and can be retried explicitly.

Regression checks: `npm --prefix frontend test`, `npm --prefix frontend run build`, and
`cd frontend; npx playwright test` (Chrome). Browser tests use simulated API responses and do not
spend model credits or change saved documents.

## Server deployment

The checked-in systemd units and the deployment, backup, migration, verification and rollback
runbook are documented in [`deploy/README.md`](deploy/README.md). The units intentionally mirror the
current Ubuntu server and contain its fixed user and repository path; review those values before
using them on another host. Production secrets and database files remain outside Git.

## Provider URL security

Each member enters the provider's model name directly in Settings. Saving, connection tests, and AI
requests use that name. Run `alembic upgrade head` when updating an existing installation; the
migration converts saved catalog references to their provider model names while retaining API keys.
Settings also include a response timeout in seconds (default 240, integer range 10-600), applied to
AI requests and connection tests. Existing connections receive 240 seconds during migration.
Members can save timeout changes without entering their API Key again.

Provider URLs cannot contain credentials, queries or fragments and must resolve only to public IP
addresses. Production mode also requires HTTPS. DNS is checked immediately before connection tests,
but application-level validation cannot fully prevent DNS rebinding because the HTTP client resolves
the hostname again. Production deployments must block private, loopback, link-local and metadata
destinations with an outbound firewall or controlled HTTP proxy. AI provider calls should apply the
same `ProviderUrlPolicy` immediately before every outbound request.

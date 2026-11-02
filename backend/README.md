# Uniflow API

FastAPI service for the Uniflow academic support platform. This folder also owns its container images and Azure deployment configuration.

## Local development

From this directory, create and activate a Python 3.12 environment, then install dependencies:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start the API from this directory with:

```bash
uvicorn app.main:app --reload
```

The API listens on port 8000. Open `/docs` for the OpenAPI interface and `/health` for the health endpoint. Configure local backend settings in the ignored `.env` file; configure the frontend independently in `../frontend/.env.local`.

## Upstash Redis

Set `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` in the backend environment. The API uses the Upstash REST interface for a short-lived dashboard attendance-summary cache and distributed university-portal sync locks. Attendance cache entries expire after 20 seconds and are invalidated when portal data or timetable entries change. Portal locks expire after 15 minutes; if Redis is unavailable, portal sync falls back to the existing PostgreSQL advisory lock.

## Backend layout

```text
app/
├── api/
│   └── endpoints/   HTTP routes and the API router registry
├── <feature>/       Domain models, schemas, repositories, and services
├── core/            Configuration, logging, security, and cross-cutting concerns
├── db/
│   ├── models/      SQLAlchemy entities grouped by domain
│   ├── repositories/ Persistence queries grouped by domain
│   └── *.py         Database setup and external storage clients
├── integrations/    External provider clients and adapters
├── services/        Shared application services
└── main.py          FastAPI application and lifecycle
alembic/             Database migrations
scripts/             Local maintenance commands
tests/               Automated tests
```

The API registry mounts endpoint modules under the `/api/v1` prefix used by the web client. HTTP routes are centralized under `app/api/endpoints/`; domain packages hold business logic, schemas, persistence, and provider integrations. Keep HTTP handling thin, put business rules in services, and keep SQLAlchemy queries in repositories. ORM models and repositories are grouped into focused modules.

## Database changes

Create schema changes as Alembic migrations under `alembic/versions/`. Do not edit an already-applied migration to change a deployed schema. Apply migrations with `alembic upgrade head` from this directory.

## Tests

Run backend tests from this directory with `python -m pytest`.

## Azure deployment

Azure Docker Compose, Caddy, and production environment examples live in [`deploy/`](deploy/). GitHub Actions builds and deploys backend images only; Vercel handles the frontend separately. See the repository [deployment guide](../docs/deployment.md).

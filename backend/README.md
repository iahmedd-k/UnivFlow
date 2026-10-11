# Uniflow API

FastAPI service for the Uniflow academic support platform. Full-stack setup and root commands are documented in the repository [README](../README.md).

## Local development

From the repository root, create and activate a Python 3.12 environment, then install dependencies:

```powershell
python -m venv backend/.venv
.\backend\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
```

Start the API from the repository root with `npm run dev:backend`, or from `backend/` with:

```bash
uvicorn app.main:app --reload
```

The API listens on port 8000. Open `/docs` for the OpenAPI interface and `/health` for the health endpoint.

## Upstash Redis

Set `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` in the backend environment. The API uses the Upstash REST interface for a short-lived dashboard attendance-summary cache and distributed university-portal sync locks. Attendance cache entries expire after 20 seconds and are invalidated when portal data or timetable entries change. Portal locks expire after 15 minutes; if Redis is unavailable, portal sync falls back to the existing PostgreSQL advisory lock.

## Backend layout

```text
app/
├── api/             Feature endpoint registry and shared HTTP endpoints
├── v1/api/endpoints/ Versioned execution and diagram endpoints
├── <feature>/       Domain endpoints, schemas, and feature services
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

The API registry mounts feature routers under the `/api/v1` prefix used by the web client. Feature routers live with their domain, such as `app/assignments/router.py`; versioned endpoints live in `app/v1/api/endpoints/`. Keep HTTP handling thin, put business rules in services, and keep SQLAlchemy queries in repositories. ORM models and repositories are grouped into focused modules; their package initializers re-export public names so existing imports remain compatible.

## Database changes

Create schema changes as Alembic migrations under `alembic/versions/`. Do not edit an already-applied migration to change a deployed schema. Apply migrations with `alembic upgrade head` from `backend/` or `npm run db:migrate` from the root.

## Tests

Run backend tests from `backend/` with `python -m pytest`, or from the repository root with `npm test`.

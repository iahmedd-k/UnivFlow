# Uniflow

Uniflow is an academic support platform with a Next.js frontend and a FastAPI backend.

## Project boundaries

- `frontend/` is the Next.js application and Vercel project root.
- `backend/` contains the API, migrations, tests, Dockerfiles, and Azure deployment configuration.
- PostgreSQL, Redis, and object storage are external services; Azure Compose does not run database or Redis containers.
- Vercel deploys the frontend. GitHub Actions tests both applications and deploys backend images to Azure.

## Local development

Start the frontend in one terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Start the backend in another terminal:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

The frontend runs at `http://localhost:3000`; the API runs at `http://localhost:8000`. FastAPI docs are at `http://localhost:8000/docs`.

Configure frontend values in `frontend/.env.local` and backend values in `backend/.env`. Keep credentials, local databases, browser profiles, and private keys out of Git.

## Where to work

- FastAPI routes, services, integrations, and persistence: `backend/app/`.
- Alembic schema changes: `backend/alembic/versions/`.
- Backend tests: `backend/tests/`.
- Next.js routes, components, and client helpers: `frontend/app/`.
- Azure container and runtime configuration: `backend/deploy/`.
- Deployment steps: [docs/deployment.md](docs/deployment.md).

Run frontend checks from `frontend/` (`npm run lint`, `npm run build`) and backend tests from `backend/` (`python -m pytest`).

## License

No license is currently specified in this repository.

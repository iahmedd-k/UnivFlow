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

## Private workspace access

Production dashboard features require a one-time administrator approval after Clerk sign-in. A user requests access, the configured administrator receives an eight-digit, account-bound code, and the administrator shares that code only with the matching account. Codes expire after ten minutes by default and are rate-limited. New Clerk accounts do not receive dashboard API access until approved.

Set `ACCESS_ADMIN_EMAIL` to the administrator inbox. OTP delivery uses the existing SendGrid configuration or SMTP fallback, so configure `SENDGRID_API_KEY` and `SENDGRID_FROM_EMAIL`, or `SMTP_USERNAME`, `SMTP_PASSWORD`, and `EMAIL_FROM`. The default admin address is `ahmedkhanofficials@gmail.com`. For local development the gate is bypassed.

From `backend/`, list or revoke existing approvals with `python scripts/manage_private_access.py list` and `python scripts/manage_private_access.py revoke <clerk-user-id>`. The private beta deployment should run one API instance because the existing APScheduler runs in-process.

## Assignment solver behavior

Assignment generation is Claude-only. Uniflow automates Claude.ai through the user's isolated browser profile; Claude usage limits and UI changes can interrupt a solve. Generated code is a draft: Uniflow does not execute it, and Claude-reported output is not execution evidence. Standalone code execution and diagram-generation endpoints are not exposed. Review generated work before submitting it to Classroom.

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

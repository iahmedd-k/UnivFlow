# Uniflow

Uniflow is an academic support platform with a Next.js web client and a FastAPI backend. It brings course work, assignments, classroom activity, schedules, document workflows, and AI-assisted study tools into one application.

## Repository layout

```text
.
├── backend/                 FastAPI application, database migrations, and Python tests
│   ├── app/                 API domains, services, integrations, and persistence
│   ├── alembic/             Database migration history
│   ├── scripts/             Local maintenance and seed commands
│   └── tests/               Automated backend tests
├── frontend/                Next.js App Router application
│   ├── app/                 Pages, layouts, route handlers, and UI components
│   └── public/              Static browser assets
├── .env.example             Environment variable template
└── package.json             Root development and workspace commands
```

## Requirements

- Node.js 18 or newer
- Python 3.12 or newer
- npm

External services such as Supabase, S3-compatible storage, Google APIs, Groq, Gemini, Piston, and Kroki are optional or feature-specific. Configure only the services needed for your local workflow.

## Local setup

1. Copy `.env.example` to `.env` and fill in the credentials for the services you plan to use. Keep real secrets out of Git.
2. Install the frontend and root JavaScript dependencies:

   ```bash
   npm install
   ```

3. Install backend dependencies from the repository root:

   ```bash
   python -m venv backend/.venv
   # Windows PowerShell
   .\backend\.venv\Scripts\Activate.ps1
   # macOS/Linux: source backend/.venv/bin/activate
   python -m pip install -r backend/requirements.txt
   ```

4. Start both services:

   ```bash
   npm run dev
   ```

The frontend runs at `http://localhost:3000`; the API runs at `http://localhost:8000`. FastAPI's interactive API documentation is available at `http://localhost:8000/docs`.

To run either service independently, use `npm run dev:frontend` or `npm run dev:backend`.

## Common commands

| Command | Purpose |
| --- | --- |
| `npm run dev` | Start frontend and backend in parallel |
| `npm run build` | Build the frontend for production |
| `npm run lint` | Run frontend linting |
| `npm test` | Run backend tests with pytest |
| `npm run db:migrate` | Apply Alembic database migrations |
| `npm run db:seed` | Seed local development data |

Backend commands expect the Python environment to be activated. They can also be run directly from `backend/`, for example `python -m pytest` and `alembic upgrade head`.

## Configuration

`.env.example` documents the available settings for application URLs, authentication, database/storage connections, AI providers, code execution, and diagram rendering. The frontend uses its own `.env.local` file for Next.js-specific public configuration. Never commit `.env`, `.env.local`, API keys, OAuth credentials, browser profiles, or local databases.

## Engineering notes

- Keep API route handlers in their domain package under `backend/app/`; place reusable business logic in services and provider-specific code in integrations.
- Keep database schema changes in Alembic migrations under `backend/alembic/versions/`.
- Keep frontend routes and route handlers in the Next.js App Router under `frontend/app/`; extract shared UI and API helpers into focused modules.
- Add automated backend tests under `backend/tests/` and frontend tests alongside an established test setup when one is introduced.
- `ASSIGNMENT_SOLVER_FLOW.md` documents the assignment-solving workflow.

## License

No license is currently specified in this repository.

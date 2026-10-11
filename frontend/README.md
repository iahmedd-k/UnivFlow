# Uniflow Web Client

The Uniflow web client uses Next.js App Router and React. The root repository README covers full-stack setup and common commands.

## Development

From the repository root, install dependencies and start the frontend with:

```bash
npm install
npm run dev:frontend
```

Or run `npm run dev` to start the frontend and FastAPI backend together. The frontend is available at `http://localhost:3000`.

Set `NEXT_PUBLIC_API_URL` in `.env.local` to the backend API base URL. The default is `http://localhost:8000/api/v1`.

## Project conventions

- App Router pages, layouts, and route handlers live under `app/`.
- Shared browser API helpers live under `app/lib/`.
- Static assets live under `public/`.
- Run `npm run lint` and `npm run build` from this directory, or use the root npm scripts.

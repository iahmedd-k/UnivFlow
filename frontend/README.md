# Uniflow Web Client

The Uniflow web client uses Next.js App Router and React. This folder is the Vercel project root; the FastAPI backend is maintained and deployed separately from `backend/`.

## Development

From this directory, install dependencies and start the frontend with:

```bash
npm ci
npm run dev
```

The frontend is available at `http://localhost:3000`. Run the backend separately using the instructions in [`../backend/README.md`](../backend/README.md).

Set `NEXT_PUBLIC_API_URL` in `.env.local` to the backend API base URL. The default is `http://localhost:8000/api/v1`.

## Project conventions

- App Router pages, layouts, and route handlers live under `app/`.
- Shared browser API helpers live under `app/lib/`.
- Static assets live under `public/`.
- Run `npm run lint` and `npm run build` from this directory.

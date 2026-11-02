# Uniflow architecture implementation plan

This plan records the target and the staged implementation for the current Uniflow codebase. The first increment is underway in this working tree; later steps are ordered to reduce operational risk and avoid a large, hard-to-review rewrite.

## Outcomes

- One owner for browser server state, API configuration, authentication, request deadlines, and cache invalidation.
- Bounded, user-scoped database reads and no duplicate engine/metadata registries.
- Responsive pages that render cached data and can show section-level failures without waiting for unrelated resources.
- Durable, observable background work for provider sync, document ingestion, AI, browser automation, and notifications.
- Explicit source and ownership semantics for courses, assignments, timetable, attendance, and document assets.

## Delivery order

### 0. Stabilize loading and connection behavior — in progress

- [x] Centralize the backend URL and share the frontend query client.
- [x] Add request cancellation/deadlines, bounded authentication token resolution, and mutation-driven cache invalidation.
- [x] Move Overview to one response and make Classroom, Attendance, and Timetable load core resources independently.
- [x] Move the Assignments page from an unscoped localStorage copy and component fetch state to user-scoped QueryClient queries shared with Classroom; invalidate affected coursework and overview queries after mutations.
- [x] Centralize manual/Clerk query-owner identity, remove only the previous owner’s cache when identity changes, and invalidate feature queries after API mutations while leaving portal sync from invalidating the manual timetable unless `sync_timetable=true` is explicit.
- [x] Move Portal connection settings into a user-scoped query and durable sync-job polling into a cancellable QueryClient query that stops at terminal states or repeated request failure.
- [x] Move dashboard-shell auth, private-access, and Classroom sync status into the shared QueryClient; Classroom and the shell now share the same user-scoped sync-status key rather than issuing separate status requests.
- [x] Make Google Classroom cookie-session writes idempotent: canonicalize and compare the encrypted stored snapshot, and skip commits when neither cookies nor user-agent changed.
- [x] Move Settings profile/email/auth/portal and browser session status reads to independent user-scoped QueryClient queries; share auth and portal keys with their other consumers and keep editable values as local drafts.
- [x] Move Mail & Drive auth, email category, and Drive reads into independent user-scoped QueryClient queries; cancel/unmount behavior now follows query signals, and refresh only refetches the separate resources.
- [x] Move activity runs, run stats, Classroom sync status, run events, and automation history to owner-scoped QueryClient queries; add the missing frontend API wrappers used by the existing activity screen.
- [x] Share the announcements list query between its index and detail routes, with cancellation, owner scoping, and retry UI.
- [x] Move Notifications list filters, stats, and briefing preferences into independent owner-scoped queries; keep preference edits as a local draft and expose per-resource retry behavior.
- [x] Add the missing scoped, typed Quiz list/detail API that the dashboard screen expected; share the paginated list query between Quiz index and detail views.
- [x] Split Exams, Classroom study materials, and RAG conversation list reads into independent owner-scoped queries; restore the study-plan API routes already used by the Exams UI and add API client methods for them.
- [x] Share the Exams list query with exam details and move assignment templates to a user-scoped query with retryable loading errors.
- [x] Move the legacy Courses/Study Assistant screen's course, Classroom material, and conversation lists to separate shared owner-scoped queries; course materials and conversation history now have independent loading states.
- [x] Move assignment detail reads into the shared owner-scoped QueryClient; reuse the list as a fallback for legacy backends and expose the query error with a retry action.
- [x] Narrow dashboard overview ORM loads to only the course, assignment, and attendance columns the read model needs, avoiding hydration of descriptions and unrelated coursework payload columns.
- [x] Narrow RAG document metadata and Classroom-backed document reads to SQL projections, avoiding provider sync side effects and large extracted-content/description hydration on list requests.
- [x] Stop scanning extracted material content and assignment descriptions with `length()` during RAG metadata listing; use stored file size or a display estimate instead.
- [x] Bound coursework/course list reads with stable `limit`/`offset` parameters, add deterministic tie-break ordering, and define strict Pydantic item schemas for those two high-use endpoints.
- [x] Scope assignment material projections and submission joins to the authenticated owner so inconsistent legacy rows cannot leak another owner’s material metadata.
- [x] Return database pool checkout timeouts as retryable HTTP 503 responses instead of generic 500 errors.
- [x] Make portal job claims row-locked and atomic; actually consume persisted bounded retries with exponential backoff instead of leaving failed jobs queued forever.
- [x] Add a reviewed additive Alembic migration for composite user-scoped read indexes. The configured Supabase database is still on m6 and the migration is intentionally unapplied pending query-plan review on a safe snapshot.
- [x] Skip unchanged Google Classroom cookie snapshot writes at both extension and API layers: extension renewals compare a local SHA-256 fingerprint, while the backend remains idempotent if a snapshot is sent.
- [x] Use one SQLAlchemy engine and one bounded connection pool for API and background services; the development default is capped at seven app connections to fit the observed Supabase session-pool budget.
- [x] Unify the declarative registry and import core/RAG model families in Alembic; production startup now expects migrations instead of calling `create_all`.
- [x] Add request correlation IDs and structured API timing; DB/provider/worker spans remain in the observability phase.
- [ ] Close this phase only after multi-tab load no longer causes pool waits or request timeouts. The local stress render still exposed a slow RAG document-metadata request and one classroom sync-status request failure while multiple pages and the browser extension were active; deadlines now surface this instead of spinning indefinitely, but the underlying contention/query cost is still open.

### 1. Data ownership and database correctness

- [x] Inventory the configured local schema and confirm its Alembic revision/head (`m6_schedule_user_unique`).
- [ ] Compare production schema, indexes, constraints, data quality, and Alembic baseline before applying schema migrations.
- [x] Keep a single declarative Base, engine, and session factory. Import every model family from the migration environment.
- Replace string-keyed `Setting` state in order of risk: provider credentials/connections, access grants, then user preferences. Keep secret values encrypted and out of query cache/logs.
- Add/verify tenant ownership, provider/source IDs, uniqueness constraints, and indexes on frequent user-scoped reads. Use explicit migrations, not `create_all`, for deployed environments.
- Keep recurring `TimetableEntry` separate from dated `ClassSchedule`; manual timetable stays canonical, portal import remains preview plus explicit apply.
- Store attendance snapshots with source and capture time; calculate aggregates from bounded projections.

### 2. Frontend server-state and cache contract

Use `frontend/app/lib/api.js` as the only JSON API client and `frontend/app/lib/api-config.js` as the only base URL source. The RAG client now delegates JSON requests to that client and shares auth, deadline/error behavior, and QueryClient-backed resource cache; its streaming transport shares the request ID and bounded auth lookup.

| Resource | Query scope | Freshness target | Invalidation |
|---|---|---:|---|
| Dashboard overview | user + overview | 30–60 seconds | affected coursework, attendance, timetable, academic record writes/sync |
| Courses | user + page/filter | 2 minutes | course sync, course update/delete |
| Assignments | user + page/filter/status | 30–60 seconds | sync, review, submit, solution state changes |
| Timetable | user + weekly/date range | 2 minutes | manual CRUD; explicit portal apply only |
| Attendance summary | user + summary/snapshot | 1–2 minutes | attendance import; timetable writes only if calculated projections depend on it |
| Document metadata (including PDF metadata/index state) | user + filters/page | 30–60 seconds | upload, delete, re-index, course-material attach/detach |
| Document bytes/PDF previews | user + immutable asset ID/version | do not put large binary bodies in QueryClient | signed URL or explicit download; browser/HTTP cache follows immutable version and private access policy |
| Document processing/job state | user + job/document ID | no stale cache while active; short cache after terminal state | job events/status transition |
| Conversations/messages | user + conversation + cursor | 15–30 seconds for list; message pages on demand | create/send/delete/rename |
| Provider settings/status | user + provider | 15–30 seconds | connect/disconnect/update |

All keys include an authenticated owner scope, not a raw token. API transport cache keys store a token fingerprint, not the JWT. GET requests deduplicate in flight; pages use independent queries and render cached data while refreshing. Status polling and active jobs bypass normal freshness. Uploading PDF/document bytes is a mutation; only compact metadata/status is cached. Never cache credentials or signed URLs beyond their expiry.

Mutation policy: update a known entity directly when its response is authoritative; otherwise invalidate only its resource family and the small set of dependent summaries. Avoid substring invalidation once the existing API cache migration is complete. Add cursor pagination before caching large lists. Keep form state local and server state in QueryClient.

### 3. Read paths, API contracts, and query cost

- Define Pydantic response models and stable envelopes for high-use endpoints first: overview, courses, assignments, timetable, attendance, document lists/status, and job status.
- Replace full ORM collection loads in dashboard/list endpoints with SQL counts, projections, ordering, and limits. Add cursor pagination for courses, assignments, conversations, and activity.
- Make the overview endpoint a read model with a bounded response and explicit freshness/capture timestamps. Keep detailed page resources separate.
- Audit query counts and add per-user indexes from measured query plans. Avoid Redis caching until invalidation and source-of-truth behavior are defined; the browser QueryClient handles interactive reads first.
- Standardize error shape, request ID, retryability, and cancellation semantics across FastAPI and both JSON/streaming frontend transports.

### 4. Domain boundaries

- Split Classroom routes into coursework reads/sync, browser session, assignment solution, and submission commands; move rules into application services and repositories.
- Consolidate the duplicate RAG route/service/model families behind one versioned contract. Preserve existing document IDs through an explicit migration and compatibility window.
- Keep identity/auth concerns in one dependency layer; standardize Clerk/manual user mapping and user-scoped access. Manual seeded authentication is development-only and explicit.
- Model shared file assets once with owner, provider, checksum/version, MIME type, size, and storage key. Coursework, assignments, templates, and RAG reference asset IDs rather than duplicate file metadata/content.

### 5. Durable asynchronous work

- Define one job lifecycle (`queued`, `running`, `succeeded`, `failed`, `cancelled`), progress events, idempotency key, retry policy, owner, and timestamps.
- Use the existing durable portal job as a reference, then move Classroom sync, document extraction/embedding, AI solution generation, browser automation, and notification delivery to workers.
- Add transactional outbox writes for jobs triggered by DB mutations. Use a durable queue compatible with the deployment environment; do not rely on a FastAPI process's memory for ownership or progress.
- Run APScheduler separately from API replicas, with a singleton/lease during migration. It now defaults off in development and on in production, configurable via `SCHEDULER_ENABLED`; add per-user concurrency limits and provider rate limits.
- Expose job resources for polling first, then SSE events for live progress. Poll only while active and stop on terminal status/unmount.

### 6. Reliability, security, and observability

- Configure database pool size/overflow/checkout timeout and per-statement PostgreSQL timeout from deployment connection budgets; observe checked-out connections and wait time. Verify sessions close in request and worker paths.
- Add tracing from browser request through API, SQL, queue, provider, and object storage. Record endpoint latency, DB query count, cache hit/miss, job age, retries, and timeout cause.
- Add rate limiting, upload limits/type checks, private object access, signed URL expiry, secret encryption/rotation, and audit events for provider connections and portal sync.
- Validate graceful shutdown, worker recovery, idempotency, and multi-replica scheduler behavior in staging before production rollout.

## Module target summary

| Module | Target |
|---|---|
| Overview | One typed, bounded SQL read model; one user-scoped query; stale-while-revalidate. |
| Courses/Classroom | Paginated normalized records; idempotent provider sync job; independent course and assignment queries. |
| Assignments/submissions | Separate coursework, solution, review, and submission services; durable transitions/jobs. |
| Timetable | Recurring pattern and dated occurrence types; manual schedule canonical; portal preview/apply. |
| Attendance | Timestamped source snapshots and SQL aggregates; explicit freshness. |
| Portal | Typed encrypted connection, durable sync checkpoints/job events, explicit timetable apply. |
| RAG/documents/PDFs | One asset identity and ingestion pipeline; metadata cache separate from large binary bytes; active processing status uncached. |
| AI/browser automation | Isolated workers, durable jobs/events, cancellation and per-user limits. |
| Notifications | Outbox-driven delivery jobs with preferences, retries, and idempotency. |
| Auth/settings | Canonical user/provider mapping, explicit access grants and typed preferences, short-lived status cache. |
| Activity/agent runs | Append-only events with cursor pagination and SSE for active runs. |
| Exams/templates/announcements/Drive | Typed paginated metadata, shared asset identity, provider-specific access policy. |

## Verification gates

For each increment: inspect the migration SQL and existing schema; compile/lint affected code; render each changed frontend route locally; exercise representative API responses and inspect API/worker logs for timeouts, pool exhaustion, and unhandled 5xx errors. Do not apply destructive schema changes or switch production job infrastructure without a reviewed migration and deployment plan.

## Working-tree status

Already present from the current loading-fix increment: shared QueryClient/provider, canonical API URL, bounded request/auth deadlines, cache invalidation, one Overview request, independent queries on the main dashboard tabs, and a unified engine/session export. This pass also unified the ORM metadata registry, loaded RAG models into Alembic metadata, stopped production runtime `create_all`, made pool limits configurable within the observed Supabase client budget, added request IDs and API timing, moved RAG document metadata, usage, and conversation lists into user-scoped QueryClient entries, removed per-file status polling in favor of one active document-list refresh, fingerprinted tokens in transport cache keys, and added resource-specific freshness windows. PDF bytes remain outside the metadata query cache. RAG listings no longer launch Classroom provider sync, stale processing documents are repaired with one scoped bulk update, metadata lists select only needed columns, and size estimates no longer scan extracted text. The extension skips unchanged cookie renewals, and the downloadable companion ZIP includes the updated extension. Mail & Drive, Activity, and Notifications use independent owner-scoped queries; Activity's missing API wrappers are implemented. Announcement index/detail pages share one query. Exams resources load independently, detail pages share the list query, assignment templates use a scoped query, and the legacy Courses/Study Assistant screen shares Classroom courses, materials, and RAG conversation queries with independent loading states. Quizzes has a scoped typed API and shared list cache; the Exams UI's existing study planner has backend routes and frontend client methods. Coursework list reads are bounded and typed; material projection and submission join are owner-scoped. Pool exhaustion returns retryable 503, and portal sync jobs use an atomic claim plus bounded retries. An additive composite-index migration was prepared but not applied because the active configured database uses a shared Supabase pooler and no safe snapshot query-plan review has been performed yet. Durable worker processes, settings/schema migrations, RAG/chat family consolidation, shared asset identity, and other-module query migration remain subsequent implementation stages.

Current evidence: backend health reported healthy dependencies; `/api/v1/dashboard/overview` returned HTTP 200 with an `X-Request-ID` and preserved counts (36 courses, 156 assignments, 3 classes today, 37 upcoming assignment records). Earlier pages rendered in Chrome: Overview metrics, 44 semester assignments, portal summary, Study Assistant history, and 11 Classroom courses/156 assignments. Settings’ six backing endpoints returned HTTP 200. Mail & Drive, Activity, Notifications, announcements, Exams, Quizzes, Templates, Exam details, and their API code linted without errors; changed dashboard routes returned local Next.js HTTP 200. Course and assignment list routes returned HTTP 200 with request IDs. Agent runs/stats/automation history, notification list/stats/preferences, Quiz list, and study-plan list routes returned HTTP 200 after restarting the non-reloading local API process. The study-plan create route rejected an invalid short syllabus with HTTP 422 before any AI work. Backend compile succeeded. Browser automation is disabled in Work settings, so changed pages were route-checked over local HTTP rather than inspected in a browser. The RAG document endpoint previously returned 362 documents after a slow request; latency and earlier QueuePool waits remain open. The active configured database is Supabase-backed, current Alembic revision is m6, and read-only inspection found 34 tables; the new composite-index migration is m7 and remains unapplied. No test suite was run. `git diff --check` passed with only line-ending notices. Earlier targeted ESLint for shell/settings changes had zero errors and three hook/navigation warnings.

Still required to satisfy the audit: remove the pool wait/query latency under concurrent authenticated multi-tab load; compare every deployed schema and run query plans against a safe snapshot before applying m7; replace string-keyed settings through dual-read migrations and finish tenant/source constraints; finish migrating every dashboard module to independent queries and infinite pagination where needed; add typed response contracts/projections to all high-use modules; consolidate RAG API/model families and Classroom service boundaries; add shared asset identities; and move long-running sync/AI/browser/notification work from FastAPI `BackgroundTasks` into a separately deployed durable worker/outbox. Phase 0 and the full architecture objective remain in progress.

# Uniflow live schema inventory

Read-only inspection of the PostgreSQL database configured for the local app on 2026-11-02. The app environment is labeled development, while the configured database is reached through a Supabase pooler; treat it as shared and do not infer that it is disposable. Alembic reports `m6_schedule_user_unique` as the current revision. The database exposes 34 tables including `alembic_version`. The working tree now has an additive `m7_user_read_indexes` migration as the head; it has not been applied. Treat this inspection as the active configured database baseline, not proof that every production deployment has the same schema.

## Tables by domain

| Domain | Tables | Notes |
|---|---|---|
| Identity and configuration | `users`, `settings`, `google_credentials` | `settings` is keyed by a global string key/value; user scoping is embedded in some keys. Credentials are a separate table but secret encryption/rotation and owner constraints require audit. |
| Courses and coursework | `courses`, `assignments`, `assignment_materials`, `assignment_solutions`, `submissions`, `assignment_templates` | Core rows carry `user_id`; external IDs and uniqueness/source semantics need a measured constraint audit. Material file metadata overlaps the document and Drive domains. |
| Timetable and academic records | `timetable_entries`, `class_schedules`, `attendance_records`, `exams`, `quizzes`, `announcements` | Recurring timetable rows and dated schedules are distinct. Portal/manual source ownership and attendance capture freshness need explicit fields/contracts. |
| RAG and study | `documents`, `document_chunks`, `conversations`, `messages`, `message_citations`, `study_plans`, `study_plan_sessions` | New RAG conversation/message family is separate from the older chat family below. `document_chunks.embedding` uses PostgreSQL `vector`. |
| Older chat and agents | `chat_conversations`, `chat_messages`, `agent_runs`, `agent_events`, `browser_automation_jobs` | Potential overlap with `conversations`/`messages`; consumers and row migration must be mapped before consolidation. Agent events are candidates for cursor pagination. |
| Notifications | `notifications`, `notification_preferences`, `notification_templates`, `daily_reports` | Delivery jobs, idempotency, preference ownership, and worker behavior need review. |
| Portal and audit | `portal_sync_jobs`, `change_events` | Portal jobs are already durable; source checkpoints, event retention, and consistency with other job types need review. |

## Full table list

`agent_events`, `agent_runs`, `alembic_version`, `announcements`, `assignment_materials`, `assignment_solutions`, `assignment_templates`, `assignments`, `attendance_records`, `browser_automation_jobs`, `change_events`, `chat_conversations`, `chat_messages`, `class_schedules`, `conversations`, `courses`, `daily_reports`, `document_chunks`, `documents`, `exams`, `google_credentials`, `message_citations`, `messages`, `notification_preferences`, `notification_templates`, `notifications`, `portal_sync_jobs`, `quizzes`, `settings`, `study_plan_sessions`, `study_plans`, `submissions`, `timetable_entries`, `users`.

## Migration gates

1. Map every `Setting` key prefix and its readers/writers before introducing typed replacement tables; keep dual-read compatibility until verified.
2. Map every consumer and identifier relationship for both chat families before moving any rows. Preserve document and conversation IDs through an explicit compatibility plan.
3. Inspect production schema, indexes, constraints, row counts, and data quality separately; this local inventory is not production approval.
4. Add tenant/source constraints and indexes only after detecting and resolving existing duplicate or orphan rows.
5. Generate and inspect Alembic SQL against a copy/snapshot before deployment. Do not use runtime `create_all` for production schema changes.

## Hot read index comparison

The current database has separate user/date/course indexes for the tables below, but no matching composite index for the common scoped ordering/join paths. The proposed additive migration adds composite indexes for assignments by user and due date, materials by user and assignment, dated schedules by user and date, recurring timetable by user/weekday/start time, attendance by user/course, and courses by user/name/id. These are candidates from endpoint query shapes; inspect `EXPLAIN` plans and row counts before applying to a shared deployment.

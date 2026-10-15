# Alembic Migration Strategy

## Migration Order

Migrations must be applied in sequential order. The revision history forms a linear chain:

```
f9eb2b17779e (initial) 
  → a42b98f1e7c3 (add_classroom_work_type)
  → b71d1a0c8f44 (add_recurring_timetable)
  → c8d1a92e4f10 (isolate_classroom_and_browser_jobs)
  → d9f4c2a7b1e6 (merge_recurring_timetable_and_browser_jobs)
  → add_missing_user_id_columns (add user_id to all tables)
  → add_fk_constraints_and_soft_deletes (foreign keys, soft deletes, and dashboard materialized views)
```

## Applying Migrations

### Fresh Database (PostgreSQL)
```bash
cd backend
alembic upgrade head
```

The latest migration creates PostgreSQL materialized views. Use PostgreSQL to apply the complete migration chain; SQLite is not supported for upgrading to `head`.

### Existing Database
```bash
# Check current revision
alembic current

# Upgrade to latest
alembic upgrade head
```

### Downgrade (Rollback)
```bash
# Downgrade one revision
alembic downgrade -1

# Downgrade to specific revision
alembic downgrade <revision_id>
```

## Migration Details

| Revision | Description | Key Changes |
|----------|-------------|-------------|
| `f9eb2b17779e` | Initial migration | Creates all base tables without `user_id` |
| `a42b98f1e7c3` | Add classroom work type | Adds `work_type` column to assignments |
| `b71d1a0c8f44` | Add recurring timetable | Creates `timetable_entries` table |
| `c8d1a92e4f10` | Isolate Classroom data | Adds `user_id` to `google_credentials`, `courses`, `assignments`, `assignment_templates`; creates `browser_automation_jobs` |
| `d9f4c2a7b1e6` | Merge migration | Empty merge of two branch heads |
| `add_missing_user_id_columns` | Multi-user isolation | Adds `user_id` to 15 remaining tables with unique constraints and indexes |
| `add_fk_constraints_and_soft_deletes` | Data integrity and dashboard views | Adds foreign keys and soft-delete columns, then creates PostgreSQL materialized views |

## Important Notes

1. **Never reorder migrations** - The `down_revision` chain must remain intact
2. **Use PostgreSQL** - The latest migration creates PostgreSQL materialized views and cannot be applied to SQLite
3. **Test locally first** - Run `alembic upgrade head` on a copy of production data before deploying
4. **Backup before migrating** - Always backup production database before running migrations
5. **The `add_missing_user_id_columns` migration** is critical for multi-user support - it adds `user_id` to all tables that were missing it, enabling proper data isolation

## Generating New Migrations

```bash
# Auto-generate from model changes
alembic revision --autogenerate -m "description of changes"

# Create empty migration
alembic revision -m "description of changes"
```

## Migration Files Location

All migration files are in `backend/alembic/versions/`. Each file contains `upgrade()` and `downgrade()` functions.

## Configuration

- `alembic.ini` - Main configuration
- `alembic/env.py` - Runtime environment (loads settings, configures database URL)
- Uses `app.core.config.settings` for database URL resolution

## Troubleshooting

### "Multiple head revisions" error
Run `alembic merge heads -m "merge heads"` to create a merge migration.

### "Can't locate revision" error
Check `alembic history` to see all revisions and their order.

### Data migration needed
For complex data migrations, create an empty migration and write custom SQL in `upgrade()` using `op.execute()`.

## CI/CD Integration

The GitHub Actions workflow (`.github/workflows/ci-deploy.yml`) validates migrations on a fresh PostgreSQL service before deployment:
```bash
python -m alembic upgrade head
```

Deployment then applies the validated migrations to production before restarting the API.
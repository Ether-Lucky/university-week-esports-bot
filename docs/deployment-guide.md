# Deployment & Operations Guide

Deployment model: **Local computer → Bot process → Discord API + Supabase (hosted Postgres).** Only the bot is local; the database is hosted on Supabase. The PC needs to be online (reaching Discord and Supabase) while the bot must respond or run automated actions.

## Running
- Foreground: `python -m esports_bot` (see logs live).
- Keep-alive options (pick one, documented for the operator):
  - Leave the terminal open during the event.
  - **NSSM** (Non-Sucking Service Manager) to run as a Windows service that auto-restarts on crash/reboot.
  - Windows Task Scheduler "At log on" + restart-on-failure.
- The bot is **restart-safe**: persistent views re-register, and startup reconciles Discord resources against the DB.

## Backups (critical — DB is source of truth)
- **Supabase-managed:** automatic daily backups / point-in-time recovery via the Supabase dashboard (availability depends on plan — verify yours). This is your primary safety net.
- **Local off-platform:** `/system backup` runs `pg_dump` → `data/backups/esports-<timestamp>.dump` (custom format) for a copy you control. Restore with `pg_restore`.
- **Recommended cadence:** before setup, before cleanup, before updating, and daily during the active event.
- Store at least one copy **off the machine** (encrypted USB / school drive). Backups contain PII — protect them.
- Manual dump anytime: `pg_dump "$MIGRATION_DATABASE_URL" -Fc -f backup.dump` (strip the `+asyncpg` from the URL for the CLI).

## Updating the bot
```bash
git pull                 # or replace files
.venv\Scripts\activate
pip install -e .         # refresh deps
alembic upgrade head     # apply any new migrations
python -m esports_bot
```
Always `/system backup` before updating. Migrations are versioned and forward-only; never edit the DB by hand.

## Restore
- `/system restore <backup-file>` (Head only): runs a safety `pg_dump` first, then `pg_restore --clean` into the Supabase database, then reconciles resources. Confirm prompt required.
- Supabase-side: use the dashboard's PITR/backup restore for a full rollback.
- Manual: `pg_restore --clean --if-exists -d "<direct-url-without-asyncpg>" backup.dump` → restart bot → `/system health`.

## Recovering from failure
| Situation | Recovery |
|---|---|
| Bot crashed | Restart; startup reconcile fixes state; check #log-errors. |
| PC rebooted | Restart bot (or auto via service); no data loss (DB is on Supabase). |
| Internet outage | Bot reconnects to Discord automatically; DB calls retry with backoff; queued deadline transitions run on reconnect/startup. |
| Supabase unreachable / DB error | Bot retries with backoff; write actions fail gracefully with a staff-visible error until DB is back; no partial state (DB-first). |
| DB corrupted / bad data | Restore from Supabase PITR or a `pg_dump` backup; DB is the source of truth. |
| Discord channel/role deleted manually | `/system health` marks MISSING and offers recreation from DB. |
| Setup interrupted | Re-run `/setup confirm`; idempotent — resumes, no duplicates. |
| Cleanup interrupted | Re-run `/system cleanup`; only deletes remaining tracked temp resources. |
| Wrong destructive action | `/event rollback` (state) or restore from backup; audit log shows what happened. |

## Health & observability
- `/system status` — uptime, Discord/DB connectivity, event/state, counts, last DB op, last error.
- `/system health` — resource reconciliation.
- Console + `data/logs/bot.log` for operator-level detail.

## Data hygiene after the event
- Generate exports (`/export all`) and store safely (local files, PII — protect them).
- Screenshots are Discord references (no local files to purge); staff channels holding them are retained until archive.
- `/event archive` — event becomes read-only history (retained in Supabase).

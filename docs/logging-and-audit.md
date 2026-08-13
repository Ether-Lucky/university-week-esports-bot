# Logging & Audit

Two distinct systems:
1. **Audit log (DB)** — `audit_logs` table, the authoritative, queryable, exportable record of every mutation. Independent of Discord.
2. **Operational logs** — Discord staff-log channels (human-readable) + console/file logging (for the operator).

## 1. Audit log (source of truth)
Every service mutation calls:
```python
audit.record(event_id, actor_user_id, action, entity_type, entity_id,
             before=<dict|None>, after=<dict|None>, result="SUCCESS"|"FAILURE", error=None)
```
- `before`/`after` capture the changed fields (JSON), enabling reconstruction.
- Failures are logged too (illegal transitions, permission denials, Discord API errors).
- Never contains secrets or full PII beyond what's needed to identify the entity (store IDs, not raw screenshots).
- Exportable via `/export logs` (see export-specification.md).

Logged actions (non-exhaustive): application submitted/approved/rejected/withdrawn/corrected; team created/renamed/logo-changed/member-joined/kicked/left/leader-changed/disbanded/corrected; recruitment sent/accepted/declined/expired/cancelled; mechanics created/edited/published; tryout configured/rescheduled/started/ended; check-in changes/overrides; match created/started/completed/corrected/cancelled/disputed; champion recorded; export generated; setup run; cleanup executed; staff added/removed; state transitions; command failures.

## 2. Discord staff-log channels
Mapped in `discord_resources` (purpose = `log_*`). The bot mirrors important audit entries to the matching channel as a compact embed:

| Channel | Receives |
|---|---|
| #log-system | setup, event state changes, backups, health/reconcile |
| #log-applications | submit/approve/reject/withdraw/correct |
| #log-teams | create/rename/logo/disband/correct/register |
| #log-members | join/leave/kick/transfer/recruit resolve |
| #log-moderation | disqualifications, admin overrides, corrections |
| #log-commands | every slash command invocation (actor, command, outcome) |
| #log-tryout | checkin, start, reschedule, end, champion |
| #log-errors | exceptions/stack traces (staff-only), API failures |
| #log-exports | export generated (type, rows, file) |

Log embeds include: timestamp (event tz), actor mention + ID, action, entity, short before→after summary, result. PII kept minimal; full detail lives in the DB audit log.

## 3. Console / file logging (operator)
- Python `logging` to console + rotating file `data/logs/bot.log`.
- Levels: INFO for lifecycle/commands, WARNING for recoverable issues (missing resource, DM blocked), ERROR for failures.
- Startup logs: config summary (no secrets), DB path, connected guild, current event/state, reconcile result.
- Useful for the local operator to see health at a glance (supports FR-24 observability).

## 4. Reconstructability requirement
Given only the DB, staff can answer: who approved application X and when; why team Y was disbanded and by whom; what a match result was before a correction; when a champion was recorded. This is guaranteed because `before`/`after` + actor + timestamp are always captured.

# Error Handling & Resilience

## Principles
- **DB is source of truth.** Discord operations are secondary and reconcilable.
- **Fail safe, fail loud (to staff), fail quiet (to users).** Users get friendly messages; staff get detail in `#log-errors`; secrets never leak.
- **Idempotency over rollback.** Where a true transaction across Discord+DB is impossible, record intent + status and make re-runs safe.

## Interaction-level handling
- Every command handler wraps its body; on exception:
  1. Reply to the user with a generic ephemeral error ("Something went wrong — staff notified. (ref: <audit_id>)").
  2. Write an audit FAILURE with the error class + message (no secrets).
  3. Post a detailed embed (with traceback) to `#log-errors`.
- Long operations `defer()` within 3s, then `followup`/edit when done (Discord token limits).

## Categorized failures & responses
| Failure | Detection | Response |
|---|---|---|
| Discord API 429 (rate limit) | discord.py raises | Library backs off; batch ops add pacing; operation resumes. |
| Discord API 403/50013 (missing perms / role too low) | HTTPException | Abort action, tell staff to fix bot role position/permissions; audit FAILURE. |
| Discord API 404 (resource gone) | HTTPException | Mark `discord_resources.status=MISSING`; offer recreation via `/system health`. |
| DM blocked (50007) | HTTPException | Fall back to ephemeral/channel notification. |
| DB unreachable (Supabase/network) | asyncpg/SQLAlchemy error | Retry with exponential backoff + small connection pool; if persistent, surface a staff-visible "database temporarily unavailable" and refuse writes (no partial state — DB-first). Recover automatically when connectivity returns. |
| Illegal state transition | domain `IllegalTransition` | Friendly "can't do that in state X"; audit FAILURE. |
| Validation error | domain validators | Field-specific message to user; no write. |
| Partial setup | status tracking | Re-run resumes from `discord_resources` status. |
| Partial cleanup | status tracking | Re-run deletes only remaining tracked temp resources. |
| Bot restart mid-flow | startup routine | Persistent views re-registered; reconcile; catch-up deadlines. |

## Resource creation pattern (setup, teams)
```
1. INSERT discord_resources row (status=PENDING, discord_id=NULL)  [DB commit]
2. Create the Discord resource
3. UPDATE row (discord_id=<id>, status=CREATED)                    [DB commit]
On failure between 1 and 3: row stays PENDING → re-run finds PENDING rows and
either completes them (if the resource actually exists, matched by purpose) or retries.
```
This makes setup/team-creation **resumable and duplicate-free**.

## Resource deletion pattern (cleanup)
```
1. Mark resource status=DELETING
2. Delete Discord resource (404 treated as success — already gone)
3. Mark status=DELETED (DB history NOT deleted)
```
Cleanup only ever touches rows in `discord_resources` for the current event's temporary resources; never unrelated channels.

## Startup routine
1. Load config (fail fast on bad secrets).
2. Connect to Supabase Postgres (async pool, SSL); run pending-migrations check (warn if not at head); retry/backoff if unreachable.
3. Connect Discord; resolve guild.
4. Load active event; re-register persistent views.
5. Reconcile: verify each CREATED `discord_resources.discord_id` exists; mark MISSING.
6. Catch-up: apply any due deadline transitions (or flag for staff per config).
7. Log a health summary to console + `#log-system`.

## Operator-facing errors
- Config problems (missing token, bad GUILD_ID) → clear console message, no stack noise, no secret echo.
- Community-not-enabled at setup → explicit remediation message, setup aborts cleanly.
- Resource-limit projection exceeded → setup aborts, prints the projected vs allowed numbers.

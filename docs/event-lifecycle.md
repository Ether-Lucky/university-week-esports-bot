# Event Lifecycle

The event is governed by a single state machine. Commands are permitted only in the states listed for them (see `state-machine.md` for the formal transition table and `permissions.md` for authority).

```
DRAFT
  └─ /event create → SETUP
SETUP
  └─ /setup confirm (server built, roles/channels created, config validated) → APPLICATIONS_OPEN
APPLICATIONS_OPEN
  └─ applications open; verification & applying active
  └─ /event advance (or applications_close_at reached) → TEAM_FORMATION
TEAM_FORMATION
  └─ create/join/find teams; recruitment active
  └─ team_creation & recruitment deadlines → REGISTRATION_LOCKED
REGISTRATION_LOCKED
  └─ rosters frozen; teams register; mechanics/challonge finalized
  └─ /tryout validate passes → PRE_TRYOUT
PRE_TRYOUT
  └─ team check-in; final validation
  └─ /tryout start (validation must pass) → TRYOUT_ACTIVE
TRYOUT_ACTIVE
  └─ matches run; battle results recorded; corrections allowed
  └─ /tryout end → RESULTS
RESULTS
  └─ champions selected & announced; exports generated
  └─ /system cleanup (confirmed) → CLEANUP
CLEANUP
  └─ temporary Discord resources deleted; DB preserved
  └─ /event archive → ARCHIVED
ARCHIVED
  └─ read-only; queryable forever; new year = new event record
```

## Phase responsibilities

| State | What's happening | Key commands enabled |
|---|---|---|
| DRAFT | Event record exists, nothing built | /event create, /event configure |
| SETUP | Building Discord structure | /setup, /setup preview/confirm/status |
| APPLICATIONS_OPEN | Members verify + apply; staff review | Apply button, /application approve/reject |
| TEAM_FORMATION | Teams form, recruit | /team *, /recruit *, Join/Find buttons |
| REGISTRATION_LOCKED | Rosters frozen; finalize mechanics/challonge | /mechanics *, tournament config |
| PRE_TRYOUT | Check-in + validation | /tryout checkin, /tryout status |
| TRYOUT_ACTIVE | Matches + results | /match *, /tryout end |
| RESULTS | Champions, exports | champion selection, /export * |
| CLEANUP | Delete temp resources | /system cleanup |
| ARCHIVED | History only | /export *, read queries |

## Deadline enforcement (local-hosting caveat)
Deadlines (`applications_close_at`, `team_creation_deadline`, `recruitment_deadline`) are stored but only *auto-advance* the state when the bot is running. On startup the bot runs a **catch-up** pass: if a deadline has passed, it applies the pending transition (or flags it for staff confirmation, configurable). Staff can always advance manually with `/event advance`.

## Reusability
`ARCHIVED` events are never modified. Starting a new year: `/event create` builds a fresh `events` row (new year), reusing the `games` catalog and, optionally, prior config as a template. No code changes.

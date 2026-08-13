# State Machines

Four machines. Transitions not listed are **illegal** and rejected by the service layer (with an audit FAILURE entry). Staff overrides are explicitly noted; overrides are always logged.

## 1. Event state machine

States: DRAFT, SETUP, APPLICATIONS_OPEN, TEAM_FORMATION, REGISTRATION_LOCKED, PRE_TRYOUT, TRYOUT_ACTIVE, RESULTS, CLEANUP, ARCHIVED

| From | To | Trigger | Guard |
|---|---|---|---|
| DRAFT | SETUP | /event create completes config | valid config |
| SETUP | APPLICATIONS_OPEN | /setup confirm | server built, limits OK, Community verified |
| APPLICATIONS_OPEN | TEAM_FORMATION | /event advance or close deadline | — |
| TEAM_FORMATION | REGISTRATION_LOCKED | /event advance or deadlines | — |
| REGISTRATION_LOCKED | PRE_TRYOUT | /event advance | /tryout validate passes |
| PRE_TRYOUT | TRYOUT_ACTIVE | /tryout start | full validation passes |
| TRYOUT_ACTIVE | RESULTS | /tryout end | tryout in progress |
| RESULTS | CLEANUP | /system cleanup (confirmed) | champions recorded, exports done |
| CLEANUP | ARCHIVED | /event archive | cleanup logged complete |
| any (Head override) | previous state | /event rollback | Head only, logged, guarded |

Rollback allows correcting an accidental advance (e.g., back to TEAM_FORMATION) — Head only, requires reason, audited. Cannot rollback out of ARCHIVED.

## 2. Application state machine

States: PENDING, APPROVED, REJECTED, WITHDRAWN, ASSIGNED_TO_TEAM, DISQUALIFIED

| From | To | Trigger | Guard |
|---|---|---|---|
| (none) | PENDING | applicant submits | valid form, window open, no active dup |
| PENDING | APPROVED | staff approve | staff auth |
| PENDING | REJECTED | staff reject | reason required |
| PENDING | WITHDRAWN | applicant withdraw | own application |
| APPROVED | ASSIGNED_TO_TEAM | joins/creates team | approved + no active team |
| APPROVED | WITHDRAWN | applicant withdraw | own |
| APPROVED | DISQUALIFIED | staff | reason required |
| ASSIGNED_TO_TEAM | APPROVED | leaves/kicked from team | team still valid |
| ASSIGNED_TO_TEAM | DISQUALIFIED | staff | reason |
| REJECTED | PENDING | applicant re-applies (new row) | cooldown (OQ-8) |
Rejected/withdrawn rows are retained; re-apply creates a **new** application row, preserving history.

## 3. Team state machine

States: RECRUITING, FULL, REGISTERED, CHECKED_IN, COMPETING, ELIMINATED, CHAMPION, DISBANDED

| From | To | Trigger | Guard |
|---|---|---|---|
| (none) | RECRUITING | team created | creator approved |
| RECRUITING | FULL | roster reaches size | active members == roster_size |
| FULL | RECRUITING | member leaves/kicked | count < size |
| FULL | REGISTERED | /team register or state=REGISTRATION_LOCKED | full + game requirements |
| RECRUITING/FULL | REGISTERED | staff register | staff override |
| REGISTERED | CHECKED_IN | all members check in | all present or staff override |
| CHECKED_IN | COMPETING | /tryout start | event TRYOUT_ACTIVE |
| COMPETING | ELIMINATED | loses match | match COMPLETED |
| COMPETING | CHAMPION | selected champion at /tryout end | one per game |
| any | DISBANDED | leader/staff disband | leader or staff; logged |
Notes:
- On CHAMPION, the team's members are granted the global **Player** role (OQ-10 — Player = official selected players). This is the only place Player is granted.
- A DISBANDED team's members' applications revert APPROVED (freeing them).
- CHAMPION teams are exempt from cleanup deletion.
- Match voice provisioning at tryout start uses **floor(complete_teams/2)** channels; an odd team out waits (OQ-3).

## 4. Match state machine

States: SCHEDULED, READY, LIVE, COMPLETED, CANCELLED, DISPUTED

| From | To | Trigger | Guard |
|---|---|---|---|
| (none) | SCHEDULED | /match create or auto at tryout start | teams checked in |
| SCHEDULED | READY | both teams present | — |
| READY | LIVE | /match start | event TRYOUT_ACTIVE |
| LIVE | COMPLETED | /match battle-ended | winner set, screenshot |
| COMPLETED | DISPUTED | staff flag | reason |
| DISPUTED | COMPLETED | /match correct | staff + reason; updates result |
| any | CANCELLED | staff cancel | reason |
Corrections never delete the prior result; `match_results.corrected=true` + audit entry records the change.

## Enforcement
`domain/states.py` exposes `can_transition(machine, frm, to) -> bool` and `assert_transition(...)`. Services call it before every write; illegal transitions raise `IllegalTransition`, caught by the cog and shown as a friendly error, and recorded as an audit FAILURE.

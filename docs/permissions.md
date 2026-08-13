# Permissions & Authorization Model

Authorization is enforced at **two layers** for every sensitive action:
1. **Discord layer** — the member holds the required role (checked via stored role IDs in `discord_resources`, not by role name).
2. **Application layer** — `domain/authorization.py` policy confirms the actor is permitted for the specific action + current event state.

Both must pass. A member who can *see* a button must still pass the handler's re-check.

## Role → authority summary

| Role | Authority |
|---|---|
| **E-Sports Head** | Everything. Setup, event lifecycle, all overrides, staff management, cleanup. |
| **E-Sports Committee** | Approve/reject applications, manage/correct teams, mechanics, check-in, matches, exports, tryout run. No destructive setup/cleanup without Head (configurable). |
| **Officer in Charge** | Oversight: review, approve/reject, administrative overrides, corrections. |
| **Faculty in Charge** | Same class as OIC (oversight/overrides). |
| **Player** | **Champions only** (OQ-10). Granted to the winning team's members at `/tryout end`; marks official selected players. Access to champions/player areas. |
| **Applicant** | Apply, create/join/find team, own application/team actions. **Team members compete as Applicant + their Team role** (not as Player). |
| **Audience** | View public channels, listen to Stage. No event mutations. |
| **Unverified** | Only `#verify`. |

Staff class = {Head, Committee, OIC, FIC}. Some actions require **Head only** (marked).

## Command → required authority (see command-specification.md for full list)

| Command | Min authority | State restriction |
|---|---|---|
| /setup, /setup preview/confirm | **E-Sports Head role** (OQ-13; `OWNER_DISCORD_ID` break-glass only) | DRAFT/SETUP |
| /event create/configure | Head | DRAFT/SETUP/APPLICATIONS_OPEN (configure) |
| /event archive | Head | RESULTS/CLEANUP |
| /application approve/reject/view/correct | Staff | APPLICATIONS_OPEN..TEAM_FORMATION |
| /application withdraw | Applicant (own) or Staff | before ASSIGNED lock |
| Apply as Player (button) | Applicant | APPLICATIONS_OPEN + window |
| /team create · Create/Find/Join (buttons) | Applicant (approved) | TEAM_FORMATION |
| /team kick/transfer/rename/logo/disband | Team leader or Staff | ≤ REGISTRATION_LOCKED (leader); Staff anytime |
| /team correct, staff disband/add/remove | Staff | any (logged) |
| /recruit, accept/decline/cancel | Leader (recruit/cancel), targeted applicant (accept/decline) | TEAM_FORMATION |
| /mechanics create/edit/publish | Staff | SETUP..PRE_TRYOUT |
| /tryout status | Staff | any |
| /tryout checkin | Staff (manage) / team member (self check-in) | PRE_TRYOUT |
| /tryout start/end/reschedule | Staff (start/end: Head or Committee) | PRE_TRYOUT / TRYOUT_ACTIVE |
| /match battle-ended/correct/cancel | Staff | TRYOUT_ACTIVE |
| /export * | Staff | any |
| /staff add/remove | **Head** | any |
| /staff list, /system status/health | Staff | any |
| /system backup/restore/cleanup | **Head** | restore/cleanup: guarded + confirm |

## Authorization policy (pseudocode)

```python
def can(actor: Member, action: Action, ctx: EventContext) -> Decision:
    roles = resolve_event_roles(actor, ctx.event)      # via stored role IDs
    if action.requires_head and Role.HEAD not in roles:
        return Deny("requires E-Sports Head")
    if action.staff_only and not (roles & STAFF_ROLES):
        return Deny("staff only")
    if action.owner_scoped and not owns_target(actor, action.target):
        if not (roles & STAFF_ROLES):                  # staff override
            return Deny("not owner")
    if ctx.event.state not in action.allowed_states and not staff_override(actor, roles):
        return Deny(f"not allowed in state {ctx.event.state}")
    return Allow()
```

## Guarantees
- Sensitive commands are **registered with default_member_permissions** (hidden from ordinary users) AND re-checked in code — never rely on UI hiding alone.
- Staff overrides on owner-scoped actions are always audit-logged.
- The bot verifies its own role position is above managed roles before assigning them.

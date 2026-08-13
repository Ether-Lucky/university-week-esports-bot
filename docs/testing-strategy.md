# Testing Strategy

Tooling: **pytest** + **pytest-asyncio**, coverage via **pytest-cov**. Discord calls isolated behind `DiscordResourceService` so services/domain test without a live Discord. DB tests run against a **disposable PostgreSQL** (Docker via `testcontainers`, or a dedicated Supabase *test* project / local `supabase start`) so tests exercise the same engine as production — partial unique indexes and CHECK constraints behave identically. Each test uses a transaction rolled back at teardown (or a fresh schema). Pure-domain unit tests need no DB.

## Test pyramid
- **Unit (most):** pure domain logic — no Discord, no I/O.
- **Integration (some):** services + real (disposable) Postgres + mocked DiscordResourceService.
- **E2E (few):** full lifecycle simulation with a fake Discord layer.

## Unit tests
| Area | Cases |
|---|---|
| Email validation | valid domain, wrong domain, malformed, case-insensitivity, empty |
| URL validation | valid FB hosts, wrong host, non-https, injection attempts |
| Name sanitization | mention injection (@everyone), markdown, control chars, length caps, uniqueness |
| Attachment validation | Discord attachment content-type in {PNG,JPG,WEBP}, oversize rejected, wrong type rejected (no local storage) |
| Logo URL validation | https + allowlisted image host accepted; non-https / bad host / non-image rejected |
| Team capacity | join under/at/over roster size, leader-last-member behavior |
| Team membership | user can't be on two teams, cross-game join blocked, only-approved join |
| State machines | every legal transition allowed; representative illegal transitions rejected (event/app/team/match) |
| Authorization | each command's required authority allow/deny; staff override; state gating |
| Scheduling | `floor(N/2)` channels for N=0,1,2,3,5,8; odd team gets a bye/waits (OQ-3) |
| Verification | external verified-role → Audience grant; role removed → Audience revoke (if enabled) |
| Champion → Player | Player role granted to champion members at tryout end; not before |
| Exports | CSV quoting/escaping, BOM, timestamp formatting, row counts |

## Integration tests
| Area | Cases |
|---|---|
| Repositories | CRUD, partial unique indexes (one active application per user; email/Discord 1:1), FK cascade behavior |
| ApplicationService | submit→pending, approve/reject(reason required), one-active-app-per-user enforcement, history written, audit written |
| TeamService | create (records + resource calls), join guards, kick reverts application, disband frees members |
| TryoutService | validation gate (missing mechanics/challonge blocks start), start creates N voice channels, end records champion + triggers export |
| MatchService | battle-ended saves + publishes, correct sets corrected+audit |
| SetupService | idempotency: interrupt after k of n resources, re-run creates only remainder; limit projection aborts when exceeded |
| Reconcile | MISSING detection when a stored discord_id is absent; recreation |
| Exporter | writes files, populates `exports` table |

## End-to-end (fake Discord)
Simulate the full flow and assert DB + resource-service call effects at each step:
```
Setup → Verify → Apply → Approve → Create team → Recruit → Accept → Team full
→ Register → Check-in → Tryout start (voice channels) → Battle result → Correct
→ Tryout end + champion → Export → Cleanup → Archive
```
Assertions: correct state at each stage, audit entries present, exports non-empty, cleanup deletes only tracked temp resources, DB history preserved after cleanup, event ARCHIVED and still queryable.

## Non-functional checks
- Idempotency: re-running setup/cleanup yields no duplicates and no errors.
- Restart safety: persistent views reconstruct; pending deadline transitions apply on startup.
- Authorization negative tests: ordinary user denied every staff/Head command.
- Privacy: no PII in public-channel payloads (assert on mocked public sends).

## Coverage targets
- Domain layer: ≥ 90%.
- Services: ≥ 80%.
- Overall: ≥ 75%.
- CI (optional/local): `pytest` must pass before a milestone is marked complete.

## Per-milestone gate
Each milestone in `task.md` lists required tests. A milestone is "done" only when its tests pass and its acceptance criteria are demonstrably met.

# Implementation Task Breakdown

Rules: implement **one milestone at a time**. After each: run its tests, verify acceptance criteria, update this file (check boxes), update affected docs, report, and **wait for approval** before the next major milestone.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done. Each task: **ID** — title — deps — acceptance — files — tests.

---

## M0 — Requirements & Specs  `[x]`
- **M0-001** `[x]` Author spec docs — accept: all docs in `docs/` reviewed & approved — files: `docs/*`.
- **M0-002** `[x]` Resolve open questions — accept: `open-questions.md` answered by stakeholder (all 15 + Supabase directive, 2026-08-13).

## M1 — Project Bootstrap  `[x]`
- **BOOT-001** `[x]` `pyproject.toml`, deps (discord.py, SQLAlchemy[asyncio], asyncpg, Alembic, pydantic(-settings), pytest, ruff, black) — accept: `pip install -e ".[dev]"` works ✓ — files: `pyproject.toml`.
- **BOOT-002** `[x]` Config module (Pydantic settings from `.env`) + `.env.example` — accept: bad/missing config fails fast, no secret leak ✓ — files: `src/esports_bot/config.py`, `.env.example`.
- **BOOT-003** `[x]` Logging setup (console + rotating file) — accept: no secrets ✓ — files: `src/esports_bot/logging_setup.py`.
- **BOOT-004** `[x]` Bot skeleton + cog loader + guild command sync + `/system status` stub — files: `bot.py`, `__main__.py`, `cogs/system.py`.
- **BOOT-005** `[x]` `.gitignore` + `README.md` skeleton + smoke tests (pytest 2/2 green, ruff clean) — files: `.gitignore`, `README.md`, `tests/`.
- Layer package skeletons created: `cogs/ services/ domain/ repositories/ infra/ models/`.

## M2 — Database (Supabase Postgres)  `[~]`
- **DB-001** `[x]` Async SQLAlchemy engine (asyncpg, SSL, pool_pre_ping) + `session_scope` + `ping` → Supabase — accept: `ASYNC_PING True` verified — files: `infra/db.py`.
- **DB-002** `[x]` ORM models for all 19 tables; Postgres types (BIGINT/timestamptz/JSONB/Enum+CHECK) — accept: 19/19 tables map cleanly — files: `models/*`, `domain/enums.py`.
- **DB-003** `[x]` Alembic (async-free sync psycopg env) + initial migration; **applied to Supabase** (`alembic_version=4ced0c4116e9`, 20 tables incl. version) — files: `alembic.ini`, `migrations/`.
- **DB-004** `[x]` Constraints & partial indexes — one active app per (event_id, user_id) OQ-4; per email OQ-5; one active team membership per event; CHECK rejection_reason — accept: **verified live** — duplicate active application raises IntegrityError — tests: `tests/integration/test_db_constraints.py`.
- **DB-005** `[x]` Repository layer (core: User/Event/Game/Staff repos) — built in M4 — files: `repositories/core.py` — exercised by EventService integration test.
- **DB-006** `[x]` Audit service (`audit.record`) — writes rows w/ before/after/result — files: `infra/audit.py` — used by every EventService mutation.
- Tests: unit `test_models.py` (metadata/constraints, no DB); integration `test_db_constraints.py` (guarded by `RUN_DB_TESTS=1`). Suite: **7 passed, 1 skipped**; live-DB test **passed**; ruff clean.

## M3 — Discord Bot Foundation  `[~]`
- **DISCORD-001** `[x]` `DiscordResourceService` + `ResourceGateway` Protocol (real `DiscordResourceGateway` wrapping a guild) — accept: idempotent create verified (no duplicate on re-run) — files: `infra/discord_resources.py`, `infra/discord_gateway.py`, `infra/resource_repository.py` — tests: `test_resource_service.py`.
- **DISCORD-002** `[x]` `discord_resources` mapping (`SqlResourceRepository`) + `reconcile()` — accept: MISSING detection + recreate verified with fakes — tests: `test_resource_service.py`.
- **DISCORD-003** `[~]` App-command error handler (fail quiet to users, loud to logs, no secret leak) done in `bot.py`. *Persistent-view base deferred to the first real button (M6/M7); #log-errors channel mirror lands with M16.*
- **DISCORD-004** `[x]` Authorization framework — pure dual-layer policy `evaluate()` + `Action`/`Role`/`Decision` — accept: head/staff/owner/state gating verified — files: `domain/authorization.py` — tests: `test_authorization.py`. *(@check decorator that resolves member→roles wires in at M5 with real roles.)*
- **DISCORD-005** `[x]` State-machine module + guards (event/application/team/match) + rollback helpers — accept: illegal transitions raise `IllegalTransition` — files: `domain/states.py` — tests: `test_states.py`.
- Suite now: **23 passed, 1 skipped**; ruff clean.

## M4 — Setup Wizard  `[x]`
- **SETUP-001** `[x]` Resource-limit projection + Community check — accept: violations flagged; preview blocks when not Community/over limit — files: `domain/limits.py` — tests: `test_limits_and_setup.py`.
- **SETUP-002** `[x]` `/setup preview` (detect, preserve/remove, projection, community, confirm token) — accept: no changes made; preserve/remove logic verified — files: `cogs/setup.py`, `domain/setup_plan.py` — tests: `test_limits_and_setup.py`.
- **SETUP-003** `[x]` `/setup backup` (server structure → JSON) — files: `cogs/setup.py`, `domain/setup_plan.py::serialise_backup`.
- **SETUP-004** `[x]` `/setup confirm` destructive build, **idempotent** + guarded (token + community/limit gate + backup-first) — accept: re-run creates no duplicates (verified with fakes); removal orders children→categories→roles — files: `services/setup_service.py`, `domain/server_blueprint.py` — tests: `test_setup_service.py`. *(Not run against a live server; awaiting operator go-ahead.)*
- **SETUP-005** `[x]` `/event create/configure/advance/status` (`cogs/event.py`) + `/system health` reconcile command (`cogs/system.py`, done in M5) — reports/marks MISSING resources.
- Also built: first repositories (DB-005) + audit service (DB-006); validators (`domain/validators.py`).
- Suite: **39 passed, 2 skipped**; live-DB **2 passed** (EventService create/configure/advance + duplicate guards); ruff clean.

## M5 — Roles & Permissions  `[x]`
- **PERM-001** `[x]` Base roles created + IDs stored (via M4 blueprint); preserved Head role registered as `role_head`; `bot_top_role_position()` available for hierarchy checks.
- **PERM-002** `[x]` Permission-overwrite matrix applied to every channel/category — accept: staff-only hidden from @everyone, apply/forum/players/verify rules enforced — files: `domain/permissions.py`, `services/setup_service.py::apply_permissions`, gateway `set_overwrites` — tests: `test_permissions.py`.
- **PERM-003** `[x]` `/staff add/remove/list` — persists assignment + grants/revokes the Discord role — files: `cogs/staff.py`, `services/staff_service.py` — tests: live-DB `test_staff_service.py`.
- **DISCORD-004 (decorator)** `[x]` Dual-layer authz now wired: `services/authz.py` resolves member→held Roles via stored role IDs; `cogs/checks.py::is_head/is_staff` gate commands — tests: `test_authz_resolution.py`.
- Suite: **49 passed, 3 skipped**; live-DB **3 passed**; ruff clean.

## M6 — Verification (external bot)  `[x]`
- **VERIF-001** `[x]` `on_member_update` → grant/revoke Audience from the external verified role (OQ-2) — `cogs/verification.py`, `domain/verification.py` — tests: `test_verification.py`.

## M7 — Applications  `[x]`
- **APP-001** `[x]` Apply button → game select → 5-input modal — `cogs/applications.py`.
- **APP-002** `[x]` `ApplicationService` submit (validation, one-active-app OQ-4/5, history, audit) — tests: `test_application_service.py` (live).
- **APP-003** `[x]` Review-channel post + `/application approve/reject`(reason) + DM notify w/ fallback + log mirror.
- **APP-004** `[x]` `/application list`; PII ephemeral only. *(view/withdraw/correct: withdraw in service; view/correct commands are follow-ups.)*

## M8 — Teams  `[x]`
- **TEAM-001** `[x]` `/team create` → DB + role + text + voice; logo via validated URL (OQ-7) — `cogs/teams.py`, `services/team_service.py`.
- **TEAM-002** `[x]` `/team join` with all guards (approved, one-team, full, game-match) — tests: `test_team_service.py` (live). *(Forum post + in-forum Join button pending — see CHANGELOG.)*
- **TEAM-003** `[x]` leave/disband/rename/transfer (+ resource teardown on disband); frees members — tests live.
- **TEAM-004** `[~]` staff override on disband/rename/transfer wired; `/team correct` (game change) is a follow-up.

## M9 — Recruitment  `[x]`
- **RECRUIT-001** `[x]` `create_lft_post` (screenshot Discord-ref only, OQ-6) — `services/recruitment_service.py`. *(LFT-forum posting UI pending.)*
- **RECRUIT-002** `[x]` recruit request + accept/decline + expiry — tests: `test_recruitment_service.py` (live).

## M10 — Staff Management  `[x]`
- **STAFF-001** `[x]` Delivered in M5 (authz + `/staff *`, overrides audited).

## M11 — Mechanics & Challonge  `[x]`
- **MECH-001** `[x]` `/mechanics create/publish` + embed builder (limit-safe) — `cogs/mechanics.py`.
- **MECH-002** `[x]` `/tournament set` + publish per game — tests: e2e (live).
- **MECH-003** `[x]` `docs/embed-authoring.md`.

## M12 — Check-in  `[x]`
- **CHECKIN-001** `[x]` `/tryout checkin` + `CheckinService` (team readiness) — `services/checkin_service.py`.

## M13 — Tryout Execution  `[x]`
- **TRYOUT-001** `[x]` `/tryout status` readiness table — `services/tryout_service.py::validate`.
- **TRYOUT-002** `[x]` `/tryout start` → floor(N/2) voice channels, audience excluded — tests: `test_scheduling.py` + e2e.
- **TRYOUT-003** `[~]` reschedule via `/event`+`set_schedule`; dedicated `/tryout reschedule` announcement edit is a follow-up.
- **TRYOUT-004** `[x]` `/tryout crown` (Player role to champions, OQ-10) + `/tryout end` → RESULTS — tests: e2e.

## M14 — Battle Results  `[x]`
- **MATCH-001** `[x]` `/match battle-ended` capture + publish + save — `services/match_service.py`.
- **MATCH-002** `[x]` `/match correct` (corrected flag + audit); cancel/create/start in service — tests: e2e.

## M15 — Exports  `[x]`
- **EXPORT-001** `[x]` CSV exporter (applicants/teams/members/matches/checkins/logs; BOM, RFC-4180) + `exports` table — `infra/exporter.py`.
- **EXPORT-002** `[x]` `/export <kind|all>` (+ zip), delivered ephemerally — tests: e2e (applicants/teams).

## M16 — Logging  `[x]`
- **LOG-001** `[x]` Staff log-channel mirror (`infra/logchannel.py`) wired for applications/teams/cleanup; all actions in DB audit log.
- **LOG-002** `[~]` per-command mirror to #log-commands is a follow-up; command outcomes captured in audit + console.

## M17 — Cleanup & Archive  `[x]`
- **CLEAN-001** `[x]` `/system cleanup` (guarded confirm) disbands non-champions, deletes their + tryout resources, keeps champions + DB — tests: e2e.
- **CLEAN-002** `[x]` `/system archive` → ARCHIVED (queryable) — tests: e2e.
- **CLEAN-003** `[~]` `/system backup/restore` documented (pg_dump/PITR); command wiring is a follow-up.

## M18 — Testing  `[x]`
- **TEST-001** `[x]` Unit suite (states, authz, permissions, validators, limits, scheduling, verification, resource service, setup) — 62 tests.
- **TEST-002** `[x]` Live-DB integration (event/staff/application/team/recruitment services).
- **TEST-003** `[x]` Full e2e lifecycle (`test_e2e_lifecycle.py`) — setup→…→archive.

## M19 — Documentation  `[x]`
- **DOC-001** `[x]` README (quick start, prerequisites, layout) + command reference in `command-specification.md`.
- **DOC-002** `[x]` setup/deployment/embed-authoring docs updated for Supabase + external verification.

## M20 — Release  `[x]`
- **REL-001** `[x]` `CHANGELOG.md`, version 0.1.0, `.env.example` finalized.
- **REL-002** `[~]` Live dry-run on a test Discord server pending operator action (destructive flows not yet run live).

---

## Sample acceptance criteria (Given/When/Then style)

**APP-001 / APP-002**
- Given a verified Audience member, When they press *Apply as Player*, Then the game select + application form opens.
- Given an email not ending in the event domain, When submitted, Then submission is rejected with a clear validation message and nothing is stored.
- Given a valid application, When submitted, Then it is stored PENDING, staff are notified in #application-review, and an audit entry exists.
- Given the user already has ONE active application (any game), When they apply again, Then it is blocked as a duplicate (OQ-4). Same for a school email or Discord account already used by an active application (OQ-5).

**TEAM-002**
- Given a full team, When an applicant presses *Join Team*, Then the join is refused (team full).
- Given an applicant already on a team, When they press *Join Team* on another, Then refused (already on a team).
- Given an applicant for a different game, When they press *Join Team*, Then refused (wrong game).

**TRYOUT-002**
- Given a game with 5 complete checked-in teams, When `/tryout start`, Then floor(5/2)=2 match voice channels are created and 1 team gets a bye/waits (OQ-3), each channel joinable only by the two matched teams' roles + staff, and Audience cannot connect.

**TRYOUT-004 (champion → Player)**
- Given RESULTS with a champion selected for a game, When `/tryout end` completes, Then each champion team member is granted the global **Player** role (OQ-10), and no non-champion holds Player.

**CLEAN-001**
- Given RESULTS state with one champion per game, When `/system cleanup` is confirmed, Then non-champion team roles/channels/voice/forum-posts and tryout voice channels are deleted, champions are preserved, all DB records remain, and unrelated channels are untouched.

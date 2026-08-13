# Architecture

## 1. Technology stack (recommendation)

| Concern | Choice | Why |
|---|---|---|
| Language | **Python 3.11+** | Beginner-friendly, excellent Discord support, easy Windows setup, huge ecosystem. |
| Discord library | **discord.py 2.x** | Mature, well-documented, first-class slash commands / modals / buttons / views, active maintenance. |
| Database | **PostgreSQL via Supabase (hosted)** | Stakeholder directive: only the bot is local; the DB is hosted. Supabase gives managed Postgres with automatic backups, SSL, and a dashboard — no local DB server to run. |
| DB driver | **asyncpg** (via SQLAlchemy async engine) | Non-blocking DB I/O that fits discord.py's asyncio loop; connects to Supabase's Postgres endpoint. |
| ORM | **SQLAlchemy 2.x (async)** | Robust, typed; async engine over asyncpg. Alembic for migrations against the Supabase database. |
| Migrations | **Alembic** | Versioned schema changes; safe upgrades between years. |
| Config validation | **Pydantic v2** | Validates `.env` + event config; clear error messages. |
| Testing | **pytest** + **pytest-asyncio** | Async-friendly unit/integration tests. |
| Lint/format | **ruff** + **black** | Consistency for future maintainers. |

### ADR-001 — Python + discord.py over TypeScript/discord.js
Both are viable. Python chosen for lower barrier to entry for student maintainers, simpler local tooling on Windows, and readable code. discord.py covers every needed primitive (app commands, modals, views, forums, stages).

### ADR-002 — PostgreSQL on Supabase (revised per stakeholder directive)
Original recommendation was local SQLite; the stakeholder directed that **only the bot is local and the database must be hosted on Supabase**. Decision: **PostgreSQL hosted on Supabase**, reached over SSL via the async SQLAlchemy engine (asyncpg) using the project's connection string (stored in `.env` as `DATABASE_URL`). Consequences:
- **Backups:** Supabase provides automatic/point-in-time backups (plan-dependent); we additionally support `/system backup` via `pg_dump` to a local file for off-platform copies.
- **Availability:** the bot now requires internet connectivity to reach both Discord **and** Supabase. DB connectivity failures are treated as recoverable network errors (retry/backoff) — see `error-handling.md`.
- **Access model:** the bot connects with the Supabase Postgres service credentials (direct connection / connection pooler), **not** the anon/public API key. Row-Level Security is not required because access is a single trusted service account; RLS may be left off or set to deny-all for the anon role. The Supabase JS/anon API is not used.
- **Concurrency & constraints:** Postgres natively supports partial unique indexes, CHECK constraints, and (if needed) exclusion constraints — used to enforce data-integrity rules at the DB layer.
- We use the **connection pooler** endpoint (PgBouncer, transaction mode) for resilience; migrations run against the direct connection.

### ADR-003 — Challonge as external link, no API (v1)
The brief says not to assume Challonge API integration. Brackets are managed in Challonge's UI; the bot only stores and publishes the per-game URL. Rationale: avoids an external API dependency/credential, keeps the bot resilient offline, matches scope. Revisit if auto-sync of results is later required.

### ADR-004 — DB is source of truth; Discord is a projection
Every Discord resource maps to a DB row (`discord_resources`). The bot never infers state from channel names. It can reconcile/recreate Discord resources from the DB (`/system health`). See Product Principle §48 of the brief.

## 2. Layered architecture

```
┌─────────────────────────────────────────────┐
│  Discord Interface (cogs)                     │  discord.py cogs, slash commands,
│  buttons, modals, views, event listeners      │  buttons, modals — thin, no business logic
├─────────────────────────────────────────────┤
│  Application / Service Layer                  │  use-cases: ApplicationService,
│  (orchestration, authorization, transactions) │  TeamService, TryoutService, SetupService…
├─────────────────────────────────────────────┤
│  Domain Layer                                 │  entities, value objects, state machines,
│  (pure logic, no Discord, no DB)              │  validation rules, authorization policy
├─────────────────────────────────────────────┤
│  Repository Layer                             │  data access; one repo per aggregate
├─────────────────────────────────────────────┤
│  Infrastructure                               │  Supabase Postgres/SQLAlchemy, DiscordResourceService,
│                                               │  FileStorage, config, logging, exporter
└─────────────────────────────────────────────┘
```

**Rules**
- Cogs contain **no business logic** — they parse the interaction, call a service, and render the result.
- Services own transactions, authorization checks, and audit logging.
- Domain layer is **pure** (unit-testable without Discord or a DB): email/URL validation, roster rules, state-transition legality, scheduling math, authorization policy.
- **All Discord resource create/delete/edit goes through `DiscordResourceService`** so it can be mocked in tests and reconciled against the DB.

## 3. Proposed source layout

```
esports/
├── docs/                      # all specs (this folder)
├── .env.example
├── README.md
├── pyproject.toml
├── alembic.ini
├── migrations/                # Alembic (runs against Supabase Postgres)
├── data/                      # runtime: exports, db backups, logs (gitignored)
│   ├── exports/
│   ├── backups/               # pg_dump output
│   └── logs/
├── src/esports_bot/
│   ├── __main__.py            # entrypoint: load config, start bot
│   ├── bot.py                 # Bot subclass, cog loading, startup reconcile
│   ├── config.py              # Pydantic settings from .env
│   ├── cogs/                  # Discord interface
│   │   ├── setup.py
│   │   ├── event.py
│   │   ├── verification.py
│   │   ├── applications.py
│   │   ├── teams.py
│   │   ├── recruitment.py
│   │   ├── tryout.py
│   │   ├── mechanics.py
│   │   ├── matches.py
│   │   ├── exports.py
│   │   ├── staff.py
│   │   └── system.py
│   ├── services/              # application layer
│   ├── domain/                # entities, state machines, policies, validators
│   │   ├── states.py          # event/team/application/match state machines
│   │   ├── authorization.py   # role→permission policy
│   │   ├── validators.py      # email, url, file, name sanitization
│   │   └── scheduling.py      # floor(N/2) match channels, bye handling
│   ├── repositories/
│   ├── infra/
│   │   ├── db.py              # async engine/session → Supabase Postgres (asyncpg, SSL)
│   │   ├── discord_resources.py
│   │   ├── exporter.py        # CSV exports (screenshots referenced as Discord URLs)
│   │   └── audit.py
│   └── models/                # SQLAlchemy ORM models
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

## 4. Cross-cutting concerns

- **Authorization:** every command passes through a decorator/check that verifies (1) Discord role membership via stored role IDs and (2) application-level policy in `domain/authorization.py`. Both must pass. See `permissions.md`.
- **Audit:** services call `audit.record(actor, action, entity, before, after, result)` for every mutation. See `logging-and-audit.md`.
- **Idempotency:** setup/cleanup/team-creation record intent + status so re-runs reconcile. See `error-handling.md`.
- **State enforcement:** services check the event state machine before allowing an action. See `state-machine.md`.
- **Config-driven:** no year/game/role/date is hard-coded; all read from DB (`events`, `games`, `discord_resources`).

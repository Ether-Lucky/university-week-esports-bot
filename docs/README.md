# Specification Index — University Week E-Sports Discord Bot

Spec-driven project. **Implementation is blocked until this spec is reviewed and approved.**

## Read in this order
1. [requirements.md](requirements.md) — scope, functional & non-functional requirements, out-of-scope, assumptions.
2. [open-questions.md](open-questions.md) — **decisions needed from you** (each has a recommended default).
3. [constraints.md](constraints.md) — platform / legal / hosting / tech constraints.
4. [discord-limitations.md](discord-limitations.md) — Discord limits + mitigations + brief conflicts resolved.
5. [architecture.md](architecture.md) — tech stack, ADRs, layered architecture, source layout.
6. [database-design.md](database-design.md) — tables, relationships, constraints, backup.
7. [discord-server-design.md](discord-server-design.md) — channels, roles, permission overwrite matrix.
8. [permissions.md](permissions.md) — dual-layer authorization model.
9. [command-specification.md](command-specification.md) — full slash-command set + components.
10. [event-lifecycle.md](event-lifecycle.md) — end-to-end phase flow.
11. [state-machine.md](state-machine.md) — event/application/team/match state machines.
12. [security.md](security.md) — secrets, validation, file uploads, PII/privacy.
13. [logging-and-audit.md](logging-and-audit.md) — DB audit + Discord staff logs.
14. [export-specification.md](export-specification.md) — CSV formats & fields.
15. [error-handling.md](error-handling.md) — resilience, idempotency, recovery patterns.
16. [setup-guide.md](setup-guide.md) — first-time & yearly setup (Windows).
17. [deployment-guide.md](deployment-guide.md) — running, backups, updates, recovery.
18. [testing-strategy.md](testing-strategy.md) — unit/integration/e2e + gates.
19. [task.md](task.md) — milestone task breakdown (M0–M20) with acceptance criteria.

## Core decisions at a glance
- **Stack:** Python 3.11+ · discord.py 2.x · **PostgreSQL on Supabase** + async SQLAlchemy 2.x (asyncpg) · Alembic · Pydantic · pytest.
- **Hosting:** only the **bot** runs locally (Windows); the **database is hosted on Supabase**.
- **Principle:** database is the source of truth; Discord resources are a reconcilable projection.
- **Reusable:** no year/game/role/date hard-coded; new year = new `events` record, no code changes.
- **Prerequisites:** Discord server **Community-enabled** (Forums + Stages); a **Supabase project**; an **external verification bot** (OQ-2).
- **Key rules (from resolved OQs):** one active application per user (OQ-4); email/Discord 1:1 (OQ-5); screenshots = Discord refs only (OQ-6); team logo = URL (OQ-7); `floor(N/2)` match channels (OQ-3); **Player role = champions**, granted at tryout end (OQ-10); setup run by **E-Sports Head** role (OQ-13).

## Status
- M0 specs authored; **all 15 open questions resolved** + Supabase directive applied ([open-questions.md](open-questions.md)).
- Awaiting your final approval of the spec set.
- On approval: implement **one milestone at a time**, test, verify, update docs, report, then pause for approval before the next.

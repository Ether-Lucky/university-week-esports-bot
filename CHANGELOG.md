# Changelog

## 0.1.0 — Initial implementation (unreleased)

Spec-driven build of the University Week E-Sports Discord bot. All milestones
M0–M20 implemented; service layer verified against a live Supabase Postgres.

### Milestones
- **M0** Specification set (`docs/`) + open-question resolutions.
- **M1** Project bootstrap: config, logging, bot skeleton, `/system status`.
- **M2** Database: 19 SQLAlchemy models, Alembic migration applied to Supabase,
  partial unique indexes + CHECK constraints (verified live).
- **M3** Foundation: state machines, authorization policy, `DiscordResourceService`
  (idempotent create + reconcile), interaction error handler.
- **M4** Setup wizard: `/event create/configure/advance/status`, `/setup preview/backup/confirm`
  (guarded, idempotent), resource-limit projection, Community check, audit service.
- **M5** Roles & permissions: overwrite matrix applied to all channels, `/staff add/remove/list`,
  dual-layer role-based authorization, `/system health` reconcile.
- **M6** Verification: external verified-role → Audience (`on_member_update`).
- **M7** Applications: apply button → game select → modal; `/application approve/reject/list`;
  validation, one-active-application enforcement, history, DM notifications.
- **M8** Teams: `/team create/join/leave/view/disband`; role + channel provisioning; guards.
- **M9** Recruitment: `/recruit player/accept/decline`; expiring requests.
- **M10** Staff management (delivered in M5).
- **M11** Mechanics & Challonge: `/mechanics create/publish`, `/tournament set`.
- **M12** Check-in: `/tryout checkin`.
- **M13** Tryout execution: `/tryout status/start/crown/end`; floor(N/2) voice provisioning;
  champion → Player role.
- **M14** Battle results: `/match battle-ended/correct`.
- **M15** Exports: `/export <kind|all>` — CSV (UTF-8 BOM, RFC-4180) + zip.
- **M16** Logging: staff log-channel mirror for key actions (audit DB is source of truth).
- **M17** Cleanup & archive: `/system cleanup` (guarded), `/system archive`; DB history preserved.
- **M18** Testing: 62 unit tests + live-DB integration incl. full lifecycle e2e.
- **M19** Documentation: specs, setup/deployment guides, embed-authoring guide.
- **M20** Release prep: this changelog; version 0.1.0.

### Notes / follow-ups
- Team Forum posts and the in-forum **Join** button are not yet implemented (join via
  `/team join <id>`); Find-a-Team screenshot upload flow is service-ready, UI pending.
- Review Approve/Reject buttons post as info; staff use `/application approve|reject`
  (restart-safe). Log-channel mirroring wired for high-value actions; remaining actions
  still fully captured in the DB audit log.
- Destructive flows (`/setup confirm`, `/system cleanup`) verified against fakes/live-DB,
  not yet run against a production Discord server.

# Requirements — University Week E-Sports Discord Bot

> Status: Draft for review · Spec-driven (implementation blocked until approval)
> Source of truth for scope. Where this document and the original brief disagree, this document wins **after** approval.

---

## 1. Purpose

A **reusable**, **configuration-driven** Discord bot that manages the full lifecycle of a university's annual University Week E-Sports tryout/tournament event: applications, verification, teams, recruitment, tryout logistics, matches, results, champions, exports, and cleanup — while preserving all historical data in a local database.

The bot runs **locally** (operator's Windows PC), connects to Discord via the Discord API, and uses a **local database as the source of truth**. Discord resources are operational *representations* of database entities, never the other way around.

## 2. Actors / Roles

| Actor | Description |
|---|---|
| **E-Sports Head** | Highest event authority (pre-existing role, preserved by setup). Full bot authority. |
| **E-Sports Committee** | Student staff. Approve/reject applications, manage teams, run tryouts. |
| **Officer in Charge (OIC)** | Staff oversight. Review + administrative overrides. |
| **Faculty in Charge (FIC)** | Faculty oversight. Review + administrative overrides. |
| **Player** | Verified applicant assigned to a team. |
| **Applicant** | Verified member with an approved (or pending) application, not yet on a team. |
| **Audience** | Verified member, spectator only. |
| **(Unverified member)** | New join; no event role until verification. |

## 3. Functional Requirements (numbered, testable)

### FR-1 Initial Server Setup (destructive, guarded)
- **FR-1.1** Setup is invocable only by E-Sports Head (or Discord Administrator during first-run bootstrap).
- **FR-1.2** Setup MUST detect current server config and present a **preview** of what will be preserved vs removed. No destruction before explicit confirmation.
- **FR-1.3** Setup MUST warn that it is destructive and require an explicit confirm step (button + typed confirmation token).
- **FR-1.4** Setup MUST export/back up existing server structure (channels, categories, roles, permission overwrites) to a JSON file before destructive changes.
- **FR-1.5** Preserved resources: the Announcement channel, a designated Text-channel category and its channels, and the E-Sports Head role.
- **FR-1.6** Setup MUST create roles: E-Sports Committee, Officer in Charge, Faculty in Charge, Applicant, Audience, Player.
- **FR-1.7** All created Discord resource IDs MUST be persisted in `discord_resources`.
- **FR-1.8** Setup MUST be **idempotent/resumable**: re-running after partial completion reconciles against `discord_resources` rather than duplicating.
- **FR-1.9** Setup MUST validate Discord resource limits (roles, channels, categories, channels/category) **before** any creation and abort with an explanation if exceeded.

### FR-2 Event Configuration
- **FR-2.1** A setup wizard captures: event name, year, school name, school email domain, timezone, games (with required roster size each), tryout date/time, application open/close date/time, team-creation deadline, recruitment deadline, and cleanup policy.
- **FR-2.2** Any number of games is supported, subject to Discord limits (validated).
- **FR-2.3** No event attribute may be hard-coded; all live in the database.
- **FR-2.4** Creating a new yearly event MUST create a new `events` row, never overwrite a prior one.

### FR-3 Per-Game Structure
- **FR-3.1** Each configured game gets a dedicated category with a defined channel set (see `discord-server-design.md`).
- **FR-3.2** Visibility/interaction enforced via Discord permission overwrites, backed by DB role mapping.

### FR-4 Verification (OQ-2: third-party verification bot)
- **FR-4.1** New members receive no event role.
- **FR-4.2** Anti-bot verification is handled by an **external verification/captcha bot** that assigns a configured "verified" role. Our bot watches for that role (config `VERIFIED_SOURCE_ROLE_ID`) on a member and then grants **Audience**. Our bot does not implement the captcha itself.
- **FR-4.3** The bot MUST NOT auto-assign Applicant/Player. (Player is reserved for champions — FR-18.)
- **FR-4.4** If the external verified role is removed from a member, the bot may revoke Audience (configurable).

### FR-5 Player Application
- **FR-5.1** An application channel shows a bot message + **Apply as Player** button opening a game-aware modal form.
- **FR-5.2** Captured: first name, full name, middle initial, school email, Facebook URL, year & section, game, Discord user ID, Discord username/display name.
- **FR-5.3** School email MUST end with the configured domain (validated).
- **FR-5.4** Facebook URL MUST be validated (scheme + host allowlist).
- **FR-5.5** A user may have only **one active application per event total** (across all games) — OQ-4. School email and Discord account are each bound 1:1 to the active application (OQ-5). Duplicates are prevented by DB constraints (see data integrity).
- **FR-5.6** Applications open only while event state = APPLICATIONS_OPEN (and within open/close window).

### FR-6 Application Review
- **FR-6.1** Applications post to a staff-only review channel visible to Committee/OIC/FIC.
- **FR-6.2** Staff can Approve or Reject; Reject REQUIRES a reason.
- **FR-6.3** States: PENDING, APPROVED, REJECTED, WITHDRAWN, ASSIGNED_TO_TEAM, DISQUALIFIED. All transitions recorded in `application_history`.
- **FR-6.4** Applicant notified of result (DM, with channel-fallback if DMs closed).
- **FR-6.5** Rejected/withdrawn applications are retained (never deleted).

### FR-7 Teams
- **FR-7.1** Approved applicants can Create a Team or Find a Team.
- **FR-7.2** Create-team captures team name, logo **URL** (validated; no upload — OQ-7), game; creator becomes leader.
- **FR-7.3** Creating a team creates: DB record, Discord role, team text channel, team voice channel (all under the game category), and a Team Forum post.
- **FR-7.4** Team management (leader): leave (if valid), kick, transfer leadership, disband, rename, change logo, view roster/status.
- **FR-7.5** Staff overrides: disband any team, add/remove members, transfer leadership, correct info, change game (correction) — all logged.
- **FR-7.6** Team states: RECRUITING, FULL, REGISTERED, CHECKED_IN, COMPETING, ELIMINATED, CHAMPION, DISBANDED (see `state-machine.md`).

### FR-8 Team Forum & Joining
- **FR-8.1** Each game has a public Team Forum viewable by Audience/Applicant/Player/Staff.
- **FR-8.2** Each post shows team name, game, logo, leader, roster, required size, current count, status.
- **FR-8.3** A team-less approved applicant can **Join Team** if not full.
- **FR-8.4** Guards: no user on two active teams; no exceeding roster size; no cross-game joining; only approved applicants; only during permitted states.

### FR-9 Find-a-Team / Recruitment
- **FR-9.1** Find-a-Team form captures IGN, main role/position, game, game-profile screenshot, statistics screenshot; posts to the game's recruitment forum.
- **FR-9.2** A leader can **Recruit Player**, sending a request the player must Accept/Decline.
- **FR-9.3** Recruitment requests expire after a configurable timeout.

### FR-10 Tryout Configuration & Mechanics
- **FR-10.1** Staff configure tryout date/time/timezone, per-game Challonge URL, mechanics, registration/check-in deadlines.
- **FR-10.2** Changing tryout date/time updates the published announcement.
- **FR-10.3** Each game has a mechanics channel. Staff can create/edit/replace/view mechanics, displayed as a clean embed. Mechanics are REQUIRED before tryout can begin.

### FR-11 Challonge
- **FR-11.1** Challonge treated as an external link only (no API integration in v1). Configured per game; published to the game's tournament channel. (See ADR in `architecture.md`.)

### FR-12 Pre-Tryout Validation
- **FR-12.1** `/tryout status` reports per game: mechanics present, Challonge present, complete-team count, date configured — and an overall READY/NOT READY.
- **FR-12.2** Tryout cannot start unless all required items exist for every game.

### FR-13 Check-in
- **FR-13.1** Team check-in system with staff view of team readiness (n/size).
- **FR-13.2** Defined handling for: player no-show, incomplete team, team withdrawal, staff override, ineligibility.

### FR-14 Tryout Start
- **FR-14.1** On start, per game: count complete checked-in teams, compute match voice channels = **floor(complete_teams / 2)** (OQ-3). With an odd count, the leftover team gets a **bye and waits** (no channel this round). Example: 5 teams → floor(5/2)=2 voice channels, 1 team waits.
- **FR-14.2** Match voice channels joinable only by relevant team/player roles + staff; Audience excluded.

### FR-15 Stage Channel
- **FR-15.1** Optional per-game/event Stage channel for audience viewing; requires Community-enabled server (validated at setup).

### FR-16 Battle Results
- **FR-16.1** `/match battle-ended` captures game, team A, team B, winner, result screenshot, optional notes; publishes to the game's Battle Results channel and saves to DB.
- **FR-16.2** Match states: SCHEDULED, READY, LIVE, COMPLETED, CANCELLED, DISPUTED.

### FR-17 Disputes & Corrections
- **FR-17.1** `/match correct` requires staff permission + reason, updates DB, updates public result if needed, writes an audit entry. Results are correctable, never permanently immutable.

### FR-18 Tryout End & Champion
- **FR-18.1** `/tryout end` validates tryout is in progress, asks staff to pick a champion per game, then: records champion, marks team CHAMPION, **grants the global Player role to the champion team's members** (OQ-10 — Player = official selected players/champions), announces, thanks participants, exports applicant/team/result data, preserves history, transitions to RESULTS (cleanup is a separate confirmed step — OQ-9).

### FR-19 Exports (CSV)
- **FR-19.1** Provide CSV exports: applicants, teams, team members (normalized), battle results, check-ins, audit logs. Excel-compatible (UTF-8 BOM, RFC-4180 quoting). Field lists per `export-specification.md`.

### FR-20 Cleanup
- **FR-20.1** Per configured policy, disband non-winning teams and delete their temporary Discord resources (role, text, voice, forum post) plus tryout-specific temporary channels.
- **FR-20.2** NEVER delete DB history because Discord resources are removed.
- **FR-20.3** Cleanup is logged and MUST NOT touch unrelated Discord resources.

### FR-21 Archiving
- **FR-21.1** After cleanup, event → ARCHIVED and remains queryable. Future events create new records.

### FR-22 Staff Logging
- **FR-22.1** Dedicated staff-only log channels: system, applications, teams, members, moderation, commands, tryout, errors, exports. Important actions are logged with enough detail to reconstruct events.

### FR-23 Commands & Permissions
- **FR-23.1** Full slash-command system (see `command-specification.md`) with a strict authorization model checked at both Discord-role and application level.

### FR-24 Observability
- **FR-24.1** `/system status` reports uptime, Discord/DB connection, current event + state, counts (applicants/approved/teams/complete teams/active matches), last successful DB op, last error.

## 4. Non-Functional Requirements

- **NFR-1 Reusability:** zero code changes to run a new year; all via config/DB.
- **NFR-2 Reliability & idempotency:** operations survive restarts and partial failures; safe to re-run.
- **NFR-3 Security & privacy:** student PII protected; token never committed; input/URL/file validation.
- **NFR-4 Maintainability:** clean layered architecture; next year's operator may not be the author.
- **NFR-5 Local-first:** single-machine Windows deployment; online only when acting.
- **NFR-6 Simplicity:** maintainable monolith; no cloud/microservice/queue infrastructure.
- **NFR-7 Auditability:** every administrative mutation produces an audit record.

## 5. Explicitly Out of Scope (v1)

- Challonge API integration (link only).
- Cloud hosting / high availability.
- Web dashboard / frontend app.
- Multi-guild (one server per running bot instance) — see OQ.
- Automated bracket generation / match scheduling beyond round-1 voice channel provisioning.
- Payment, ticketing, or non–E-Sports University Week activities.

## 6. Assumptions

- One bot instance manages one Discord guild at a time (OQ-1).
- The operator holds the pre-existing **E-Sports Head** role (preserved by setup) to bootstrap and run `/setup` (OQ-13). Administrator is needed once to invite the bot and to create/enable Community.
- Exactly one **active** (non-archived) event per guild at a time; archived events coexist.
- **Database is hosted on Supabase (Postgres); only the bot runs locally.** The operator provisions a Supabase project and supplies its connection string.
- Verification is provided by an **external verification bot**; our bot maps its verified role to Audience (OQ-2).
- Screenshots are retained as **Discord attachment references only** (no local copies); team logos are URLs (OQ-6/OQ-7).

See `open-questions.md` for items needing your decision and `constraints.md` for platform limits.

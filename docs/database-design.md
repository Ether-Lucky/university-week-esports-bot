# Database Design

**Engine:** PostgreSQL hosted on **Supabase**, accessed via async SQLAlchemy 2.x (asyncpg, SSL), versioned with Alembic.
**Principles:** stable internal PKs (`BIGINT GENERATED ALWAYS AS IDENTITY`, or UUID); Discord snowflake IDs stored as data (`BIGINT` or `TEXT`), never as primary business identity; foreign keys enforced; soft-state via status columns, hard history retained.

> Types: Discord snowflakes → `BIGINT` (fit in 64-bit) or `TEXT`; timestamps → `timestamptz` stored in **UTC**, displayed in the event timezone; enums → Postgres `ENUM` types or `TEXT` + `CHECK`; JSON payloads (config, audit before/after, mechanics body) → `JSONB`. Postgres natively supports **partial unique indexes**, `CHECK`, and exclusion constraints — data-integrity rules are enforced in the DB, not only the service layer.
>
> Access: the bot connects with Supabase Postgres **service credentials** via the connection pooler (transaction mode) for runtime and the direct connection for migrations. The Supabase anon/REST API is not used; RLS may be deny-all for anon.

## Entity overview

```
events 1───* event_games *───1 games
events 1───* applications *───1 games
events 1───* teams *───1 games
teams  1───* team_members *───1 users
applications *───1 users
teams  1───* matches ... (matches reference two teams + winner)
matches 1───1 match_results
teams  1───* checkins *───1 users
event_games 1───* mechanics (current + history)
event_games 1───1 tournaments (challonge link)
* ───ownership─── discord_resources (polymorphic map)
* ───audit─── audit_logs
events 1───* exports
events 1───* staff_assignments *───1 users
applications 1───* application_history
recruitment_posts 1───* recruitment_requests
```

## Tables

### events
| col | type | notes |
|---|---|---|
| id | PK | internal |
| guild_id | TEXT | Discord guild |
| name | TEXT | e.g. "University Week E-Sports" |
| year | INT | |
| school_name | TEXT | |
| email_domain | TEXT | e.g. uphsl.edu.ph |
| timezone | TEXT | IANA, e.g. Asia/Manila |
| state | TEXT | event state machine (DRAFT…ARCHIVED) |
| applications_open_at / applications_close_at | TEXT | UTC |
| team_creation_deadline / recruitment_deadline | TEXT | UTC |
| tryout_at | TEXT | UTC |
| cleanup_policy | TEXT | JSON (what to delete) |
| created_at / updated_at | TEXT | |

Constraint: at most one event per `guild_id` with `state != 'ARCHIVED'` (enforced in service + partial unique index).

### games (catalog, reusable across years)
| id PK | name | short_code | default_roster_size |

### event_games (per-event game config)
| id PK | event_id FK | game_id FK | roster_size | challonge_url | tryout_at (override) | stage_enabled BOOL | UNIQUE(event_id, game_id) |

### users (one row per Discord user seen)
| id PK | discord_user_id TEXT UNIQUE | discord_username | discord_display_name | first_seen_at |
Business identity is `id`; Discord ID is an attribute.

### applications
| col | type | notes |
|---|---|---|
| id | PK | |
| event_id | FK | |
| game_id | FK | |
| user_id | FK → users | |
| first_name, full_name, middle_initial | TEXT | sanitized |
| school_email | TEXT | validated against event.email_domain |
| facebook_url | TEXT | validated |
| year_section | TEXT | |
| status | TEXT | PENDING/APPROVED/REJECTED/WITHDRAWN/ASSIGNED_TO_TEAM/DISQUALIFIED |
| rejection_reason | TEXT | required when REJECTED |
| reviewed_by | FK → users | staff |
| team_id | FK → teams NULL | |
| created_at / updated_at | | |

Partial unique indexes (OQ-4/OQ-5), all over rows where status in (PENDING, APPROVED, ASSIGNED_TO_TEAM):
- one **active** application per **(event_id, user_id)** — a user may have only ONE active application total, regardless of game (OQ-4);
- unique **(event_id, school_email)** — email bound to one active application;
- unique **(event_id, discord_user_id via user_id)** — one Discord account ↔ one active application (OQ-5).
`game_id` is still recorded on the application (which game they applied for).

### application_history (immutable audit of state changes)
| id PK | application_id FK | from_status | to_status | reason | actor_user_id | created_at |

### teams
| col | type | notes |
|---|---|---|
| id | PK | |
| event_id FK / game_id FK | | |
| name | TEXT | sanitized; UNIQUE(event_id, game_id, name) |
| logo_url | TEXT | validated image URL (OQ-7) — no upload; used as forum thumbnail |
| leader_user_id | FK → users | |
| status | TEXT | RECRUITING/FULL/REGISTERED/CHECKED_IN/COMPETING/ELIMINATED/CHAMPION/DISBANDED |
| roster_size | INT | copied from event_games at creation |
| created_at / updated_at / disbanded_at | | |

### team_members
| id PK | team_id FK | user_id FK | role_in_team TEXT (LEADER/MEMBER) | joined_at | left_at NULL | active BOOL |
Partial unique index: a user may have only one `active` team membership per (event_id) — enforced via service + index on active rows. UNIQUE(team_id, user_id, active).

### recruitment_posts (Find-a-Team profiles)
| id PK | event_id FK | game_id FK | user_id FK | ign | main_role | profile_screenshot_url | stats_screenshot_url | status TEXT (OPEN/CLOSED) | forum_post_id TEXT | created_at |

Screenshots (OQ-6): stored as **Discord attachment references only** — the uploaded image's Discord CDN URL plus `(channel_id, message_id, attachment_id)`. No local copy, no BLOB. Validation of type/size is done on the uploaded Discord attachment before accepting.

### recruitment_requests
| id PK | recruitment_post_id FK NULL | team_id FK | target_user_id FK | requested_by FK | status TEXT (PENDING/ACCEPTED/DECLINED/EXPIRED/CANCELLED) | expires_at | created_at | resolved_at |

### matches
| id PK | event_id FK | game_id FK | round INT NULL | team_a_id FK | team_b_id FK NULL (bye) | winner_team_id FK NULL | status TEXT (SCHEDULED/READY/LIVE/COMPLETED/CANCELLED/DISPUTED) | voice_channel_ref TEXT NULL | created_at/updated_at |

### match_results
| id PK | match_id FK UNIQUE | winner_team_id FK | screenshot_ref | notes | reported_by FK | corrected BOOL | correction_reason | created_at/updated_at |

### checkins
| id PK | event_id FK | game_id FK | team_id FK | user_id FK | state TEXT (CHECKED_IN/NOT_CHECKED_IN/EXCUSED/OVERRIDDEN) | actor_user_id NULL | created_at/updated_at | UNIQUE(team_id, user_id) |

### mechanics
| id PK | event_game_id FK | version INT | title | body (JSON: sections/fields) | published BOOL | created_by FK | created_at | (keep all versions; latest published is current) |

### tournaments
| id PK | event_game_id FK UNIQUE | challonge_url | published_message_ref TEXT | updated_by FK | updated_at |
(Challonge is a link; see ADR-003.)

### discord_resources (polymorphic map — the reconciliation backbone)
| id PK | event_id FK | resource_type TEXT (ROLE/CATEGORY/TEXT_CHANNEL/VOICE_CHANNEL/FORUM_CHANNEL/STAGE_CHANNEL/FORUM_POST/MESSAGE) | discord_id TEXT | owner_type TEXT (EVENT/GAME/TEAM/SYSTEM/LOG) | owner_id INT NULL | purpose TEXT (e.g. 'team_text','game_category','log_applications') | status TEXT (PENDING/CREATED/DELETED/MISSING) | created_at/updated_at |
Index on (event_id, owner_type, owner_id, purpose). This is how the bot finds resources by ID, not by name.

### staff_assignments
| id PK | event_id FK | user_id FK | staff_role TEXT (HEAD/COMMITTEE/OIC/FIC) | assigned_by FK | active BOOL | created_at |

### audit_logs (bot's own source of truth — independent of Discord)
| id PK | event_id FK NULL | actor_user_id FK NULL | action TEXT | entity_type TEXT | entity_id INT NULL | before JSON NULL | after JSON NULL | result TEXT (SUCCESS/FAILURE) | error TEXT NULL | created_at |

### exports
| id PK | event_id FK | export_type TEXT | file_path TEXT | row_count INT | generated_by FK | created_at |

## Data-integrity constraints (enforced in DB where possible, else service layer)

1. One active application per (event, game, user) — partial unique index.
2. A user cannot be `active` in two teams in the same event — service check + index.
3. `team_members` active count ≤ `teams.roster_size` — service check, optionally backed by a Postgres trigger/constraint.
4. A team only holds players of its `game_id` — application.game_id must equal team.game_id at join (service check).
5. Only APPROVED/ASSIGNED_TO_TEAM applicants may join/create teams.
6. `applications.rejection_reason` NOT NULL when status = REJECTED — CHECK constraint.
7. State transitions validated against machines in `state-machine.md` before write.
8. FK constraints ON; cascade rules: deleting a team soft-marks members left (no hard delete of history).
9. Discord IDs unique per resource where applicable.

## Backup

Two layers: (1) **Supabase-managed** automatic/point-in-time backups (plan-dependent) via the Supabase dashboard; (2) **local off-platform** dumps — `/system backup` runs `pg_dump` against the Supabase connection to `data/backups/esports-YYYYMMDD-HHMMSS.sql` (or custom-format `.dump`). Restore via `pg_restore`/`psql`. See deployment-guide.md. Backups contain PII → treat as sensitive.

# Discord Limitations & Mitigations

This document enumerates Discord API/platform limits the implementation must respect, and how the bot mitigates each. Setup MUST calculate estimated resource usage and abort with an explanation if a limit would be exceeded.

## Resource limits

| Resource | Limit | How the bot handles it |
|---|---|---|
| Roles / guild | 250 | Estimate: 7 base roles + 1 per team. Setup projects max teams and warns when `7 + expected_teams` approaches 250. Team creation refuses past a configurable `MAX_TEAMS` and past the hard limit. |
| Channels / guild | 500 | Setup budgets: preserved + staff/log channels + per-game channels + (teams × 2). Abort if projected > 500. |
| Categories / guild | ~50 | 1 per game + STAFF + STAFF LOGS + preserved. Abort if games push over. |
| Channels / category | 50 | Team text+voice live under the game category. Hard team ceiling per game = (50 − base game channels) / 2. Documented and enforced. |
| Forum channels | Community only | Prerequisite check (`COMMUNITY` feature). |
| Stage channels | Community only | Prerequisite check; optional feature degrades gracefully. |
| Modal inputs | 5, text only | Multi-step application (see constraints.md §2). |
| Slash commands / guild | 100 | Command set is well under; grouped via subcommands. |
| Embed | 6000 chars / 25 fields / 1024 per field / 256 title | Mechanics/embeds validated before send; truncate + link overflow. |
| Message | 2000 chars | Use embeds/files. |
| Attachment size | 25 MB (non-boosted) | File-upload validation caps size below this (default 8 MB). |
| Rate limits | per-route buckets | discord.py handles 429 backoff; setup/cleanup batch operations and add small delays; all bulk ops are resumable. |
| Bulk message delete | only messages < 14 days | Cleanup deletes channels wholesale rather than bulk-deleting old messages. |
| Audit log | Discord's own | The bot keeps its **own** `audit_logs` table (source of truth), independent of Discord's. |

## Behavioral limitations

- **DMs may be closed.** All applicant notifications fall back to an ephemeral message or a mention in a designated channel.
- **Command propagation.** Guild-scoped command registration is near-instant; global registration can take up to an hour. The bot syncs **guild-scoped** for the operating guild.
- **Manual tampering.** Staff may delete a channel/role by hand. The bot stores IDs and reconciles: on startup and on demand (`/system health`) it detects missing resources and can recreate them from DB state.
- **Interaction token expiry.** Interaction responses must be sent within 3s (defer) / 15 min (followup). Long operations `defer()` immediately and edit the response when done.
- **No true transactions across Discord + DB.** Mitigation: DB write is the source of truth; Discord operations are wrapped so that on failure the DB records the intended-vs-actual state and `/system health` can reconcile. Each team/channel creation records a status (PENDING → CREATED / FAILED).

## Conflicts with the brief (resolved)

1. **Forum requirement vs non-Community servers.** The brief assumes forums/stages exist. Resolution: Community is a documented **prerequisite**; setup verifies it. (See open-questions is not needed — this is a hard platform fact, documented here.)
2. **9-field application form vs 5-input modal cap.** Resolved via multi-step flow (constraints.md §2).
3. **"Create voice channels = teams/2" for odd counts.** Resolved as `floor(N/2)`; the odd team out waits/gets a bye (OQ-3).

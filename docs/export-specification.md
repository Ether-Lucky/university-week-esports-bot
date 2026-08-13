# Export Specification

## Format rules
- **CSV**, UTF-8 **with BOM** (so Excel opens Unicode correctly), RFC-4180 quoting (fields with commas/quotes/newlines quoted; embedded quotes doubled).
- One header row; ISO-8601 timestamps in the event timezone with offset (e.g. `2027-02-14T09:00:00+08:00`).
- Files written to `data/exports/<event>-<type>-<YYYYMMDD-HHMMSS>.csv`; also delivered to the invoking staff (ephemeral) and logged to `#log-exports` + `exports` table.
- `/export all` produces a ZIP of every CSV.
- Screenshot fields export a **reference** (local path + Discord URL), not the binary.

## Applicant export (`/export applicants`)
`application_id, event, event_year, discord_user_id, discord_username, discord_display_name, first_name, full_name, middle_initial, school_email, facebook_url, year_section, game, status, team, reviewed_by, rejection_reason, created_at, updated_at`

## Team export (`/export teams`)
`team_id, event, game, team_name, team_leader, member_count, roster_size, status, created_at, updated_at, disbanded_at`
(Members summarized as count; see members export for detail.)

## Team member export (`/export members`) — normalized, one row per membership
`team_member_id, event, game, team_id, team_name, discord_user_id, discord_username, display_name, role_in_team, joined_at, left_at, active`

## Battle result export (`/export matches`)
`match_id, event, game, round, team_a, team_b, winner, status, screenshot_ref, reported_by, corrected, correction_reason, created_at, updated_at`

## Check-in export (`/export checkins`)
`checkin_id, event, game, team, discord_user_id, display_name, state, actor, created_at, updated_at`

## Audit log export (`/export logs`)
`audit_id, timestamp, actor, action, entity_type, entity_id, before, after, result, error`
(`before`/`after` serialized as compact JSON strings.)

## Acceptance
- Opening any export in Excel shows correct columns, no mojibake, dates readable.
- Row counts match `/system status` figures at export time.
- PII exports are local files only; never posted to public channels (security.md).

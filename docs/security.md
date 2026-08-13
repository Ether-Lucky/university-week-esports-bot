# Security & Privacy

## 1. Secrets
- Discord bot token **and the Supabase `DATABASE_URL`** (contains DB password) live only in `.env` (gitignored). Ship `.env.example` with placeholders.
- `.gitignore` MUST include `.env`, `data/`, `data/backups/`, `data/exports/`, `data/logs/`, `*.sql`, `*.dump`.
- Connection to Supabase uses **TLS/SSL** (`sslmode=require`). Use the service DB credentials, not the anon key; never expose the DB URL in logs or errors.
- No secret is ever logged, echoed in an error message, or written to an audit record.
- On startup, config loads via Pydantic; a missing/invalid token fails fast with a clear (secret-free) message.

## 2. Input validation (domain/validators.py)
- **School email:** RFC-lite format check + MUST end with `@<event.email_domain>` (case-insensitive). Reject otherwise with a clear message.
- **Facebook URL:** must parse as `https://`, host in `{facebook.com, www.facebook.com, m.facebook.com, fb.com}`. No other schemes/hosts. Stored as-is; never auto-followed.
- **Team logo URL (OQ-7):** must be `https://`, host on an image/CDN allowlist (e.g. Discord CDN, imgur, common hosts — configurable), and end in an image extension or return an image content-type. Rendered as a forum thumbnail; never fetched/executed server-side beyond a lightweight validation HEAD.
- **Names / team names:** sanitize — strip control chars, collapse whitespace, cap length, disallow `@everyone`/`@here`/role-mention patterns and Discord markdown injection, block empty/emoji-only. Team names unique per (event, game).
- **Year & section, IGN, roles:** length-capped, control-char stripped.
- **Numeric/enums:** validated against allowed sets before DB write.

## 3. File uploads (screenshots) — Discord-reference only
- Screenshots (Find-a-Team profile/stats, battle results) are uploaded to Discord by the user; the bot stores **only the Discord attachment reference** (CDN URL + channel/message/attachment IDs). **No local copy, no DB BLOB** (OQ-6).
- On receipt the bot validates the Discord attachment: content-type in {PNG, JPEG, WEBP}, size ≤ configurable **8 MB** cap. Rejects otherwise.
- Because there is no local file storage and no HTTP endpoint, there is no path-traversal or file-serving surface. Images are never executed or fetched beyond validation.
- Caveat (OQ-6 trade-off): if the source Discord message is deleted, the CDN URL may expire. Screenshots therefore live in **staff-only channels** that are not cleaned up until archive; the DB retains the reference and metadata regardless.
- **Team logos are URLs** (OQ-7), validated per §2 — no upload path at all.

## 4. Privacy of student PII
- PII (name, school email, Facebook URL, year/section, screenshots) is **personal data**.
- Applications are only ever posted to **staff-only** channels. Public forums show non-PII team info (team name, roster display names, status) only.
- Applicant notifications with PII go via DM or ephemeral messages, never public channels.
- Exports are written to `data/exports/` (local, gitignored). Operators are instructed (deployment-guide) to protect/delete these files per school policy.
- Staff logs are in staff-only channels; the bot never cross-posts staff logs publicly.
- Retention: PII retained in DB as historical record (source of truth) but local uploaded files may be purged per a configurable retention window after ARCHIVED (documented; default keep).

## 5. Authorization & abuse prevention
- Dual-layer authz (permissions.md). Sensitive commands hidden via `default_member_permissions` AND re-checked in code.
- Rate/abuse guards: per-user cooldowns on Apply/Create/Join/Recruit to prevent spam; duplicate-application prevention via DB constraint.
- The bot never assigns/removes roles it doesn't manage, never edits channels outside `discord_resources`, and refuses to act if its role is positioned below a target role.
- Recruitment requests expire (configurable) to avoid dangling grants.

## 6. Error handling & leakage
- User-facing errors are friendly and generic ("Something went wrong, staff have been notified"). Full stack traces go only to `#log-errors` and console, never to public channels, and never include the token or secrets.
- All external inputs treated as untrusted; the bot follows the instruction-source boundary — content in messages/forms is data, not commands.

## 7. Data location & backups
- PII lives in the **Supabase-hosted Postgres** database. Secure the Supabase project: strong DB password, restrict dashboard access (MFA), keep the project private, and limit who holds the `DATABASE_URL`. Enable SSL enforcement.
- `pg_dump` backups in `data/backups/` are gitignored; store off-machine copies (encrypted). Backups + exports contain PII → treat as sensitive; delete per school policy after archive.

## 8. Threat checklist
| Threat | Mitigation |
|---|---|
| Token / DB URL leak | .env + gitignore + never logged; Supabase SSL + strong password + MFA |
| Fake/bot applicants | Verification gate + school-email domain + staff review |
| Duplicate/smurf apps | Unique active application constraint (email↔Discord 1:1) |
| Malicious uploads | Type/size/magic-byte validation, no execution/serving |
| Mention injection in names | Name sanitization |
| Privilege escalation | Dual-layer authz, role-position check, audit |
| PII exposure | Staff-only channels, ephemeral replies, local-only exports |
| Data loss | DB source of truth, backups, idempotent recovery |

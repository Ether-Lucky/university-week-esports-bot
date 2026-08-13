# Constraints

## 1. Discord platform constraints (see also discord-limitations.md)

| Limit | Value (current) | Impact |
|---|---|---|
| Roles per guild | 250 | Each team = 1 role. Cap teams accordingly. |
| Channels per guild | 500 | Categories + channels + team channels all count. |
| Categories per guild | ~50 | One per game + staff/logs categories. |
| Channels per category | 50 | Team channels live under game category → hard team ceiling. |
| Guild-wide role/channel creation | rate-limited | Setup must batch + back off; expect slow setup. |
| Modal text inputs | max 5 per modal | Application form (9 fields) needs ≥2 modals or a multi-step flow. |
| Modal input types | short/paragraph text only | No file upload, dropdown, or date picker inside a modal. |
| File upload in interactions | not in modals | Screenshots/logos captured via a follow-up message upload step, not the modal. |
| Stage channels | require Community server | Validate `COMMUNITY` guild feature before creating. |
| Forum channels | require Community server | Team Forum / recruitment forum need Community. **Critical dependency.** |
| Slash command global sync | up to ~1h propagation | Use guild-scoped command sync for instant updates. |
| Embed limits | 6000 chars total, 25 fields, 1024/field | Mechanics embeds must respect this. |
| Message content | 2000 chars | Long content → embeds or files. |
| DM delivery | may be blocked by user | Notifications need channel fallback. |

**Key architectural consequence:** because Forum channels (Team Forum, recruitment forum) and Stage channels **require a Community-enabled server**, setup validation MUST check the `COMMUNITY` guild feature and either (a) require the operator to enable Community first, or (b) fall back to a non-forum representation. This is tracked as a hard prerequisite in `setup-guide.md`.

## 2. Modal field constraint → application form design

Discord modals allow **max 5 text inputs and only text**. The application needs 9 fields, several of which (game selection, screenshots) aren't plain text. Resolution:
- **Step 1 (button):** game is chosen via a select menu *before* the modal (or pre-bound to the channel/game).
- **Step 2 (modal A, ≤5 inputs):** first name, full name, middle initial, school email, year & section.
- **Step 3 (modal or select):** Facebook URL + confirm (Discord ID/username captured automatically from the interaction — never typed).
- Screenshots (Find-a-Team) are uploaded via a follow-up ephemeral prompt asking the user to upload an image, not inside a modal.

## 3. Local hosting constraints

- **Only the bot is local; the database is hosted on Supabase (Postgres).** The bot needs internet to reach **both** Discord and Supabase. If either is unreachable, affected actions fail gracefully and retry (see error-handling.md).
- Bot only functions while the PC is on and online; scheduled/automated actions (e.g., auto-closing applications at a deadline) only fire when the process is running. Deadlines are enforced **on next command / on startup catch-up**, not guaranteed at the exact second.
- Single bot process; Postgres handles concurrency. Use the Supabase connection pooler (transaction mode) with a small pool.
- No inbound ports required (bot uses outbound gateway/WebSocket to Discord and outbound TLS to Supabase).
- Screenshots are **not** stored locally — only Discord attachment references are kept (OQ-6). Team logos are URLs (OQ-7). So the local machine holds no user images.

## 4. Legal / privacy constraints

- Student PII (email, Facebook, name, screenshots) is personal data. It must not be posted to public channels. Applications go to staff-only channels; exports are local files with restricted handling. See `security.md`.

## 5. Technology constraints (chosen — see architecture.md ADRs)

- Python 3.11+ · discord.py 2.x · **PostgreSQL on Supabase** + async SQLAlchemy 2.x (asyncpg) · Alembic migrations · Pydantic (config) · pytest.
- Windows 10/11 primary target for the bot process; database is remote (Supabase).

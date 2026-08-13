# Setup Guide (First-Time & Yearly)

Audience: the operator running the bot on a local Windows PC. Assume they may not be the original developer.

## A. Prerequisites
1. **Windows 10/11**.
2. **Python 3.11+** — install from python.org; check "Add Python to PATH". Verify: `python --version`.
3. **Git** (optional, for updates).
4. A **Discord account** with permission to add a bot to the target server, and the server must be **Community-enabled** (required for Forum/Stage channels — see §D).
5. A **Supabase account + project** (free tier is fine) — this hosts the database (only the bot is local). See §E-pre.
6. An **external verification bot** installed on the server (e.g. a captcha-gate bot) that assigns a "verified" role after a member passes its captcha (OQ-2). Note that role's ID for `.env`.
7. **PostgreSQL client tools** (`pg_dump`/`pg_restore`) for backups — bundled with the PostgreSQL installer; add its `bin` to PATH.

## B. Install the bot
```bash
git clone <repo> esports-bot   # or download + unzip
cd esports-bot
python -m venv .venv
.venv\Scripts\activate
pip install -e .               # installs dependencies from pyproject.toml
```

## C. Create the Discord application & bot
1. Go to the Discord Developer Portal → **New Application** → name it.
2. **Bot** tab → **Add Bot**. Copy the **token** (keep secret).
3. **Privileged Gateway Intents:** enable **Server Members Intent** (needed for role/member management) and **Message Content Intent** only if used (this bot is interaction-first; enable Members + Guilds).
4. **OAuth2 → URL Generator:** scopes `bot` + `applications.commands`. Bot permissions: Manage Roles, Manage Channels, Manage Server (for Community/setup reads), Read/Send Messages, Embed Links, Attach Files, Manage Messages, Move Members, Mute/Deafen Members (voice), Create Public/Private Threads, Send Messages in Threads, Manage Threads, Priority Speaker (stage), View Channels.
5. Copy the generated **invite URL**, open it, invite the bot to your server.
6. In Server Settings → Roles, **drag the bot's role above** all roles it will manage (it must sit above @E-Sports Committee and below/above as per hierarchy in discord-server-design.md). The bot warns at setup if it's positioned too low.

## D. Enable Community (required)
Server Settings → **Enable Community** → follow the wizard (rules channel, updates channel, verification level). This unlocks **Forum** and **Stage** channels. Without it, setup will stop and tell you to enable Community.

## E-pre. Create the Supabase database
1. Sign in to Supabase → **New project**. Choose a name, a strong **database password** (save it), and a region close to you.
2. Wait for provisioning. Go to **Project Settings → Database → Connection string**.
3. Copy the **connection pooler** URI (transaction mode) for the bot runtime, and note the **direct connection** URI for migrations. They look like:
   `postgresql://postgres.<ref>:<password>@<host>:6543/postgres` (pooler) / `...:5432/postgres` (direct).
4. Ensure `sslmode=require` is applied (the app appends it). Keep this URI secret.

## E. Configure environment
```bash
copy .env.example .env
```
Edit `.env`:
```
DISCORD_TOKEN=your-bot-token
GUILD_ID=your-server-id                 # right-click server → Copy Server ID (Developer Mode on)
OWNER_DISCORD_ID=your-user-id           # optional break-glass only (OQ-13; normal bootstrap = E-Sports Head role)
# Supabase Postgres (only the bot is local):
DATABASE_URL=postgresql+asyncpg://postgres.<ref>:<password>@<pooler-host>:6543/postgres?sslmode=require
MIGRATION_DATABASE_URL=postgresql+asyncpg://postgres.<ref>:<password>@<direct-host>:5432/postgres?sslmode=require
VERIFIED_SOURCE_ROLE_ID=role-id-from-external-verification-bot   # OQ-2
UPLOAD_MAX_MB=8
RECRUIT_TIMEOUT_MINUTES=120
LOG_LEVEL=INFO
```

## F. Initialize the database (runs against Supabase)
```bash
alembic upgrade head              # creates the schema in your Supabase Postgres
```
This connects to Supabase and builds all tables. Verify in the Supabase dashboard → Table Editor. Back up anytime with `/system backup` (pg_dump) — see deployment-guide.md.

## G. Start the bot
```bash
python -m esports_bot
```
You should see: connected as <bot>, guild resolved, no active event yet. Slash commands sync to your guild (near-instant).

## H. First-time server setup (in Discord)
> Bootstrap (OQ-13): the pre-existing **E-Sports Head** role runs setup. Before starting, the server owner/Admin must create/keep an **@E-Sports Head** role and assign it to the operator. (Setup preserves this role.) The `OWNER_DISCORD_ID` in `.env` is only an emergency fallback.
1. `/event create` → wizard: event name, year, school, email domain, timezone, cleanup policy.
2. `/event configure` → add games + roster sizes + deadlines + tryout date.
3. `/setup preview` → review what will be preserved vs removed + resource-limit projection.
4. `/setup backup` → saves current server structure to JSON.
5. `/setup confirm <token>` → builds roles, categories, channels, forums, logs. Resumable if interrupted.
6. `/setup status` and `/system health` → verify everything created; repair any MISSING.
7. `/staff add @user COMMITTEE` (and OIC/FIC) → assign your staff.

The event is now in APPLICATIONS_OPEN once you advance. See `staff-usage` (README) for running the event.

## I. Yearly reuse (new University Week)
- Ensure last year's event is `ARCHIVED` (it stays in the DB forever).
- `/event create` for the new year → new `events` row (games catalog reused). Optionally clone last year's config as a template.
- Re-run `/setup preview` → `/setup confirm` to (re)build the current year's structure.
- **No code changes.** Update the bot only for bug fixes/features (see deployment-guide.md §Updating).

## J. Verifying the bot works
- Bot online (green) in member list.
- `/system status` returns event + connections OK (Discord + Supabase).
- Complete the **external verification bot's** captcha in #verify → it grants the verified role → our bot grants **Audience**.
- Press **Apply as Player** → form opens.

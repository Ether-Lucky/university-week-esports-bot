# University Week E-Sports Discord Bot

A reusable, configuration-driven Discord bot that runs a university's annual
University Week **E-Sports tryout/tournament**: verification, applications, teams,
recruitment, tryout logistics, matches, results, champions, exports, and cleanup.

- **Only the bot runs locally** (on a Windows PC). The **database is hosted on Supabase**.
- **The database is the source of truth**; Discord channels/roles are a rebuildable projection.
- **Reusable every year** — nothing (year, games, roles, dates) is hard-coded. A new year is a
  new event record, no code changes.

> This README is the full operator manual. Deeper design detail lives in [`docs/`](docs/README.md).
> If you get stuck, jump to [Troubleshooting](#15-troubleshooting).

---

## Table of contents
1. [How it works](#1-how-it-works)
2. [What you need before starting](#2-what-you-need-before-starting)
3. [Get the code onto the PC](#3-get-the-code-onto-the-pc)
4. [Install Python + the bot](#4-install-python--the-bot)
5. [Create the Discord bot](#5-create-the-discord-bot)
6. [Enable Community on your server](#6-enable-community-on-your-server)
7. [Add an external verification bot](#7-add-an-external-verification-bot)
8. [Create the Supabase database](#8-create-the-supabase-database)
9. [Configure `.env`](#9-configure-env)
10. [Initialize the database](#10-initialize-the-database)
11. [Run the bot](#11-run-the-bot)
12. [First-time setup inside Discord](#12-first-time-setup-inside-discord)
13. [Running the event, phase by phase](#13-running-the-event-phase-by-phase)
14. [Command reference](#14-command-reference)
15. [Troubleshooting](#15-troubleshooting)
16. [Backups & restore](#16-backups--restore)
17. [Updating the bot & reusing it next year](#17-updating-the-bot--reusing-it-next-year)
18. [Running the tests (optional)](#18-running-the-tests-optional)
19. [Project layout](#19-project-layout)

---

## 1. How it works

```
Your Windows PC                     The internet
┌────────────────────┐
│  python -m esports_bot │ ───────►  Discord API   (your server: channels, roles, buttons)
│  (the bot process) │ ───────►  Supabase       (PostgreSQL database = source of truth)
└────────────────────┘
```

The PC only needs to be **on and online** while the bot must respond to commands or run
automated actions. When the bot is off, Discord still shows everything it already created,
but buttons/commands won't respond.

---

## 2. What you need before starting

| # | Requirement | Notes |
|---|---|---|
| 1 | **Windows 10/11 PC** | The machine that will host the bot. |
| 2 | **Python 3.11 or newer** | Installed in step 4. |
| 3 | **A Discord account** | With permission to add a bot and manage the target server. |
| 4 | **A Discord server** you control | Where the event runs. You must be able to make it *Community* (step 6). |
| 5 | **An `@E-Sports Head` role** on that server | Create it manually and give it to yourself; setup preserves it and it authorizes setup. |
| 6 | **A Supabase account** (free tier is fine) | Hosts the database (step 8). |
| 7 | **An external verification bot** on the server | e.g. a captcha-gate bot that gives a "verified" role (step 7). |
| 8 | **PostgreSQL client tools** (`pg_dump`) | Only needed for local backups; optional to start. |

You do **not** need to know how to code to operate the bot.

---

## 3. Get the code onto the PC

The project folder is:

```
C:\Users\Ether\Desktop\1SCHOOOL\1 1 1 1 College\esports
```

That folder (the one containing `pyproject.toml`, `README.md`, and the `src/` folder) is the
**project root**. **Every command in this guide is run from the project root.**

Open **PowerShell** and go there (the path has spaces, so keep the quotes):

```powershell
cd "C:\Users\Ether\Desktop\1SCHOOOL\1 1 1 1 College\esports"
```

> Tip: you can confirm you're in the right place with `ls` — you should see `pyproject.toml`,
> `src`, `docs`, `alembic.ini`.

---

## 4. Install Python + the bot

1. **Install Python 3.11+**: download from <https://www.python.org/downloads/>. During install,
   **tick "Add Python to PATH"**. Verify in a new PowerShell window:
   ```powershell
   python --version
   ```
   It should print `Python 3.11.x` (or newer).

2. **Create a virtual environment and install the bot** (run from the project root):
   ```powershell
   cd "C:\Users\Ether\Desktop\1SCHOOOL\1 1 1 1 College\esports"
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1     # PowerShell   (cmd.exe: .venv\Scripts\activate.bat)
   pip install -e .
   ```
   - The `.venv` is a private copy of Python for this project. You'll **activate it every time**
     before running the bot. When active, your prompt shows `(.venv)`.
   - **Activation command depends on your terminal:**
     - **PowerShell**: `.\.venv\Scripts\Activate.ps1`
     - **Command Prompt (cmd.exe)**: `.venv\Scripts\activate.bat`
   - If you skip activation you must call the venv's Python explicitly:
     `.venv\Scripts\python.exe -m esports_bot`. Running plain `python -m esports_bot` **without**
     an active venv uses the system Python (which doesn't have the bot) and fails with
     `No module named esports_bot`.
   - If PowerShell blocks activation with a script-execution error, run this once, then retry:
     ```powershell
     Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
     ```

---

## 5. Create the Discord bot

1. Go to the **Discord Developer Portal**: <https://discord.com/developers/applications>.
2. **New Application** → give it a name (e.g. "UW E-Sports") → **Create**.
3. Left sidebar → **Bot** → **Add Bot** → **Yes, do it**.
4. Under **Bot**, click **Reset Token** → **Copy** the token. **Keep it secret** — you'll paste it
   into `.env` in step 9. (If it ever leaks, come back here and Reset Token again.)
5. Still on the **Bot** page, under **Privileged Gateway Intents**, enable:
   - ✅ **Server Members Intent** (needed to manage roles and detect verification).
   - (Message Content is **not** required.)
   Click **Save Changes**.
6. Left sidebar → **OAuth2** → **URL Generator**:
   - **Scopes**: check `bot` and `applications.commands`.
   - **Bot Permissions**: check **Manage Roles**, **Manage Channels**, **Manage Server**,
     **View Channels**, **Send Messages**, **Embed Links**, **Attach Files**, **Manage Messages**,
     **Read Message History**, **Move Members**, **Mute Members**, **Deafen Members**,
     **Create Public Threads**, **Send Messages in Threads**, **Manage Threads**.
   - Copy the **Generated URL** at the bottom, open it in your browser, pick your server, **Authorize**.
7. **Get your server ID**: in Discord, enable Developer Mode (User Settings → Advanced →
   Developer Mode), then right-click your server icon → **Copy Server ID**. Save it for step 9.
8. **Position the bot's role**: Server Settings → **Roles**. Drag the bot's own role
   **above** `@E-Sports Committee` and the other roles it will manage. If it's too low, Discord will
   refuse to let it create/assign roles.

---

## 6. Enable Community on your server

The bot creates **Forum** and **Stage** channels, which require a Community-enabled server.

- Server Settings → **Enable Community** → follow the wizard (set a rules channel and an updates
  channel, choose verification level). This is required — `/setup` will stop and tell you if it's
  missing.

---

## 7. Add an external verification bot

Per the project's decision (OQ-2), a **separate** verification/captcha bot handles anti-bot
verification and hands out a "verified" role; our bot then gives those members the **Audience** role.

1. Invite a verification bot of your choice (a captcha-gate bot) to the server and configure it so
   that passing verification grants a specific role (e.g. `@Verified`).
2. Copy that role's ID: Server Settings → Roles → right-click the verified role → **Copy Role ID**
   (Developer Mode must be on). Save it for step 9 (`VERIFIED_SOURCE_ROLE_ID`).

> Don't want an external bot? The button-only alternative can be re-enabled, but as configured the
> bot expects an external verified role.

---

## 8. Create the Supabase database

1. Sign in at <https://supabase.com> → **New project**.
2. Choose a name, set a strong **database password** (write it down — you'll need it in step 9),
   pick a region near you, and create the project. Wait for it to finish provisioning.
3. Go to **Project Settings → Database → Connection string** and open the **Connection pooling**
   tab. You'll see a URI like:
   ```
   postgresql://postgres.<ref>:[YOUR-PASSWORD]@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```
   Note the **host** (`aws-0-<region>.pooler.supabase.com`) and confirm the **port `5432`** (session
   mode — best for a single always-on bot). You'll build two URLs from this in the next step.

> The host looks like `aws-0-<region>.pooler.supabase.com` (e.g. `aws-0-ap-southeast-1...`), and
> `<ref>` is your project reference. Always copy the exact host, port, and ref from **your** Supabase
> dashboard — don't guess them.

---

## 9. Configure `.env`

The bot reads its secrets from a file named **`.env`** in the **project root**. It is **never**
committed to git.

1. Copy the template:
   ```powershell
   copy .env.example .env
   ```
2. Open `.env` in a text editor (Notepad is fine) and fill in real values:
   ```
   DISCORD_TOKEN=paste-the-bot-token-from-step-5
   GUILD_ID=your-server-id-from-step-5
   OWNER_DISCORD_ID=your-own-discord-user-id     # optional emergency fallback

   # Supabase — use YOUR host/region/password from step 8.
   # Runtime (session pooler, port 5432):
   DATABASE_URL=postgresql+asyncpg://postgres.<ref>:PASSWORD@aws-0-<region>.pooler.supabase.com:5432/postgres
   # Migrations (same pooler, sync driver):
   MIGRATION_DATABASE_URL=postgresql+psycopg://postgres.<ref>:PASSWORD@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require

   VERIFIED_SOURCE_ROLE_ID=verified-role-id-from-step-7

   UPLOAD_MAX_MB=8
   RECRUIT_TIMEOUT_MINUTES=120
   LOG_LEVEL=INFO
   ```
   **Important:** if your database password contains special characters, URL-encode them in the URL
   (`@` → `%40`, `#` → `%23`, `:` → `%3A`, `/` → `%2F`). Example: a password `p@ss#word`
   becomes `p%40ss%23word`.

3. Save the file. Keep `.env` private — it contains your bot token and database password.

---

## 10. Initialize the database

This creates all the tables in your Supabase project. Run once (and again after any update that
adds migrations). From the project root, with the venv active:

```powershell
alembic upgrade head
```

You should see it connect and apply the migration with no errors. You can confirm in the Supabase
dashboard → **Table Editor** (you'll see `events`, `applications`, `teams`, etc.).

---

## 11. Run the bot

From the **project root**, with the venv active:

```powershell
cd "C:\Users\Ether\Desktop\1SCHOOOL\1 1 1 1 College\esports"
.\.venv\Scripts\Activate.ps1        # PowerShell   (cmd.exe: .venv\Scripts\activate.bat)
python -m esports_bot
```

- **Must activate the venv first.** If you see `No module named esports_bot`, the venv isn't active
  (you're on the system Python). Activate it (see above) — or run without activating using the
  venv's Python directly: `.venv\Scripts\python.exe -m esports_bot`.
- **Why the project root?** The bot loads `.env` from the current folder and writes runtime files
  (logs, exports, backups) under `.\data\`. Running from elsewhere means it won't find your `.env`.
- On success you'll see log lines: starting, database connected, connected as `<bot>`, guild
  resolved, commands synced. Leave this window open while the event runs.
- **Stop the bot** with `Ctrl+C` in that window.
- In Discord, type `/system status` — it should report Discord and Database both connected.

> Keeping it running unattended: leave the PowerShell window open, or install it as an
> auto-restarting Windows service with **NSSM**. See [`docs/deployment-guide.md`](docs/deployment-guide.md).

---

## 12. First-time setup inside Discord

Do these **in Discord**, as the person holding the `@E-Sports Head` role.

1. **Create the event**
   ```
   /event create name:University Week E-Sports year:2027 school:University of Perpetual Help System Laguna
                 email_domain:uphsl.edu.ph timezone:Asia/Manila
   ```
2. **Add each game** (repeat per game)
   ```
   /event configure add-game game:Valorant roster_size:5
   /event configure add-game game:Mobile Legends roster_size:5
   ```
3. **Preview the server build** (safe — changes nothing). It lists what will be preserved vs removed,
   projects Discord resource usage, checks Community, and gives you a one-time token:
   ```
   /setup preview
   ```
4. **(Optional) Back up the current server structure** to a file:
   ```
   /setup backup
   ```
5. **Build the server** (⚠️ destructive — deletes non-preserved channels/roles, then creates the
   event structure). Use the token from the preview:
   ```
   /setup confirm token:<token-from-preview>
   ```
   > **Do your very first `/setup confirm` on a throwaway test server** to see what it does before
   > running it on the real one. It preserves: your announcements channel, the designated
   > `TEXT CHANNELS` category and its channels, and the `@E-Sports Head` role.
6. **Verify** everything was created and repair anything missing:
   ```
   /system health
   ```
7. **Assign your staff** (Committee / Officer in Charge / Faculty in Charge):
   ```
   /staff add member:@Someone role:E-Sports Committee
   ```
8. **Post the Apply button** in the `#apply` channel (run this command *in* that channel):
   ```
   /application post-button
   ```

You're set up. Move the event forward with `/event advance` when you're ready to open applications.

---

## 13. Running the event, phase by phase

The event moves through states with `/event advance` (or `/event rollback` to step back). What's
allowed depends on the current state.

| Phase | What happens | Key commands |
|---|---|---|
| **DRAFT** | Event created, nothing built | `/event configure add-game`, `/setup preview/confirm` |
| **APPLICATIONS_OPEN** | Members verify (external bot) then **Apply as Player**; staff review | Apply button, `/application list`, `/application approve id:`, `/application reject id: reason:` |
| **TEAM_FORMATION** | Approved applicants form teams & recruit | `/team create`, `/team join team_id:`, `/team view`, `/recruit player member:`, `/recruit accept request_id:` |
| **REGISTRATION_LOCKED** | Rosters frozen; finalize mechanics & bracket links | `/mechanics create`, `/mechanics publish`, `/tournament set` |
| **PRE_TRYOUT** | Team check-in + final validation | `/tryout checkin`, `/tryout status` |
| **TRYOUT_ACTIVE** | Matches run; results recorded | `/tryout start`, `/match battle-ended match_id: winner_team_id:`, `/match correct` |
| **RESULTS** | Champions crowned, data exported | `/tryout crown game: team_id:`, `/tryout end`, `/export all` |
| **CLEANUP** | Temporary resources deleted, history kept | `/system cleanup confirm:True` |
| **ARCHIVED** | Read-only history | `/system archive`, later `/export …` |

A typical run:
```
/event advance                     (DRAFT -> APPLICATIONS_OPEN, after setup)
   … applicants apply, staff approve/reject …
/event advance                     (-> TEAM_FORMATION)
   … teams form, recruit …
/event advance                     (-> REGISTRATION_LOCKED)
/mechanics create … ; /mechanics publish … ; /tournament set …
/event advance                     (-> PRE_TRYOUT)
/tryout status                     (must show READY)
/tryout start                      (-> TRYOUT_ACTIVE, creates match voice channels)
   … /match battle-ended for each match …
/tryout crown game:Valorant team_id:12
/tryout end                        (-> RESULTS)
/export all
/system cleanup confirm:True       (-> CLEANUP)
/system archive                    (-> ARCHIVED)
```

`/tryout status` must show **READY** (mechanics published, Challonge set, ≥2 complete teams, and a
tryout date) before `/tryout start` will run.

---

## 14. Command reference

**Setup & event**
- `/setup preview` · `/setup backup` · `/setup confirm token:` — build the server (Head).
- `/event create …` · `/event configure add-game …` · `/event configure remove-game game:` · `/event advance` · `/event status` — Head.

> **Fixing a misinput:** `/event configure remove-game game:<name>` removes a wrongly-added game
> (DRAFT/SETUP only) and deletes its Discord channels. It refuses if applications/teams already
> use that game. And `/event create` **never** deletes data — it's blocked while an event is active
> and only ever adds a new event record, so nothing gets wiped.

**Staff & system**
- `/staff add member: role:` · `/staff remove member:` · `/staff list`.
- `/system status` — health & counts. `/system health` — reconcile resources.
- `/system cleanup confirm:True` · `/system archive` — Head, end-of-event.

**Applications** (staff review)
- Apply button (members) · `/application list` · `/application approve id:` · `/application reject id: reason:` · `/application post-button`.

**Teams**
- `/team create name: game: [logo:]` · `/team join team_id:` · `/team leave` · `/team view team_id:` · `/team disband team_id: [reason:]`.

**Recruitment**
- `/recruit player member:` (leader) · `/recruit accept request_id:` · `/recruit decline request_id:`.

**Mechanics & tournament** (staff)
- `/mechanics create game: title: description:` · `/mechanics publish game:` · `/tournament set game: url:`.
- See [`docs/embed-authoring.md`](docs/embed-authoring.md) for writing clean mechanics.

**Tryout & matches** (staff)
- `/tryout status` · `/tryout checkin` (players) · `/tryout start` · `/tryout crown game: team_id:` · `/tryout end`.
- `/match battle-ended match_id: winner_team_id: [screenshot:] [notes:]` · `/match correct match_id: winner_team_id: reason:`.

**Exports** (staff)
- `/export kind:applicants|teams|members|matches|checkins|logs|all`.

---

## 15. Troubleshooting

| Symptom | Fix |
|---|---|
| `Configuration error: missing or invalid settings` on start | A required value in `.env` is missing/blank. Check `DISCORD_TOKEN`, `GUILD_ID`, `DATABASE_URL`. |
| Bot starts but `Configured GUILD_ID … not found` | The bot isn't in that server, or `GUILD_ID` is wrong. Re-invite (step 5) / re-copy the server ID. |
| Slash commands don't appear | Wait a few seconds and refresh Discord; the bot syncs commands to your guild on startup. Ensure it's actually running. |
| `403 Forbidden (50001 Missing Access)` on startup (command sync) | The bot was invited without the `applications.commands` scope. Re-invite it (Developer Portal → OAuth2 → URL Generator) with **both** `bot` and `applications.commands` scopes, authorize it to your server, then restart. |
| `/setup` says Community is required | Enable Community (step 6), then retry. |
| Bot "can't create/assign roles" or 403 errors | Drag the **bot's role above** the roles it manages (step 5.8) and confirm its permissions. |
| `403 (50013 Missing Permissions)` when applying channel permissions | The bot needs **Manage Roles** AND its role must sit **above `@E-Sports Head`**. In Server Settings → Roles, give the bot's role Manage Roles (or Administrator) and drag it to the top, then re-run `/setup preview` → `/setup confirm`. Setup now finishes and just reports how many channels it couldn't set. |
| Database "Unavailable" in `/system status` | Check internet, and that `DATABASE_URL` host/password are correct (URL-encode special chars). Supabase project must be running. |
| `alembic upgrade head` fails to connect | Verify `MIGRATION_DATABASE_URL` (note `+psycopg` and `?sslmode=require`) and the password encoding. |
| `No module named esports_bot` | The venv isn't active — you're on system Python. Activate it (PowerShell `.\.venv\Scripts\Activate.ps1`, cmd `.venv\Scripts\activate.bat`) then run, or use `.venv\Scripts\python.exe -m esports_bot`. Run from the project root. |
| A channel/role got deleted by hand | Run `/system health`; re-run `/setup confirm` to rebuild the base structure. |
| `/setup confirm` had issues on a Community server | Community-required channels (Rules, Community Updates) can't be deleted by anyone — the bot now preserves and skips them automatically. Just re-run `/setup preview` → `/setup confirm`. |
| Applicant didn't get a DM result | They likely have DMs closed; the result is still recorded and shown in the staff log channel. |

Detailed logs are in `.\data\logs\bot.log` and in the staff `#log-*` channels. Full recovery
scenarios are in [`docs/deployment-guide.md`](docs/deployment-guide.md).

---

## 16. Backups & restore

The **database is the source of truth**, so back it up:

- **Automatic**: Supabase keeps backups on its dashboard (plan-dependent) — your main safety net.
- **Local copy** (needs PostgreSQL client tools installed and on PATH):
  ```powershell
  pg_dump "postgresql://postgres.<ref>:PASSWORD@aws-0-<region>.pooler.supabase.com:5432/postgres" -Fc -f backup.dump
  ```
  Store a copy off the machine (encrypted USB / school drive). Backups contain student data —
  treat them as sensitive.
- **Restore**: use the Supabase dashboard's restore, or `pg_restore` into the database. See
  [`docs/deployment-guide.md`](docs/deployment-guide.md).

Recommended times to back up: before `/setup confirm`, before `/system cleanup`, before updating
the bot, and daily during the active event.

---

## 17. Updating the bot & reusing it next year

**Update the code**, from the project root:
```powershell
.\.venv\Scripts\Activate.ps1
pip install -e .
alembic upgrade head
python -m esports_bot
```
Always back up first. Migrations are forward-only — never edit the database by hand.

**Reuse next year** (no code changes):
1. Make sure last year's event is `ARCHIVED` (it stays in the database forever).
2. `/event create` for the new year → a fresh event record; the games catalog is reused.
3. `/setup preview` → `/setup confirm` to rebuild that year's structure.

---

## 18. Running the tests (optional)

Not needed to operate the bot — useful if you change the code.
```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest                 # unit tests (no database needed)
```
Live-database integration tests are skipped by default; enable them (they connect to
`DATABASE_URL` and roll everything back) with:
```powershell
$env:RUN_DB_TESTS="1"; pytest tests/integration; Remove-Item Env:\RUN_DB_TESTS
```

---

## 19. Project layout

```
esports/                         ← project root (run all commands here)
├── .env                         your secrets (never committed)
├── .env.example                 template
├── pyproject.toml               dependencies
├── alembic.ini                  database migration config
├── migrations/                  database migrations
├── data/                        runtime: logs, exports, backups (created automatically)
├── docs/                        full specification & guides
│   ├── setup-guide.md  deployment-guide.md  command-specification.md  embed-authoring.md  …
├── src/esports_bot/
│   ├── __main__.py              entrypoint (python -m esports_bot)
│   ├── bot.py  config.py  logging_setup.py
│   ├── cogs/                    Discord commands (event, setup, staff, applications, teams, …)
│   ├── services/               business logic
│   ├── domain/                 rules: states, permissions, validators, scheduling
│   ├── repositories/           database access
│   ├── infra/                  DB engine, Discord resources, exporter, audit
│   └── models/                 database tables
└── tests/                       unit + integration tests
```

Related docs: [`docs/README.md`](docs/README.md) (index) · [`docs/setup-guide.md`](docs/setup-guide.md) ·
[`docs/deployment-guide.md`](docs/deployment-guide.md) · [`CHANGELOG.md`](CHANGELOG.md).

## License
Internal university project. See the repository owner.

# Open Questions — RESOLVED

> All resolved by stakeholder on 2026-08-13. Recorded below; the rest of the specs have been updated to match.

## Resolutions (authoritative)

| ID | Decision | Effect |
|---|---|---|
| OQ-1 | **a** — one guild per bot instance. | Unchanged. |
| OQ-2 | **Third-party verification bot** — an external captcha/verification bot assigns a "verified" role; our bot detects that role (config `VERIFIED_SOURCE_ROLE_ID`) and grants **Audience**. | Verification FR + setup updated. Our bot does not implement captcha itself. |
| OQ-3 | **b** — `floor(N/2)` match voice channels; the odd team out **waits** (bye advances/waits, no channel). | Scheduling math updated everywhere. |
| OQ-4 | **b** — **one active application per user total** (across all games), not per game. | DB unique index changed to (event_id, user_id) on active statuses. |
| OQ-5 | **a** — school email bound 1:1 to one Discord account per event. | Unique (event_id, school_email) + (event_id, discord_user_id) on active apps. |
| OQ-6 | **b** — screenshots stored as **Discord attachment reference only** (no local copy). | No local file storage; DB stores Discord CDN URL + message/channel ref. |
| OQ-7 | **b** — team logo is a **URL only** (validated), not an upload. | No image upload for logos. |
| OQ-8 | **a** — rejected applicants may re-apply (new row; history kept). | Cooldown default: allowed immediately. |
| OQ-9 | **a** — cleanup is a **separate confirmed** `/system cleanup` step (not auto at tryout end). | Lifecycle unchanged (already modeled this way). |
| OQ-10 | **Player = champions only.** Team members compete as **Applicant + Team role**; the global **Player** role is granted to the **champion** team's members at `/tryout end`. | Permission model + server design + champion flow updated. |
| OQ-11 | **a** — edit the original announcement message on reschedule (+ post an "updated" notice). | Unchanged. |
| OQ-12 | **a** — Stage channel optional per game, off by default, only if Community. | Unchanged. |
| OQ-13 | **E-Sports Head role** is required to run first `/setup`. The pre-existing (preserved) E-Sports Head role must be assigned to the operator before setup. | Dropped "any Admin" bootstrap; `OWNER_DISCORD_ID` kept only as an optional break-glass fallback. |
| OQ-14 | **a** — store UTC, display in event timezone. | Unchanged. |
| OQ-15 | **a** — round-1 voice provisioning + free-form recorded results (no bracket engine; Challonge external). | Unchanged. |

## Additional stakeholder directive
- **Database is NOT local.** Only the bot runs locally. Use **Supabase (hosted PostgreSQL)** as the database. → Stack changed from SQLite to PostgreSQL/Supabase; see `architecture.md` ADR-002 (revised), `database-design.md`, `deployment-guide.md`, `setup-guide.md`.

---

## Original questions (for reference)

> Each had a recommended default (✅). Superseded by the resolutions above.

| ID | Question | Options | Recommendation |
|---|---|---|---|
| OQ-1 | **Single vs multi-guild.** Should one bot instance manage exactly one Discord server? | (a) One guild per instance ✅ (b) Multi-guild | (a) — matches "local event bot", simplest, safest. |
| OQ-2 | **Verification method.** How does a member become Audience? | (a) Button + rules-accept ✅ (b) Button + school-email check (c) CAPTCHA via external | (a) simple anti-bot button + agreement. School-email verification happens at *application* time, not verification. |
| OQ-3 | **Odd-team scheduling.** With N complete teams, `ceil(N/2)` voice channels means one team gets a bye. Correct? | (a) `ceil(N/2)`, one bye ✅ (b) `floor(N/2)`, bye team waits (c) Staff assign manually | (a) — matches brief's ceil example; bye recorded in DB. |
| OQ-4 | **School email uniqueness.** Can one school email apply for multiple games? | (a) One active application per user **per game** ✅ (b) One active application per user total | (a) — a student may realistically try out for >1 game. Configurable flag. |
| OQ-5 | **Discord identity linking.** Should a school email be bound to exactly one Discord account? | (a) Yes, 1:1 email↔Discord per event ✅ (b) Allow re-use | (a) prevents duplicate/smurf applications. |
| OQ-6 | **Screenshot storage.** Where do uploaded screenshots live? | (a) Discord attachment URL + local copy in `data/uploads/` ✅ (b) Discord only (c) DB BLOB | (a) — resilient (survives message deletion) but simple. Retention policy in security.md. |
| OQ-7 | **Team logo input.** Image upload or URL? | (a) Image attachment, stored like screenshots ✅ (b) URL only | (a) — validated (type/size), set as forum thumbnail. |
| OQ-8 | **Rejected applicant re-apply.** May a rejected applicant re-apply? | (a) Yes, new application (history kept) ✅ (b) No, staff must reset | (a) — with a configurable cooldown (default: allowed immediately). |
| OQ-9 | **Cleanup timing.** Does cleanup run automatically at tryout end or require a separate confirm? | (a) Separate `/system cleanup` confirm step ✅ (b) Auto at `/tryout end` | (a) — destructive; explicit confirm + backup first. |
| OQ-10 | **Player role vs Applicant role.** When a member joins a team, do they get Player role and lose Applicant? | (a) Gain Player, keep Applicant until registration lock ✅ (b) Swap immediately | (a) — simpler permission math; Player is additive. Confirm. |
| OQ-11 | **Announcement editing.** For tryout reschedules, edit the original announcement message or post a new one? | (a) Edit original + post an "updated" notice ✅ (b) New message only | (a) — keeps a single canonical announcement. |
| OQ-12 | **Which games get a Stage channel?** | (a) Optional per game, off by default, only if server is Community ✅ (b) One shared event Stage | (a) — configurable; skipped gracefully if not Community. |
| OQ-13 | **Staff bootstrap.** Before E-Sports Head role exists, who can run first `/setup`? | (a) Any Discord Administrator, once ✅ (b) Hard-coded operator Discord ID in `.env` | (a) primary; (b) available as `OWNER_DISCORD_ID` fallback in `.env`. |
| OQ-14 | **Timezone display.** Store all timestamps UTC, display in event timezone? | (a) UTC storage + event-tz display ✅ | (a) — standard. |
| OQ-15 | **Match model granularity for v1.** Full bracket tracking or just recorded results? | (a) Round-1 voice provisioning + free-form recorded results ✅ (b) Full bracket engine | (a) — matches "Challonge is external". Bracket lives in Challonge. |

**Please reply with any overrides** (e.g. "OQ-4 → b, OQ-9 → auto"). Anything you don't mention, I take as the ✅ default.

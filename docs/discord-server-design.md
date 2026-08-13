# Discord Server Design

All resource IDs created here are persisted in `discord_resources`. Names are cosmetic; the bot finds everything by stored ID.

## Prerequisites
- Server MUST be **Community-enabled** (required for Forum and Stage channels). Setup validates the `COMMUNITY` guild feature and stops with instructions if absent.

## Top-level structure created by setup

```
[PRESERVED]
  #announcements                (preserved announcement channel)
  ▸ TEXT CHANNELS (preserved category + its channels)
  @E-Sports Head                (preserved role)

[CREATED — roles]
  @E-Sports Committee
  @Officer in Charge
  @Faculty in Charge
  @Player
  @Applicant
  @Audience
  @<Team roles…>                (one per team, created on demand)

[CREATED — categories/channels]
  ▸ WELCOME / VERIFICATION
      #verify                    (external verification bot's captcha lives here;
                                  our bot grants Audience when the verified role appears)
      #rules
  ▸ APPLICATIONS
      #apply                     ("Apply as Player" — game select + modal)
  ▸ STAFF                        (visible: Head, Committee, OIC, FIC only)
      #staff-general
      #application-review        (approve/reject with reason)
      #staff-commands
  ▸ STAFF LOGS                   (staff-only)
      #log-system  #log-applications  #log-teams  #log-members
      #log-moderation  #log-commands  #log-tryout  #log-errors  #log-exports
  ▸ <GAME NAME>  (one category per configured game — see below)
```

## Per-game category (created for each configured game)

```
▸ VALORANT                       (category; overwrites scoped to game roles)
    #valorant-staff              (Committee/OIC/FIC/Head)
    #valorant-general            (Audience+ read, Applicant/Player write)
    #valorant-apply-info         (info / points to #apply)
    ⌗ valorant-team-forum        (FORUM — team posts; Join Team button)
    ⌗ valorant-lft-forum         (FORUM — Looking-For-Team profiles; Recruit button)
    #valorant-players            (champions / official Players — Player role only, OQ-10)
    #valorant-mechanics          (staff-published mechanics embed)
    #valorant-tournament         (Challonge link / bracket info)
    #valorant-battle-results     (Audience-visible results feed)
    🔊 valorant-tryout-1         (voice; the two matched teams' roles + staff only)  ← created at tryout start
    🔊 valorant-tryout-2         …  floor(complete_teams/2) channels; odd team out waits (OQ-3)
    🎤 valorant-stage            (STAGE — optional, audience view)   ← if stage_enabled & Community
```

### Team resources (created on team creation, under the game category)
```
@Team <Name>                     (role)
#team-<name>                     (text; team role + staff)
🔊 team-<name>                   (voice; team role + staff)
forum post in <game>-team-forum  (roster embed + Join button)
```

## Permission overwrite matrix (per channel type)

Legend: **V**=view, **R**=read history, **S**=send/interact, **C**=connect(voice), —=denied. `@everyone` denied view by default on all event channels; access granted per role.

| Channel | Audience | Applicant | Player | Committee | OIC/FIC | Head |
|---|---|---|---|---|---|---|
| #verify | V/S (before role) | — | — | V | V | V |
| #apply | — | V/S | V | V/S | V/S | V/S |
| #announcements | V/R | V/R | V/R | V/R/S | V/R/S | V/R/S |
| game #general | V/R | V/R/S | V/R/S | V/R/S | V/R/S | V/R/S |
| game team-forum | V/R | V/R/**S(Join)** | V/R | V/R/S | V/R/S | V/R/S |
| game lft-forum | V/R | V/R/**S(post)** | V/R | V/R/S | V/R/S | V/R/S |
| game #players (champions) | — | — | V/R/S | V/R/S | V/R/S | V/R/S |
| game #mechanics | V/R | V/R | V/R | V/R/**S** | V/R/S | V/R/S |
| game #tournament | V/R | V/R | V/R | V/R/S | V/R/S | V/R/S |
| game #battle-results | V/R | V/R | V/R | V/R/S | V/R/S | V/R/S |
| team #text / voice | — | team role* | team role* | V/S/C | V/S/C | V/S/C |
| game tryout voice | — | matched team role* | matched team role* | V/S/C | V/S/C | V/S/C |
| game stage | V (audience listen) | V | V | V + moderator | V + mod | V + mod |
| #application-review | — | — | — | V/R/S | V/R/S | V/R/S |
| STAFF LOGS/* | — | — | — | V/R | V/R | V/R |

Notes:
- **\*team role*** — team channels/voice grant access via that specific **Team role**, held by all members (who are Applicants during the tryout). The global **Player** role is separate and reserved for champions (OQ-10); it is not what gates team channels.
- **Audience must never connect** to team or tryout voice channels (explicit Connect deny).
- Interaction gating (who can press a button) is enforced **twice**: Discord overwrite + application-level authorization (a member could theoretically see a button; the handler re-checks).
- Team channels: only that team's role + staff. Enforced by per-team role overwrite.

## Role hierarchy (top → bottom, controls who can manage whom)

```
(bot's own managed role — must sit ABOVE all roles it creates/assigns)
@E-Sports Head
@Officer in Charge
@Faculty in Charge
@E-Sports Committee
@Team roles…
@Player
@Applicant
@Audience
@everyone
```
The **bot's integration role must be positioned above every role it manages** or Discord will refuse role assignment. Setup checks and warns if the bot role is too low.

## Reconciliation
On startup and via `/system health`, the bot loads `discord_resources`, verifies each `discord_id` still exists, marks missing ones `MISSING`, and offers to recreate them (idempotent). Team channels/roles can be rebuilt from `teams`/`team_members`.

# Command Specification

Format: `command` — authority — allowed states — description. Inputs use Discord slash options / modals / buttons. Every command: (1) checks authorization (permissions.md), (2) checks event state (state-machine.md), (3) performs the action via a service, (4) writes an audit entry, (5) replies (ephemeral for private/staff data).

Slash commands are grouped; sensitive commands use `default_member_permissions` to hide from ordinary users (defense in depth only).

## Setup
| Command | Auth | States | Description |
|---|---|---|---|
| `/setup preview` | Head/Admin | DRAFT,SETUP | Show detected server; list preserve vs remove; resource-limit projection. No changes. |
| `/setup backup` | Head/Admin | SETUP | Export current server structure to JSON. |
| `/setup confirm <token>` | Head/Admin | SETUP | Requires token from preview; performs destructive build; idempotent/resumable. |
| `/setup status` | Staff | any | Show setup progress + any MISSING resources. |

## Event
| `/event create` | Head | DRAFT | Launch config wizard (name, year, school, domain, tz, cleanup policy). |
| `/event configure` | Head | DRAFT..APPLICATIONS_OPEN | Add/edit games, roster sizes, deadlines, dates. |
| `/event advance` | Head | any (fwd) | Advance to next lifecycle state (guarded). |
| `/event rollback <reason>` | Head | any | Step back one state (audited). |
| `/event status` | Staff | any | Current event + state + key counts. |
| `/event archive` | Head | CLEANUP | Move to ARCHIVED. |

## Applications
| `/applications` | Staff | any | List/filter applications (paginated, ephemeral). |
| `/application view <id>` | Staff | any | Full application detail (ephemeral). |
| `/application approve <id>` | Staff | APPLICATIONS_OPEN..TEAM_FORMATION | Approve; notify applicant; grant Applicant privileges. |
| `/application reject <id> <reason>` | Staff | same | Reject with required reason; notify. |
| `/application withdraw [<id>]` | Applicant(own)/Staff | before assign | Withdraw. |
| `/application correct <id>` | Staff | any | Fix field(s) with reason (audited). |
| Button **Apply as Player** | Applicant | APPLICATIONS_OPEN+window | Game select → modal(s) → submit PENDING. |

## Teams
| `/team view [<team>]` | anyone (own/public) | any | Roster + status. |
| `/team create` (or button) | Applicant(approved) | TEAM_FORMATION | Name+logo+game → create team + Discord resources + forum post. |
| `/team rename <name>` | Leader/Staff | ≤REGISTRATION_LOCKED | Rename (sanitized); update role/channel/forum. |
| `/team logo` | Leader/Staff | ≤REGISTRATION_LOCKED | Replace logo (validated upload). |
| `/team kick <member> <reason>` | Leader/Staff | ≤REGISTRATION_LOCKED | Remove member; revert their application. |
| `/team leave` | Team member | ≤REGISTRATION_LOCKED | Leave (leader must transfer first unless last member → disband). |
| `/team transfer <member>` | Leader/Staff | ≤REGISTRATION_LOCKED | Transfer leadership. |
| `/team disband [<team>] <reason>` | Leader/Staff | any | Disband; free members; schedule resource cleanup. |
| `/team correct <team>` | Staff | any | Admin correction incl. game change (audited). |
| Button **Join Team** | Applicant(approved) | TEAM_FORMATION | Join if not full + eligible. |
| Button **Find a Team** | Applicant(approved) | TEAM_FORMATION | LFT profile form → recruitment forum. |

## Recruitment
| `/recruit <player>` (or button) | Leader | TEAM_FORMATION | Send recruitment request (expires per config). |
| Button **Accept/Decline** | Targeted applicant | before expiry | Resolve request. |
| `/recruit cancel <id>` | Leader | before resolve | Cancel outstanding request. |

## Tryout
| `/tryout status` | Staff | any | Per-game readiness table + overall READY/NOT READY. |
| `/tryout checkin` | Staff / team member | PRE_TRYOUT | Open/manage check-in; team members self-check-in. |
| `/tryout start` | Head/Committee | PRE_TRYOUT | Validate → create match voice channels (floor(N/2), odd team waits) → TRYOUT_ACTIVE. |
| `/tryout reschedule` | Staff | ≤PRE_TRYOUT | Change date/time; edit announcement. |
| `/tryout end` | Head/Committee | TRYOUT_ACTIVE | Champion selection per game → grant Player role to champions → announce → export → RESULTS. |

## Mechanics
| `/mechanics create <game>` | Staff | SETUP..PRE_TRYOUT | Build mechanics (guided → embed). |
| `/mechanics edit <game>` | Staff | same | New version. |
| `/mechanics publish <game>` | Staff | same | Publish current version to game #mechanics. |
| `/mechanics view <game>` | anyone | any | Show current mechanics. |

## Matches
| `/match create` | Staff | TRYOUT_ACTIVE | Manual match (team A/B). |
| `/match start <id>` | Staff | TRYOUT_ACTIVE | READY→LIVE. |
| `/match battle-ended` | Staff | TRYOUT_ACTIVE | Game, A, B, winner, screenshot, notes → publish + save. |
| `/match correct <id> <reason>` | Staff | any | Correct a result (audited). |
| `/match cancel <id> <reason>` | Staff | TRYOUT_ACTIVE | Cancel. |

## Exports
| `/export applicants` | Staff | any | CSV. |
| `/export teams` | Staff | any | CSV. |
| `/export members` | Staff | any | Normalized CSV. |
| `/export matches` | Staff | any | CSV. |
| `/export checkins` | Staff | any | CSV. |
| `/export logs` | Staff | any | Audit CSV. |
| `/export all` | Staff | any | All of the above (zipped). |

## Staff / System
| `/staff add <user> <role>` | Head | any | Assign staff role. |
| `/staff remove <user>` | Head | any | Remove staff role. |
| `/staff list` | Staff | any | List staff assignments. |
| `/system status` | Staff | any | Observability report (see observability in requirements FR-24). |
| `/system health` | Staff | any | Reconcile Discord resources vs DB; report/repair MISSING. |
| `/system backup` | Head | any | `pg_dump` the Supabase DB to a timestamped local file. |
| `/system restore <file>` | Head | any | Guarded restore via `pg_restore`/`psql` (confirm; makes safety backup first). |
| `/system cleanup` | Head | RESULTS | Confirmed deletion of temporary resources (keeps DB + champions). |

## Interaction components summary
- **Verification:** handled by an external verification bot (OQ-2). Our bot listens for the configured verified role and grants Audience — no Verify button of our own (the external bot provides its own UI).
- **Buttons:** Apply as Player, Create Team, Find a Team, Join Team, Recruit Player, Accept, Decline, Setup Confirm, Cleanup Confirm.
- **Modals:** Application (multi-step), Team create, Find-a-Team profile, Rejection reason, Mechanics builder, Battle result.
- **Select menus:** Game selection, champion selection, member selection.
- All persistent-view components use `custom_id` encoding the entity IDs so they survive bot restarts (discord.py persistent views).

"""Live event dashboard: per-game team/applicant counts, tryout date, and phase.

``refresh`` recomputes the numbers and edits a single pinned message in
#dashboard (posting it the first time). It is best-effort: any Discord/DB error
is logged and swallowed so it can never break the command that triggered it.
Callers fire it after a count changes; a periodic loop also calls it as a
safety net (see cogs/dashboard.py).
"""

from __future__ import annotations

import logging

import discord
from sqlalchemy import func, select

from ..domain.enums import ApplicationStatus, ResourceOwnerType, ResourceType, TeamStatus
from ..models import Application, Team
from ..repositories.core import EventRepository, GameRepository
from ..infra import db
from ..infra.resource_repository import SqlResourceRepository

log = logging.getLogger(__name__)

# Applicants shown on the dashboard = people accepted into the applicant pool.
_APPLICANT_STATUSES = (ApplicationStatus.APPROVED, ApplicationStatus.ASSIGNED_TO_TEAM)

_PHASE_LABELS: dict[str, str] = {
    "DRAFT": "📝 Draft (not started)",
    "SETUP": "🏗️ Setup",
    "APPLICATIONS_OPEN": "📨 Applications open",
    "TEAM_FORMATION": "👥 Team formation",
    "REGISTRATION_LOCKED": "🔒 Registration locked",
    "PRE_TRYOUT": "⏳ Pre-tryout",
    "TRYOUT_ACTIVE": "🎮 Tryouts live",
    "RESULTS": "🏆 Results",
    "CLEANUP": "🧹 Cleanup",
    "ARCHIVED": "📦 Archived",
}


def _phase_label(state) -> str:
    return _PHASE_LABELS.get(str(state), str(state))


async def _counts_by_game(session, event_id: int) -> tuple[dict[int, int], dict[int, int]]:
    """Return ({game_id: active_teams}, {game_id: approved_applicants})."""
    team_rows = await session.execute(
        select(Team.game_id, func.count())
        .where(Team.event_id == event_id, Team.status != TeamStatus.DISBANDED)
        .group_by(Team.game_id)
    )
    teams = {gid: n for gid, n in team_rows.all()}
    app_rows = await session.execute(
        select(Application.game_id, func.count())
        .where(
            Application.event_id == event_id,
            Application.status.in_(_APPLICANT_STATUSES),
        )
        .group_by(Application.game_id)
    )
    applicants = {gid: n for gid, n in app_rows.all()}
    return teams, applicants


def build_embed(
    event_name: str, state, tryout_at, games: list[tuple[int, str]],
    teams: dict[int, int], applicants: dict[int, int],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"📊 {event_name} — Live Dashboard",
        colour=discord.Colour.blurple(),
    )
    embed.add_field(name="Current phase", value=_phase_label(state), inline=True)
    if tryout_at is not None:
        ts = int(tryout_at.timestamp())
        embed.add_field(name="Tryout date", value=f"<t:{ts}:F>\n(<t:{ts}:R>)", inline=True)
    else:
        embed.add_field(name="Tryout date", value="🗓️ TBA", inline=True)

    if games:
        lines = []
        for gid, name in games:
            lines.append(
                f"**{name}** — 👥 {teams.get(gid, 0)} teams · 🙋 {applicants.get(gid, 0)} applicants"
            )
        total_teams = sum(teams.values())
        total_apps = sum(applicants.values())
        lines.append(f"\n**Total** — 👥 {total_teams} teams · 🙋 {total_apps} applicants")
        embed.add_field(name="Teams & applicants", value="\n".join(lines)[:1024], inline=False)
    else:
        embed.add_field(name="Teams & applicants", value="No games configured yet.", inline=False)

    embed.set_footer(text="Updates automatically as teams form and applications are approved.")
    embed.timestamp = discord.utils.utcnow()
    return embed


async def _move_category_to_top(guild: discord.Guild, channel: discord.abc.GuildChannel) -> None:
    """Keep the dashboard pinned above everything else (best-effort)."""
    category = getattr(channel, "category", None)
    try:
        if category is not None and category.position != 0:
            await category.edit(position=0)
        elif category is None and getattr(channel, "position", 0) != 0:
            await channel.edit(position=0)
    except discord.HTTPException as exc:
        log.debug("Could not reposition dashboard: %s", exc)


async def refresh(guild: discord.Guild, event_id: int | None = None) -> None:
    """Recompute and post/edit the dashboard for the guild's active event."""
    try:
        async with db.session_scope() as s:
            events = EventRepository(s)
            event = (
                await events.get(event_id) if event_id is not None
                else await events.get_active(guild.id)
            )
            if event is None:
                return
            games = [
                (g.id, g.name) for g in await GameRepository(s).list_games_for_event(event.id)
            ]
            teams, applicants = await _counts_by_game(s, event.id)
            embed = build_embed(
                f"{event.name} {event.year}", event.state, event.tryout_at,
                games, teams, applicants,
            )

            repo = SqlResourceRepository(s)
            channel_id = await repo.get(
                event.id, ResourceOwnerType.SYSTEM, None, "ch_dashboard"
            )
            channel_id = channel_id.discord_id if channel_id else None
            msg_row = await repo.get(
                event.id, ResourceOwnerType.SYSTEM, None, "dashboard_message"
            )
            msg_id = msg_row.discord_id if msg_row else None
            msg_row_id = msg_row.id if msg_row else None
            event_id_final = event.id

        channel = guild.get_channel(channel_id) if channel_id else None
        if channel is None:
            return  # dashboard channel not built yet — run /setup confirm
        await _move_category_to_top(guild, channel)

        edited = False
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=embed)
                edited = True
            except discord.HTTPException:
                edited = False
        if not edited:
            msg = await channel.send(embed=embed)
            async with db.session_scope() as s:
                repo = SqlResourceRepository(s)
                if msg_row_id is not None:
                    await repo.set_created(msg_row_id, msg.id)
                else:
                    row = await repo.add_pending(
                        event_id_final, ResourceType.MESSAGE, ResourceOwnerType.SYSTEM, None,
                        "dashboard_message",
                    )
                    await repo.set_created(row.id, msg.id)
    except Exception:  # noqa: BLE001 - dashboard must never break its caller
        log.exception("Dashboard refresh failed for guild %s", guild.id)

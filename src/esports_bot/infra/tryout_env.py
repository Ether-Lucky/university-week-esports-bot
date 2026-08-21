"""Tryout environment: per-game tryout channels + focus mode.

At ``/tryout start`` each game gets a dedicated **tryout category** holding a
shared tryout text channel plus a text + voice channel per competing team, and
every non-tryout channel is hidden from participants ("focus mode"). ``/tryout
end`` restores the normal channel visibility by re-applying the permission matrix.
"""

from __future__ import annotations

import logging

import discord

from ..domain.enums import ResourceOwnerType
from ..domain.server_blueprint import slug
from ..infra import db
from ..infra.discord_gateway import DiscordResourceGateway
from ..infra.discord_resources import DiscordResourceService
from ..infra.resource_repository import SqlResourceRepository
from ..models import Team
from ..repositories.core import GameRepository

log = logging.getLogger(__name__)

_STAFF_PURPOSES = ("role_head", "role_committee", "role_oic", "role_fic")
_PARTICIPANT_BASE = ("role_audience", "role_applicant", "role_player")

# Participant-visible channels hidden during the tryout. Mechanics, battle-results,
# and the tournament (Challonge/bracket) channel stay visible — teams need those;
# staff channels participants can't see anyway.
_HIDE_SYSTEM = ("ch_verify", "ch_rules", "ch_info", "ch_apply")
_HIDE_GAME = (
    "game_general", "game_apply_info", "game_team_forum",
    "game_lft_forum", "game_players",
)


async def _set(channel, target, **flags) -> None:
    try:
        await channel.set_permissions(target, **flags)
    except discord.HTTPException as exc:
        log.debug("set_permissions failed on %s: %s", getattr(channel, "id", "?"), exc)


async def provision_tryout_channels(guild, event_id: int, teams_by_game, games) -> int:
    """Build each game's tryout category (shared text + per-team text/voice).

    ``teams_by_game`` maps game_id -> iterable of team ids. Idempotent: existing
    channels are reused and their permissions re-applied. Returns the number of
    team voice channels provisioned.
    """
    created = 0
    async with db.session_scope() as s:
        resources = DiscordResourceService(
            DiscordResourceGateway(guild), SqlResourceRepository(s)
        )
        roster_by_game = {
            eg.game_id: eg.roster_size
            for eg in await GameRepository(s).list_for_event(event_id)
        }
        role_map = await resources.role_map(event_id)
        staff_ids = [role_map[k] for k in _STAFF_PURPOSES if k in role_map]

        for game_id, team_ids in teams_by_game.items():
            team_ids = set(team_ids)
            if not team_ids:
                continue
            gname = games.get(game_id, "game")
            g_slug = slug(gname)
            limit = roster_by_game.get(game_id) or 0
            game_role = guild.get_role(role_map.get(f"game_role:{g_slug}", 0))

            cat_id = await resources.ensure_category(
                event_id, ResourceOwnerType.GAME, None,
                f"cat_tryout:{g_slug}", f"{gname.upper()} · TRYOUT",
            )
            cat = guild.get_channel(cat_id)
            if cat:
                await _set(cat, guild.default_role, view_channel=True)

            # Shared per-game tryout text channel: that game's players post, all watch.
            shared_id = await resources.ensure_text_channel(
                event_id, ResourceOwnerType.GAME, None,
                f"game_tryout_text:{g_slug}", f"{g_slug}-tryout-chat", category_id=cat_id,
            )
            shared = guild.get_channel(shared_id)
            if shared:
                await _set(shared, guild.default_role, view_channel=True,
                           send_messages=False, add_reactions=False)
                if game_role:
                    await _set(shared, game_role, view_channel=True,
                               send_messages=True, add_reactions=True)
                for sid in staff_ids:
                    if (sr := guild.get_role(sid)):
                        await _set(shared, sr, view_channel=True,
                                   send_messages=True, add_reactions=True)

            for tid in sorted(team_ids):
                team = await s.get(Team, tid)
                tname = slug(team.name) if team else f"team-{tid}"
                trole = guild.get_role(
                    await resources.find(event_id, ResourceOwnerType.TEAM, tid, f"team_role:{tid}")
                    or 0
                )
                # Per-team text channel.
                txt_id = await resources.ensure_text_channel(
                    event_id, ResourceOwnerType.TEAM, tid,
                    f"team_tryout_text:{tid}", f"{g_slug}-{tname}"[:100], category_id=cat_id,
                )
                if (txt := guild.get_channel(txt_id)):
                    await _apply_team_perms(guild, txt, trole, staff_ids, voice=False)
                # Per-team voice channel (capped to roster size; staff bypass).
                vc_id = await resources.ensure_voice_channel(
                    event_id, ResourceOwnerType.TEAM, tid,
                    f"tryout_voice:{tid}", f"{g_slug}-{tname}-voice"[:100], category_id=cat_id,
                )
                if (vc := guild.get_channel(vc_id)):
                    try:
                        await vc.edit(user_limit=limit if 0 < limit <= 99 else 0)
                    except discord.HTTPException:
                        pass
                    await _apply_team_perms(guild, vc, trole, staff_ids, voice=True)
                    created += 1
    return created


async def _apply_team_perms(guild, channel, team_role, staff_ids, *, voice: bool) -> None:
    """Team + staff get full access.

    The team's **voice** channel is spectator-visible (everyone sees it, can't join/
    talk/react). The team's **text** channel is private — hidden from everyone but
    the team and staff.
    """
    if voice:
        await _set(channel, guild.default_role, view_channel=True, connect=False,
                   send_messages=False, add_reactions=False)
    else:
        await _set(channel, guild.default_role, view_channel=False)
    if team_role:
        team = {"view_channel": True, "send_messages": True, "add_reactions": True}
        if voice:
            team["connect"] = True
        await _set(channel, team_role, **team)
    for sid in staff_ids:
        sr = guild.get_role(sid)
        if sr:
            staff = {"view_channel": True, "send_messages": True, "add_reactions": True}
            if voice:
                staff["connect"] = True
                staff["move_members"] = True
            await _set(channel, sr, **staff)


async def set_focus(guild, event_id: int, hide: bool) -> int:
    """Hide (or restore) every non-tryout channel for participants."""
    async with db.session_scope() as s:
        resources = DiscordResourceService(
            DiscordResourceGateway(guild), SqlResourceRepository(s)
        )
        games = await GameRepository(s).list_games_for_event(event_id)
        shorts = [slug(g.name) for g in games]
        role_map = await resources.role_map(event_id)
        participant_ids: list[int] = [role_map[p] for p in _PARTICIPANT_BASE if p in role_map]
        participant_ids += [rid for k, rid in role_map.items() if k.startswith("game_role:")]
        targets: list[int] = []
        if hide:
            for p in _HIDE_SYSTEM:
                cid = await resources.find(event_id, ResourceOwnerType.SYSTEM, None, p)
                if cid:
                    targets.append(cid)
            for sh in shorts:
                for p in _HIDE_GAME:
                    cid = await resources.find(event_id, ResourceOwnerType.GAME, None, f"{p}:{sh}")
                    if cid:
                        targets.append(cid)

    if not hide:
        # Restore: re-apply the canonical permission matrix to every blueprint channel.
        from ..services.setup_service import SetupService

        async with db.session_scope() as s:
            gw = DiscordResourceGateway(guild)
            applied, _failed = await SetupService(
                DiscordResourceService(gw, SqlResourceRepository(s)), gw
            ).apply_permissions(event_id, shorts)
        return applied

    roles = [r for rid in participant_ids if (r := guild.get_role(rid))]
    count = 0
    for cid in targets:
        channel = guild.get_channel(cid)
        if channel is None:
            continue
        overwrites = dict(channel.overwrites)
        for role in roles:
            po = overwrites.get(role) or discord.PermissionOverwrite()
            po.view_channel = False
            overwrites[role] = po
        try:
            await channel.edit(overwrites=overwrites)
            count += 1
        except discord.HTTPException as exc:
            log.debug("focus hide failed on %s: %s", cid, exc)
    return count

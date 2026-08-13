"""Recruitment cog — looking-for-team posts and recruit requests."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import EsportsBot
from ..domain.enums import ResourceOwnerType
from ..domain.server_blueprint import slug
from ..infra import db
from ..infra.discord_gateway import DiscordResourceGateway
from ..infra.discord_resources import DiscordResourceService
from ..infra.resource_repository import SqlResourceRepository
from ..models import Game
from ..repositories.core import EventRepository, UserRepository
from ..repositories.teams import TeamRepository
from ..services.errors import ServiceError
from ..services.recruitment_service import RecruitmentService


class RecruitButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"esports:recruit:(?P<uid>\d+)",
):
    """On a looking-for-team post: a team leader recruits this player."""

    def __init__(self, target_discord_id: int) -> None:
        self.target_id = target_discord_id
        super().__init__(
            discord.ui.Button(
                label="Recruit Player", style=discord.ButtonStyle.primary,
                custom_id=f"esports:recruit:{target_discord_id}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(int(match["uid"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        target_member = interaction.guild.get_member(self.target_id)
        target_name = str(target_member) if target_member else f"user {self.target_id}"
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            leader = await UserRepository(s).get_or_create(
                interaction.user.id, str(interaction.user)
            )
            membership = await TeamRepository(s).active_membership(event.id, leader.id)
            if membership is None:
                await interaction.followup.send(
                    "You must lead a team to recruit players.", ephemeral=True
                )
                return
            try:
                request = await RecruitmentService(s).recruit(
                    event_id=event.id, team_id=membership.team_id,
                    target_discord_id=self.target_id, target_username=target_name,
                    requester_discord_id=interaction.user.id,
                    requester_username=str(interaction.user),
                    timeout_minutes=interaction.client.settings.recruit_timeout_minutes,
                )
                request_id = request.id
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        if target_member:
            try:
                await target_member.send(
                    f"You've been recruited! Use `/recruit accept {request_id}` or "
                    f"`/recruit decline {request_id}`."
                )
            except discord.HTTPException:
                pass
        await interaction.followup.send(
            f"Recruitment request #{request_id} sent to {target_name}.", ephemeral=True
        )


class RecruitmentCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    recruit = app_commands.Group(name="recruit", description="Recruitment.", guild_only=True)

    @app_commands.command(
        name="findteam", description="Post yourself on the looking-for-team forum."
    )
    @app_commands.guild_only()
    @app_commands.describe(
        ign="Your in-game name", role="Your main role / position", note="Optional note"
    )
    async def findteam(
        self, interaction: discord.Interaction, ign: str, role: str, note: str | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            try:
                post = await RecruitmentService(s).create_lft_post(
                    event_id=event.id, user_discord_id=interaction.user.id,
                    username=str(interaction.user), ign=ign, main_role=role,
                )
                game = await s.get(Game, post.game_id)
                game_name, game_slug, event_id = game.name, slug(game.name), event.id
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            forum_id = await resources.find(
                event_id, ResourceOwnerType.GAME, None, f"game_lft_forum:{game_slug}"
            )
        forum = interaction.guild.get_channel(forum_id) if forum_id else None
        thread_mention = None
        if forum is not None and isinstance(forum, discord.ForumChannel):
            embed = discord.Embed(title=f"LFT: {ign}", colour=discord.Colour.green())
            embed.add_field(name="Game", value=game_name, inline=True)
            embed.add_field(name="Main role", value=role, inline=True)
            if note:
                embed.add_field(name="Note", value=note[:1024], inline=False)
            embed.add_field(
                name="📸 Screenshots",
                value=(
                    f"{interaction.user.mention}, reply to this post with screenshots of your "
                    "**in-game profile** and **stats** so team leaders can evaluate you."
                ),
                inline=False,
            )
            embed.set_footer(text=f"{interaction.user.display_name} is looking for a team")
            view = discord.ui.View(timeout=None)
            view.add_item(RecruitButton(interaction.user.id))
            created = await forum.create_thread(
                name=f"{ign} — {role}"[:100], embed=embed, view=view
            )
            thread_mention = created.thread.mention
        where = f" Add your profile & stats screenshots by replying here: {thread_mention}" \
            if thread_mention else ""
        await interaction.followup.send(
            f"✅ Posted you to the looking-for-team forum!{where}",
            ephemeral=True,
        )

    @recruit.command(name="player", description="Recruit a player to your team (leader).")
    async def player(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            membership = await TeamRepository(s).active_membership(
                event.id, (await _uid(s, interaction.user.id, str(interaction.user)))
            )
            if membership is None:
                await interaction.followup.send("You are not on a team.", ephemeral=True)
                return
            try:
                request = await RecruitmentService(s).recruit(
                    event_id=event.id, team_id=membership.team_id,
                    target_discord_id=member.id, target_username=str(member),
                    requester_discord_id=interaction.user.id,
                    requester_username=str(interaction.user),
                    timeout_minutes=self.bot.settings.recruit_timeout_minutes,
                )
                request_id = request.id
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        try:
            await member.send(
                f"You've been recruited! Use `/recruit accept {request_id}` or "
                f"`/recruit decline {request_id}` (expires soon)."
            )
        except discord.HTTPException:
            pass
        await interaction.followup.send(f"Recruitment request #{request_id} sent.", ephemeral=True)

    @recruit.command(name="accept", description="Accept a recruitment request.")
    async def accept(self, interaction: discord.Interaction, request_id: int) -> None:
        await self._resolve(interaction, request_id, accept=True)

    @recruit.command(name="decline", description="Decline a recruitment request.")
    async def decline(self, interaction: discord.Interaction, request_id: int) -> None:
        await self._resolve(interaction, request_id, accept=False)

    async def _resolve(self, interaction, request_id: int, *, accept: bool) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            svc = RecruitmentService(s)
            try:
                if accept:
                    await svc.accept(
                        event_id=event.id, request_id=request_id,
                        actor_discord_id=interaction.user.id,
                        actor_username=str(interaction.user),
                    )
                    msg = "✅ You joined the team!"
                else:
                    await svc.decline(
                        event_id=event.id, request_id=request_id,
                        actor_discord_id=interaction.user.id,
                        actor_username=str(interaction.user),
                    )
                    msg = "Declined."
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        await interaction.followup.send(msg, ephemeral=True)


async def _uid(session, discord_id: int, username: str) -> int:
    from ..repositories.core import UserRepository

    user = await UserRepository(session).get_or_create(discord_id, username)
    return user.id


async def setup(bot: EsportsBot) -> None:
    bot.add_dynamic_items(RecruitButton)  # persistent Recruit buttons on LFT posts
    await bot.add_cog(RecruitmentCog(bot))

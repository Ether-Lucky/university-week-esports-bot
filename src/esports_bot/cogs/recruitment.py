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
from .checks import is_staff


async def _disable_message(message: discord.Message | None, note: str) -> None:
    """Remove the buttons on a request DM once it's been acted on (best-effort)."""
    if message is None:
        return
    try:
        await message.edit(content=note, view=None)
    except discord.HTTPException:
        pass


async def _finalize_accept(client, info) -> None:
    """After a request is accepted: grant the team role, refresh the forum, close the
    joining player's LFT post, and DM them."""
    guild = client.get_guild(info.guild_id)
    if guild is None:
        return
    from .teams import grant_team_role, refresh_team_forum

    await grant_team_role(guild, info.event_id, info.team_id, info.joining_discord_id)
    await refresh_team_forum(guild, info.event_id, info.team_id)
    async with db.session_scope() as s:
        try:
            thread_id = await RecruitmentService(s).cancel_lft(
                event_id=info.event_id, target_discord_id=info.joining_discord_id,
                target_username=info.joining_name, actor_discord_id=info.joining_discord_id,
                actor_username=info.joining_name,
            )
        except ServiceError:
            thread_id = None
    if thread_id:
        thread = guild.get_thread(thread_id)
        if thread is None:
            try:
                thread = await guild.fetch_channel(thread_id)
            except discord.HTTPException:
                thread = None
        if thread is not None:
            try:
                await thread.delete()
            except discord.HTTPException:
                pass
    member_user = client.get_user(info.joining_discord_id)
    if member_user:
        try:
            await member_user.send(
                f"🎉 You've joined **{info.team_name}**! Check your team channels."
            )
        except discord.HTTPException:
            pass


class RejectReasonModal(discord.ui.Modal, title="Reject — reason"):
    reason = discord.ui.TextInput(
        label="Reason", style=discord.TextStyle.paragraph, max_length=500, required=True
    )

    def __init__(self, request_id: int, source_message: discord.Message | None = None) -> None:
        super().__init__()
        self.request_id = request_id
        self.source_message = source_message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        async with db.session_scope() as s:
            try:
                info = await RecruitmentService(s).reject_request(
                    request_id=self.request_id, actor_discord_id=interaction.user.id,
                    actor_username=str(interaction.user), reason=self.reason.value,
                )
            except (ServiceError, ValueError) as exc:
                await _disable_message(self.source_message, f"⚠️ {exc}")
                await interaction.followup.send(f"❌ {exc}")
                return
        requester = interaction.client.get_user(info.requester_discord_id)
        if requester:
            kind_word = "join request" if info.kind == "JOIN" else "recruitment offer"
            try:
                await requester.send(
                    f"❌ Your {kind_word} for **{info.team_name}** was rejected.\n"
                    f"Reason: {info.reason}"
                )
            except discord.HTTPException:
                pass
        await _disable_message(
            self.source_message, f"❌ You rejected this request for **{info.team_name}**."
        )
        await interaction.followup.send("Rejected — the requester was notified with your reason.")


class AcceptReqButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"esports:reqaccept:(?P<rid>\d+)"
):
    def __init__(self, request_id: int) -> None:
        self.rid = request_id
        super().__init__(
            discord.ui.Button(
                label="Accept", style=discord.ButtonStyle.success,
                custom_id=f"esports:reqaccept:{request_id}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(int(match["rid"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        async with db.session_scope() as s:
            try:
                info = await RecruitmentService(s).accept_request(
                    request_id=self.rid, actor_discord_id=interaction.user.id,
                    actor_username=str(interaction.user),
                )
            except (ServiceError, ValueError) as exc:
                await _disable_message(interaction.message, f"⚠️ {exc}")
                await interaction.followup.send(f"❌ {exc}")
                return
        await _finalize_accept(interaction.client, info)
        await _disable_message(
            interaction.message,
            f"✅ You accepted — **{info.joining_name}** is now on **{info.team_name}**.",
        )
        await interaction.followup.send(
            f"✅ Accepted — **{info.joining_name}** is now on **{info.team_name}**."
        )


class RejectReqButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"esports:reqreject:(?P<rid>\d+)"
):
    def __init__(self, request_id: int) -> None:
        self.rid = request_id
        super().__init__(
            discord.ui.Button(
                label="Reject", style=discord.ButtonStyle.danger,
                custom_id=f"esports:reqreject:{request_id}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(int(match["rid"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            RejectReasonModal(self.rid, source_message=interaction.message)
        )


async def send_request_dm(client, recipient_discord_id: int, embed, request_id: int) -> bool:
    """DM the decider with Accept/Reject buttons. Returns False if the DM failed."""
    user = client.get_user(recipient_discord_id)
    if user is None:
        try:
            user = await client.fetch_user(recipient_discord_id)
        except discord.HTTPException:
            return False
    view = discord.ui.View(timeout=None)
    view.add_item(AcceptReqButton(request_id))
    view.add_item(RejectReqButton(request_id))
    try:
        await user.send(embed=embed, view=view)
        return True
    except discord.HTTPException:
        return False


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
                team = await TeamRepository(s).get(membership.team_id)
                team_name, team_id = team.name, team.id
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            forum_thread_id = await resources.find(
                event.id, ResourceOwnerType.TEAM, team_id, f"team_forum_post:{team_id}"
            )
        embed = discord.Embed(
            title="📣 Recruitment Offer", colour=discord.Colour.blurple(),
            description=f"Team **{team_name}** wants to recruit you!",
        )
        if forum_thread_id:
            link = f"https://discord.com/channels/{interaction.guild_id}/{forum_thread_id}"
            embed.add_field(
                name="The team", value=f"[View {team_name}'s post]({link})", inline=False
            )
        embed.set_footer(text="Accept to join, or Reject with a reason.")
        delivered = await send_request_dm(interaction.client, self.target_id, embed, request_id)
        await interaction.followup.send(
            f"Recruitment offer sent to {target_name}." if delivered
            else f"Offer created but couldn't DM them (request #{request_id}).",
            ephemeral=True,
        )


class RecruitmentCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    recruit = app_commands.Group(name="recruit", description="Recruitment.", guild_only=True)
    lft = app_commands.Group(
        name="lft", description="Looking-for-team posts.", guild_only=True
    )

    async def _delete_thread(self, guild: discord.Guild, thread_id: int | None) -> None:
        if thread_id is None:
            return
        thread = guild.get_thread(thread_id)
        if thread is None:
            try:
                thread = await guild.fetch_channel(thread_id)
            except discord.HTTPException:
                return
        try:
            await thread.delete()
        except discord.HTTPException:
            pass

    @lft.command(name="cancel", description="Cancel your own looking-for-team post.")
    async def cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            try:
                thread_id = await RecruitmentService(s).cancel_lft(
                    event_id=event.id, target_discord_id=interaction.user.id,
                    target_username=str(interaction.user),
                    actor_discord_id=interaction.user.id,
                    actor_username=str(interaction.user),
                )
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        await self._delete_thread(interaction.guild, thread_id)
        await interaction.followup.send(
            "✅ Cancelled your looking-for-team post. You can post again with `/findteam`.",
            ephemeral=True,
        )

    @lft.command(name="delete", description="Delete a member's looking-for-team post (staff).")
    @app_commands.default_permissions(manage_guild=True)
    async def delete(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            try:
                thread_id = await RecruitmentService(s).cancel_lft(
                    event_id=event.id, target_discord_id=member.id,
                    target_username=str(member),
                    actor_discord_id=interaction.user.id,
                    actor_username=str(interaction.user), staff=True,
                )
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        await self._delete_thread(interaction.guild, thread_id)
        await interaction.followup.send(
            f"Deleted {member.mention}'s looking-for-team post. They can resubmit.",
            ephemeral=True,
        )

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
                post_id = post.id
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
            async with db.session_scope() as s:
                await RecruitmentService(s).set_forum_post(post_id, created.thread.id)
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
            leader = await UserRepository(s).get_or_create(
                interaction.user.id, str(interaction.user)
            )
            membership = await TeamRepository(s).active_membership(event.id, leader.id)
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
                team = await TeamRepository(s).get(membership.team_id)
                team_name, team_id = team.name, team.id
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            forum_thread_id = await resources.find(
                event.id, ResourceOwnerType.TEAM, team_id, f"team_forum_post:{team_id}"
            )
        embed = discord.Embed(
            title="📣 Recruitment Offer", colour=discord.Colour.blurple(),
            description=f"Team **{team_name}** wants to recruit you!",
        )
        if forum_thread_id:
            link = f"https://discord.com/channels/{interaction.guild_id}/{forum_thread_id}"
            embed.add_field(
                name="The team", value=f"[View {team_name}'s post]({link})", inline=False
            )
        embed.set_footer(text="Accept to join, or Reject with a reason.")
        delivered = await send_request_dm(interaction.client, member.id, embed, request_id)
        await interaction.followup.send(
            f"Recruitment offer sent to {member.mention}." if delivered
            else f"Offer created but couldn't DM them (request #{request_id}).",
            ephemeral=True,
        )

    @recruit.command(name="accept", description="Accept a request (fallback for the DM button).")
    async def accept(self, interaction: discord.Interaction, request_id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            try:
                info = await RecruitmentService(s).accept_request(
                    request_id=request_id, actor_discord_id=interaction.user.id,
                    actor_username=str(interaction.user),
                )
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        await _finalize_accept(interaction.client, info)
        await interaction.followup.send(
            f"✅ Accepted — **{info.joining_name}** is now on **{info.team_name}**.",
            ephemeral=True,
        )

    @recruit.command(name="decline", description="Decline a request with a reason.")
    async def decline(
        self, interaction: discord.Interaction, request_id: int, reason: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            try:
                info = await RecruitmentService(s).reject_request(
                    request_id=request_id, actor_discord_id=interaction.user.id,
                    actor_username=str(interaction.user), reason=reason,
                )
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        requester = interaction.client.get_user(info.requester_discord_id)
        if requester:
            try:
                await requester.send(
                    f"❌ Your request for **{info.team_name}** was rejected. Reason: {info.reason}"
                )
            except discord.HTTPException:
                pass
        await interaction.followup.send("Rejected — the requester was notified.", ephemeral=True)


async def setup(bot: EsportsBot) -> None:
    bot.add_dynamic_items(RecruitButton, AcceptReqButton, RejectReqButton)
    await bot.add_cog(RecruitmentCog(bot))

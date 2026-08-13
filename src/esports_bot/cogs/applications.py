"""Applications cog — apply flow (button -> game select -> modal) + staff review."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import EsportsBot
from ..domain.enums import ApplicationStatus, ResourceOwnerType
from ..domain.server_blueprint import slug
from ..infra import db
from ..infra.discord_gateway import DiscordResourceGateway
from ..infra.discord_resources import DiscordResourceService
from ..infra.resource_repository import SqlResourceRepository
from ..repositories.applications import ApplicationRepository
from ..repositories.core import EventRepository, GameRepository
from ..services.application_service import ApplicationService
from ..services.errors import ServiceError
from .checks import is_staff

log = logging.getLogger(__name__)


class ApplicationModal(discord.ui.Modal):
    def __init__(self, bot: EsportsBot, event_id: int, game_id: int, game_name: str) -> None:
        super().__init__(title=f"Apply — {game_name}"[:45])
        self.bot = bot
        self.event_id = event_id
        self.game_id = game_id
        self.first_name = discord.ui.TextInput(label="First name", max_length=100)
        self.full_name = discord.ui.TextInput(label="Full name", max_length=200)
        self.school_email = discord.ui.TextInput(label="School email", max_length=255)
        self.year_section = discord.ui.TextInput(label="Year & section", max_length=50)
        self.facebook = discord.ui.TextInput(label="Facebook profile URL", max_length=500)
        for item in (
            self.first_name, self.full_name, self.school_email,
            self.year_section, self.facebook,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            async with db.session_scope() as s:
                app = await ApplicationService(s).submit(
                    event_id=self.event_id, game_id=self.game_id,
                    discord_user_id=interaction.user.id, username=str(interaction.user),
                    display_name=interaction.user.display_name,
                    first_name=self.first_name.value, full_name=self.full_name.value,
                    school_email=self.school_email.value, facebook_url=self.facebook.value,
                    year_section=self.year_section.value,
                )
                app_id = app.id
                full_name = app.full_name
                email = app.school_email
        except (ServiceError, ValueError) as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        await interaction.followup.send(
            "✅ Application submitted! Staff will review it. You'll be notified of the result.",
            ephemeral=True,
        )
        await self._post_review(interaction, app_id, full_name, email)

    async def _post_review(self, interaction, app_id, full_name, email) -> None:
        async with db.session_scope() as s:
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            channel_id = await resources.find(
                self.event_id, ResourceOwnerType.SYSTEM, None, "ch_application_review"
            )
        if channel_id and (channel := interaction.guild.get_channel(channel_id)):
            embed = discord.Embed(title=f"New application #{app_id}", colour=discord.Colour.gold())
            embed.add_field(name="Applicant", value=f"{interaction.user.mention} ({full_name})")
            embed.add_field(name="Email", value=email, inline=False)
            embed.set_footer(
                text=f"/application approve {app_id}  ·  /application reject {app_id} <reason>"
            )
            await channel.send(embed=embed)


class GameSelect(discord.ui.Select):
    def __init__(self, bot: EsportsBot, event_id: int, games: list[tuple[int, str]]) -> None:
        self.bot = bot
        self.event_id = event_id
        self._names = {str(gid): name for gid, name in games}
        options = [discord.SelectOption(label=name, value=str(gid)) for gid, name in games]
        super().__init__(placeholder="Choose a game to apply for…", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        game_id = int(self.values[0])
        await interaction.response.send_modal(
            ApplicationModal(self.bot, self.event_id, game_id, self._names[self.values[0]])
        )


class ApplyView(discord.ui.View):
    """Persistent apply button placed in #apply."""

    def __init__(self, bot: EsportsBot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Apply for Tryouts", style=discord.ButtonStyle.primary,
        custom_id="esports:apply:start",
    )
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.response.send_message("No active event.", ephemeral=True)
                return
            games = await GameRepository(s).list_games_for_event(event.id)
            game_pairs = [(g.id, g.name) for g in games]
            event_id = event.id
        if not game_pairs:
            await interaction.response.send_message("No games configured yet.", ephemeral=True)
            return
        view = discord.ui.View(timeout=120)
        view.add_item(GameSelect(self.bot, event_id, game_pairs))
        await interaction.response.send_message("Select a game:", view=view, ephemeral=True)


class ApplicationsCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    application = app_commands.Group(
        name="application", description="Review applications (staff).",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    async def _grant_event_role(
        self, guild: discord.Guild, event_id: int, purpose: str, discord_user_id: int
    ) -> None:
        """Grant a base event role (e.g. role_applicant) to a member."""
        async with db.session_scope() as s:
            resources = DiscordResourceService(
                DiscordResourceGateway(guild), SqlResourceRepository(s)
            )
            role_id = await resources.find(
                event_id, ResourceOwnerType.SYSTEM, None, purpose
            )
        member = guild.get_member(discord_user_id)
        role = guild.get_role(role_id) if role_id else None
        if member and role and role not in member.roles:
            try:
                await member.add_roles(role, reason="Application approved -> Applicant")
            except discord.HTTPException:
                pass

    async def _revoke_event_role(
        self, guild: discord.Guild, event_id: int, purpose: str, discord_user_id: int
    ) -> bool:
        """Remove a role from a member. Returns True if they actually had it."""
        async with db.session_scope() as s:
            resources = DiscordResourceService(
                DiscordResourceGateway(guild), SqlResourceRepository(s)
            )
            role_id = await resources.find(
                event_id, ResourceOwnerType.SYSTEM, None, purpose
            )
        member = guild.get_member(discord_user_id)
        role = guild.get_role(role_id) if role_id else None
        if member and role and role in member.roles:
            try:
                await member.remove_roles(role, reason="Switched game")
                return True
            except discord.HTTPException:
                pass
        return False

    async def _notify(self, guild: discord.Guild, discord_user_id: int, text: str) -> None:
        member = guild.get_member(discord_user_id)
        if member:
            try:
                await member.send(text)
            except discord.HTTPException:
                pass  # DMs closed — fall back handled by staff channel logs

    @application.command(name="approve", description="Approve an application.")
    async def approve(self, interaction: discord.Interaction, application_id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            try:
                app = await ApplicationService(s).approve(
                    application_id, actor_discord_id=interaction.user.id,
                    actor_username=str(interaction.user),
                )
                from ..models import Game, User
                user = await s.get(User, app.user_id)
                discord_id = user.discord_user_id
                event_id = event.id
                game = await s.get(Game, app.game_id)
                game_slug, game_name = slug(game.name), game.name
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            from ..infra.logchannel import post_log
            await post_log(
                s, interaction.guild, event.id, "applications",
                f"✅ Application #{application_id} approved",
                f"by {interaction.user.mention}", colour=discord.Colour.green(),
            )
        # Promote Audience -> Applicant, and give the per-game role for their game.
        await self._grant_event_role(interaction.guild, event_id, "role_applicant", discord_id)
        await self._grant_event_role(
            interaction.guild, event_id, f"game_role:{game_slug}", discord_id
        )
        await self._notify(
            interaction.guild, discord_id,
            f"✅ **Your application for {game_name} was approved!** You're now an Applicant.\n\n"
            "**What's next:**\n"
            "• **Create a team:** `/team create name:<your team name>` — you become the leader.\n"
            "• **Join a team:** press **Join Team** on a team's post in the team forum, "
            "or `/team join team_id:<id>`.\n"
            "• **No team yet?** `/findteam ign:<> role:<>` so leaders can recruit you.\n"
            "• **Switch game:** `/switch-game game:<name>` (before joining a team).\n\n"
            "See **#how-it-works** for the full guide. Good luck! 🎮",
        )
        await interaction.followup.send(f"Approved application #{application_id}.", ephemeral=True)

    @application.command(name="reject", description="Reject an application with a reason.")
    async def reject(
        self, interaction: discord.Interaction, application_id: int, reason: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            try:
                app = await ApplicationService(s).reject(
                    application_id, reason, actor_discord_id=interaction.user.id,
                    actor_username=str(interaction.user),
                )
                from ..models import User
                user = await s.get(User, app.user_id)
                discord_id = user.discord_user_id
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            from ..infra.logchannel import post_log
            await post_log(
                s, interaction.guild, event.id, "applications",
                f"❌ Application #{application_id} rejected",
                f"by {interaction.user.mention} — reason: {reason}",
                colour=discord.Colour.red(),
            )
        await self._notify(
            interaction.guild, discord_id, f"Your application was not accepted. Reason: {reason}"
        )
        await interaction.followup.send(f"Rejected application #{application_id}.", ephemeral=True)

    @application.command(name="list", description="List pending applications.")
    async def list_pending(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            pending = await ApplicationRepository(s).list_by_status(
                event.id, ApplicationStatus.PENDING
            )
            lines = [f"#{a.id} — {a.full_name} ({a.school_email})" for a in pending]
        await interaction.followup.send(
            "\n".join(lines) if lines else "No pending applications.", ephemeral=True
        )

    @application.command(
        name="backfill-roles",
        description="Grant Applicant + per-game roles to all already-approved applicants.",
    )
    async def backfill_roles(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from sqlalchemy import select

        from ..models import Application, Game, User

        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            role_map = await resources.role_map(event.id)
            res = await s.execute(
                select(User.discord_user_id, Game.name)
                .select_from(Application)
                .join(User, Application.user_id == User.id)
                .join(Game, Application.game_id == Game.id)
                .where(
                    Application.event_id == event.id,
                    Application.status.in_(
                        [ApplicationStatus.APPROVED, ApplicationStatus.ASSIGNED_TO_TEAM]
                    ),
                )
            )
            rows = res.all()

        applicant_role = interaction.guild.get_role(role_map.get("role_applicant", 0))
        granted = 0
        for discord_id, game_name in rows:
            member = interaction.guild.get_member(discord_id)
            if member is None:
                continue
            to_add = []
            if applicant_role and applicant_role not in member.roles:
                to_add.append(applicant_role)
            game_role = interaction.guild.get_role(role_map.get(f"game_role:{slug(game_name)}", 0))
            if game_role and game_role not in member.roles:
                to_add.append(game_role)
            if to_add:
                try:
                    await member.add_roles(*to_add, reason="Backfill approved-applicant roles")
                    granted += 1
                except discord.HTTPException:
                    pass
        await interaction.followup.send(
            f"Backfilled roles for {granted} approved applicants.", ephemeral=True
        )

    @application.command(name="post-button", description="Post the Apply button in this channel.")
    async def post_button(self, interaction: discord.Interaction) -> None:
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.response.send_message("Staff only.", ephemeral=True)
                return
        embed = discord.Embed(
            title="Tryout Applications",
            description=(
                "Press **Apply for Tryouts** to submit your application. "
                "Approved applicants can then form or join a team."
            ),
            colour=discord.Colour.blurple(),
        )
        await interaction.channel.send(embed=embed, view=ApplyView(self.bot))
        await interaction.response.send_message("Posted the apply button.", ephemeral=True)

    @app_commands.command(
        name="switch-game", description="Change which game your application is for."
    )
    @app_commands.guild_only()
    @app_commands.describe(game="The exact game name to switch your application to")
    async def switch_game(self, interaction: discord.Interaction, game: str) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            try:
                old_slug, new_slug = await ApplicationService(s).switch_game(
                    event_id=event.id, discord_user_id=interaction.user.id,
                    username=str(interaction.user), new_game_name=game,
                )
                event_id = event.id
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        # Move the per-game role only if they already had it (i.e. were approved).
        removed = False
        if old_slug:
            removed = await self._revoke_event_role(
                interaction.guild, event_id, f"game_role:{old_slug}", interaction.user.id
            )
        if removed:
            await self._grant_event_role(
                interaction.guild, event_id, f"game_role:{new_slug}", interaction.user.id
            )
        await interaction.followup.send(
            f"✅ Switched your application to **{game}**.", ephemeral=True
        )


async def setup(bot: EsportsBot) -> None:
    bot.add_view(ApplyView(bot))  # persistent across restarts
    await bot.add_cog(ApplicationsCog(bot))

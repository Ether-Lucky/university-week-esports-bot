"""Mechanics & tournament (Challonge) cog (docs §17-18)."""

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
from ..repositories.core import EventRepository, GameRepository
from ..services.errors import ServiceError
from ..services.mechanics_service import MechanicsService, TournamentService
from .announce import (
    AddFieldModal,
    AuthorModal,
    ContentModal,
    EmbedDraft,
    FooterModal,
    ImagesModal,
)
from .checks import is_staff


async def game_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Offer the active event's games as choices for a `game` parameter."""
    async with db.session_scope() as s:
        event = await EventRepository(s).get_active(interaction.guild_id)
        if event is None:
            return []
        games = await GameRepository(s).list_games_for_event(event.id)
    cur = current.lower()
    return [
        app_commands.Choice(name=g.name, value=g.name)
        for g in games
        if cur in g.name.lower()
    ][:25]


async def _resolve_event_game(session, guild_id: int, game_name: str):
    event = await EventRepository(session).get_active(guild_id)
    if event is None:
        return None, None, None
    game_list = await GameRepository(session).list_games_for_event(event.id)
    games = {g.name.lower(): g for g in game_list}
    game = games.get(game_name.lower())
    if game is None:
        return event, None, None
    eg = await GameRepository(session).get_event_game(event.id, game.id)
    return event, game, eg


def _mechanics_embed(title: str, body: dict) -> discord.Embed:
    # Newer mechanics store a full embed built via the /mechanics create builder.
    if isinstance(body, dict) and isinstance(body.get("embed"), dict):
        try:
            return discord.Embed.from_dict(body["embed"])
        except Exception:  # noqa: BLE001 - fall back to the legacy renderer
            pass
    embed = discord.Embed(title=title, colour=discord.Colour.teal())
    if desc := body.get("description"):
        embed.description = desc[:4000]
    for field in body.get("fields", [])[:25]:
        embed.add_field(
            name=str(field.get("name", "—"))[:256],
            value=str(field.get("value", "—"))[:1024],
            inline=bool(field.get("inline", False)),
        )
    return embed


class MechanicsBuilderView(discord.ui.View):
    """Interactive embed builder that saves the result as a game's mechanics."""

    def __init__(
        self, *, event_id: int, event_game_id: int, game_name: str,
        author_id: int, author_username: str,
    ) -> None:
        super().__init__(timeout=900)
        self.event_id = event_id
        self.event_game_id = event_game_id
        self.game_name = game_name
        self.author_id = author_id
        self.author_username = author_username
        self.draft = EmbedDraft()
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This mechanics builder isn't yours.", ephemeral=True
            )
            return False
        return True

    def panel_text(self) -> str:
        return (
            f"**Mechanics for {self.game_name}** — build the embed below, then **Save**. "
            "It's stored unpublished; run `/mechanics publish` to post it."
        )

    async def refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            content=self.panel_text(), embed=self.draft.to_embed(preview=True), view=self
        )

    @discord.ui.button(label="Content", emoji="📝", style=discord.ButtonStyle.secondary, row=0)
    async def edit_content(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ContentModal(self))

    @discord.ui.button(label="Author", emoji="👤", style=discord.ButtonStyle.secondary, row=0)
    async def edit_author(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(AuthorModal(self))

    @discord.ui.button(label="Images", emoji="🖼️", style=discord.ButtonStyle.secondary, row=0)
    async def edit_images(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ImagesModal(self))

    @discord.ui.button(label="Footer", emoji="🦶", style=discord.ButtonStyle.secondary, row=0)
    async def edit_footer(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(FooterModal(self))

    @discord.ui.button(label="Add field", emoji="➕", style=discord.ButtonStyle.secondary, row=0)
    async def add_field(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(AddFieldModal(self))

    @discord.ui.button(label="Clear fields", emoji="🧹", style=discord.ButtonStyle.secondary, row=1)
    async def clear_fields(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.draft.fields.clear()
        await self.refresh(interaction)

    @discord.ui.button(label="Timestamp", emoji="🕓", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_timestamp(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.draft.timestamp = not self.draft.timestamp
        button.style = (
            discord.ButtonStyle.success if self.draft.timestamp else discord.ButtonStyle.secondary
        )
        await self.refresh(interaction)

    @discord.ui.button(label="Save", emoji="✅", style=discord.ButtonStyle.success, row=2)
    async def save(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.draft.is_empty():
            await interaction.response.send_message(
                "Add a title, description, or a field first.", ephemeral=True
            )
            return
        embed = self.draft.to_embed(preview=False)
        title = self.draft.title or f"{self.game_name} Mechanics"
        body = {"embed": embed.to_dict(), "title": title}
        async with db.session_scope() as s:
            try:
                await MechanicsService(s).create(
                    event_id=self.event_id, event_game_id=self.event_game_id, title=title,
                    body=body, actor_discord_id=self.author_id,
                    actor_username=self.author_username,
                )
            except (ServiceError, ValueError) as exc:
                await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                return
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.response.edit_message(
            content=(
                f"✅ Mechanics for **{self.game_name}** saved (unpublished). "
                "Run `/mechanics publish` to post them."
            ),
            view=self,
        )

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.secondary, row=2)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", embed=None, view=self)

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(content="Builder timed out.", view=None)
            except discord.HTTPException:
                pass


class MechanicsCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    mechanics = app_commands.Group(
        name="mechanics", description="Game mechanics (staff).",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )
    tournament = app_commands.Group(
        name="tournament", description="Tournament links (staff).",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    @mechanics.command(
        name="create", description="Build mechanics for a game with an embed builder."
    )
    @app_commands.describe(game="Game")
    @app_commands.autocomplete(game=game_autocomplete)
    async def create(self, interaction: discord.Interaction, game: str) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event, g, eg = await _resolve_event_game(s, interaction.guild_id, game)
            if eg is None:
                await interaction.followup.send("Unknown game / no event.", ephemeral=True)
                return
            if not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            event_id, eg_id, game_name = event.id, eg.id, g.name
        view = MechanicsBuilderView(
            event_id=event_id, event_game_id=eg_id, game_name=game_name,
            author_id=interaction.user.id, author_username=str(interaction.user),
        )
        await interaction.followup.send(
            content=view.panel_text(), embed=view.draft.to_embed(preview=True),
            view=view, ephemeral=True,
        )
        view.message = await interaction.original_response()

    @mechanics.command(name="publish", description="Publish the latest mechanics to its channel.")
    @app_commands.autocomplete(game=game_autocomplete)
    async def publish(self, interaction: discord.Interaction, game: str) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event, g, eg = await _resolve_event_game(s, interaction.guild_id, game)
            if eg is None:
                await interaction.followup.send("Unknown game / no event.", ephemeral=True)
                return
            if not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            try:
                mech = await MechanicsService(s).publish(
                    event_id=event.id, event_game_id=eg.id,
                    actor_discord_id=interaction.user.id, actor_username=str(interaction.user),
                )
                title, body, event_id, game_name = mech.title, mech.body, event.id, g.name
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            channel_id = await resources.find(
                event_id, ResourceOwnerType.GAME, None, f"game_mechanics:{slug(game_name)}"
            )
        if channel_id and (ch := interaction.guild.get_channel(channel_id)):
            await ch.send(embed=_mechanics_embed(title, body))
        await interaction.followup.send("Mechanics published.", ephemeral=True)

    @mechanics.command(
        name="preview", description="Preview the saved mechanics before publishing (private)."
    )
    @app_commands.autocomplete(game=game_autocomplete)
    async def preview(self, interaction: discord.Interaction, game: str) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event, g, eg = await _resolve_event_game(s, interaction.guild_id, game)
            if eg is None:
                await interaction.followup.send("Unknown game / no event.", ephemeral=True)
                return
            if not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            mech = await MechanicsService(s).latest(eg.id)
            if mech is None:
                await interaction.followup.send(
                    f"No mechanics saved for **{g.name}** yet. Create them with "
                    "`/mechanics create`.",
                    ephemeral=True,
                )
                return
            title, body, version, published = mech.title, mech.body, mech.version, mech.published
        status = "✅ published" if published else "📝 unpublished (draft)"
        await interaction.followup.send(
            f"Preview of **{g.name}** mechanics — v{version}, {status}. "
            "This is only visible to you; use `/mechanics publish` to post it.",
            embed=_mechanics_embed(title, body),
            ephemeral=True,
        )

    @tournament.command(name="set", description="Set the Challonge URL for a game.")
    @app_commands.autocomplete(game=game_autocomplete)
    async def set_challonge(self, interaction: discord.Interaction, game: str, url: str) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event, g, eg = await _resolve_event_game(s, interaction.guild_id, game)
            if eg is None:
                await interaction.followup.send("Unknown game / no event.", ephemeral=True)
                return
            if not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            try:
                await TournamentService(s).set_challonge(
                    event_id=event.id, event_game_id=eg.id, url=url,
                    actor_discord_id=interaction.user.id, actor_username=str(interaction.user),
                )
                event_id, game_name = event.id, g.name
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            channel_id = await resources.find(
                event_id, ResourceOwnerType.GAME, None, f"game_tournament:{slug(game_name)}"
            )
        if channel_id and (ch := interaction.guild.get_channel(channel_id)):
            await ch.send(f"🏆 Tournament bracket for **{game_name}**: {url}")
        await interaction.followup.send("Challonge link set.", ephemeral=True)


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(MechanicsCog(bot))

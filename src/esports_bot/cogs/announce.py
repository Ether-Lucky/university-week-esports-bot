"""/announce — an interactive embed builder (Mimu-style) for staff.

Running the command opens an ephemeral live preview with a control panel:
buttons open modals to edit each part of the embed (content, author, images,
footer, fields), selects pick the destination channel and who to ping, and Send
posts the finished embed. Nothing is posted until Send is pressed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import EsportsBot
from ..infra import db
from ..repositories.core import EventRepository
from .checks import is_head_or_owner, is_staff

log = logging.getLogger(__name__)

_BUILDER_TIMEOUT = 900  # 15 minutes to build before the panel expires

# Placeholders staff can type in any text field; resolved when the embed is sent.
# (token, human description) — the description doubles as the staff-guide entry.
PLACEHOLDERS: list[tuple[str, str]] = [
    ("{user}", "Mention of whoever posts (you)"),
    ("{user.name}", "Your display name"),
    ("{user.tag}", "Your username"),
    ("{user.id}", "Your Discord user ID"),
    ("{server}", "The server's name"),
    ("{server.id}", "The server's ID"),
    ("{members}", "Current member count"),
    ("{channel}", "Mention of the destination channel"),
    ("{channel.name}", "Destination channel's name"),
    ("{date}", "Today's date (shown in each viewer's local time)"),
    ("{time}", "The current time (shown in each viewer's local time)"),
]


def apply_placeholders(
    text: str | None, *, guild: discord.Guild, author: discord.abc.User,
    channel: discord.abc.GuildChannel | None,
) -> str | None:
    """Replace {tokens} in a piece of text with live values."""
    if not text:
        return text
    now = int(discord.utils.utcnow().timestamp())
    mapping = {
        "{user}": author.mention,
        "{user.name}": getattr(author, "display_name", str(author)),
        "{user.tag}": str(author),
        "{user.id}": str(author.id),
        "{server}": guild.name,
        "{server.id}": str(guild.id),
        "{members}": str(guild.member_count or 0),
        "{channel}": channel.mention if channel is not None else "",
        "{channel.name}": getattr(channel, "name", "") if channel is not None else "",
        "{date}": f"<t:{now}:D>",
        "{time}": f"<t:{now}:t>",
    }
    for token, value in mapping.items():
        text = text.replace(token, str(value))
    return text


def _parse_colour(text: str | None) -> discord.Colour | None:
    if not text:
        return None
    text = text.strip().lstrip("#")
    named = {
        "blurple": discord.Colour.blurple(), "green": discord.Colour.green(),
        "red": discord.Colour.red(), "gold": discord.Colour.gold(),
        "orange": discord.Colour.orange(), "blue": discord.Colour.blue(),
        "purple": discord.Colour.purple(), "teal": discord.Colour.teal(),
        "yellow": discord.Colour.yellow(), "black": discord.Colour(0x000001),
        "white": discord.Colour(0xFFFFFF),
    }
    if text.lower() in named:
        return named[text.lower()]
    try:
        return discord.Colour(int(text, 16))
    except ValueError:
        return None


@dataclass
class EmbedDraft:
    title: str | None = None
    title_url: str | None = None
    description: str | None = None
    colour: discord.Colour | None = None
    author_name: str | None = None
    author_url: str | None = None
    author_icon: str | None = None
    image_url: str | None = None
    thumbnail_url: str | None = None
    footer_text: str | None = None
    footer_icon: str | None = None
    timestamp: bool = False
    fields: list[tuple[str, str, bool]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            (self.title, self.description, self.author_name, self.image_url, self.fields)
        )

    def to_embed(self, *, preview: bool, subst=None) -> discord.Embed:
        def S(text: str | None) -> str | None:
            return subst(text) if (subst and text) else text

        embed = discord.Embed(
            title=S(self.title) or None,
            url=self.title_url or None,
            description=S(self.description) or None,
            colour=self.colour if self.colour is not None else discord.Colour.gold(),
        )
        if preview and self.is_empty():
            embed.description = "*(empty — use the buttons below to add content)*"
        if self.author_name:
            embed.set_author(
                name=S(self.author_name), url=self.author_url or None,
                icon_url=self.author_icon or None,
            )
        if self.image_url:
            embed.set_image(url=self.image_url)
        if self.thumbnail_url:
            embed.set_thumbnail(url=self.thumbnail_url)
        if self.footer_text or self.footer_icon:
            embed.set_footer(text=S(self.footer_text) or None, icon_url=self.footer_icon or None)
        if self.timestamp:
            embed.timestamp = discord.utils.utcnow()
        for name, value, inline in self.fields:
            embed.add_field(name=S(name), value=S(value), inline=inline)
        return embed


# --------------------------------------------------------------------------- modals
class ContentModal(discord.ui.Modal, title="Embed content"):
    def __init__(self, view: "EmbedBuilderView") -> None:
        super().__init__()
        d = view.draft
        self._view = view
        self.title_in = discord.ui.TextInput(
            label="Title", required=False, max_length=256, default=d.title or "",
        )
        self.url_in = discord.ui.TextInput(
            label="Title link URL", required=False, max_length=500, default=d.title_url or "",
        )
        self.desc_in = discord.ui.TextInput(
            label="Description", required=False, style=discord.TextStyle.paragraph,
            max_length=4000, default=d.description or "",
        )
        self.colour_in = discord.ui.TextInput(
            label="Colour (hex like 5865F2 or a name)", required=False, max_length=20,
            default=(f"{d.colour.value:06X}" if d.colour is not None else ""),
        )
        for item in (self.title_in, self.url_in, self.desc_in, self.colour_in):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        d = self._view.draft
        d.title = str(self.title_in.value) or None
        d.title_url = str(self.url_in.value) or None
        d.description = str(self.desc_in.value) or None
        parsed = _parse_colour(str(self.colour_in.value))
        if parsed is not None:
            d.colour = parsed
        await self._view.refresh(interaction)


class AuthorModal(discord.ui.Modal, title="Author line"):
    def __init__(self, view: "EmbedBuilderView") -> None:
        super().__init__()
        d = view.draft
        self._view = view
        self.name_in = discord.ui.TextInput(
            label="Author name", required=False, max_length=256, default=d.author_name or "",
        )
        self.url_in = discord.ui.TextInput(
            label="Author link URL", required=False, max_length=500, default=d.author_url or "",
        )
        self.icon_in = discord.ui.TextInput(
            label="Author icon URL", required=False, max_length=500, default=d.author_icon or "",
        )
        for item in (self.name_in, self.url_in, self.icon_in):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        d = self._view.draft
        d.author_name = str(self.name_in.value) or None
        d.author_url = str(self.url_in.value) or None
        d.author_icon = str(self.icon_in.value) or None
        await self._view.refresh(interaction)


class ImagesModal(discord.ui.Modal, title="Images"):
    def __init__(self, view: "EmbedBuilderView") -> None:
        super().__init__()
        d = view.draft
        self._view = view
        self.image_in = discord.ui.TextInput(
            label="Large image URL", required=False, max_length=500, default=d.image_url or "",
        )
        self.thumb_in = discord.ui.TextInput(
            label="Thumbnail URL", required=False, max_length=500, default=d.thumbnail_url or "",
        )
        for item in (self.image_in, self.thumb_in):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        d = self._view.draft
        d.image_url = str(self.image_in.value) or None
        d.thumbnail_url = str(self.thumb_in.value) or None
        await self._view.refresh(interaction)


class FooterModal(discord.ui.Modal, title="Footer"):
    def __init__(self, view: "EmbedBuilderView") -> None:
        super().__init__()
        d = view.draft
        self._view = view
        self.text_in = discord.ui.TextInput(
            label="Footer text", required=False, max_length=2048, default=d.footer_text or "",
        )
        self.icon_in = discord.ui.TextInput(
            label="Footer icon URL", required=False, max_length=500, default=d.footer_icon or "",
        )
        for item in (self.text_in, self.icon_in):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        d = self._view.draft
        d.footer_text = str(self.text_in.value) or None
        d.footer_icon = str(self.icon_in.value) or None
        await self._view.refresh(interaction)


class AddFieldModal(discord.ui.Modal, title="Add a field"):
    def __init__(self, view: "EmbedBuilderView") -> None:
        super().__init__()
        self._view = view
        self.name_in = discord.ui.TextInput(label="Field name", max_length=256)
        self.value_in = discord.ui.TextInput(
            label="Field value", style=discord.TextStyle.paragraph, max_length=1024
        )
        self.inline_in = discord.ui.TextInput(
            label="Inline? (yes/no)", required=False, max_length=3, default="no"
        )
        for item in (self.name_in, self.value_in, self.inline_in):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if len(self._view.draft.fields) >= 25:
            await interaction.response.send_message(
                "An embed can have at most 25 fields.", ephemeral=True
            )
            return
        inline = str(self.inline_in.value).strip().lower() in ("yes", "y", "true", "1")
        self._view.draft.fields.append(
            (str(self.name_in.value), str(self.value_in.value), inline)
        )
        await self._view.refresh(interaction)


# --------------------------------------------------------------------------- view
class EmbedBuilderView(discord.ui.View):
    def __init__(self, author_id: int) -> None:
        super().__init__(timeout=_BUILDER_TIMEOUT)
        self.author_id = author_id
        self.draft = EmbedDraft()
        self.target_channel_id: int | None = None
        self.mention_users: list[discord.abc.Snowflake] = []
        self.mention_roles: list[discord.abc.Snowflake] = []
        self.ping_everyone = False
        self.ping_here = False
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This announcement builder isn't yours.", ephemeral=True
            )
            return False
        return True

    def _panel_text(self) -> str:
        if self.target_channel_id:
            dest = f"<#{self.target_channel_id}>"
        else:
            dest = "*(pick a channel below)*"
        pings = []
        if self.ping_everyone:
            pings.append("@everyone")
        if self.ping_here:
            pings.append("@here")
        pings += [f"<@&{r.id}>" for r in self.mention_roles]
        pings += [f"<@{u.id}>" for u in self.mention_users]
        ping_line = " ".join(pings) if pings else "none"
        return (
            f"**Preview** · destination: {dest} · pings: {ping_line}\n"
            "-# Tip: type placeholders like `{user.id}`, `{server}`, `{members}` — "
            "see the placeholder guide in #staff-commands."
        )

    def _subst(self, interaction: discord.Interaction):
        channel = None
        if self.target_channel_id:
            channel = interaction.guild.get_channel(self.target_channel_id)
        channel = channel or interaction.channel
        return lambda t: apply_placeholders(
            t, guild=interaction.guild, author=interaction.user, channel=channel
        )

    def preview_embed(self, interaction: discord.Interaction) -> discord.Embed:
        return self.draft.to_embed(preview=True, subst=self._subst(interaction))

    async def refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            content=self._panel_text(),
            embed=self.preview_embed(interaction),
            view=self,
        )

    # Row 0 — content editors
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

    # Row 1 — destination channel
    @discord.ui.select(
        cls=discord.ui.ChannelSelect, row=1, placeholder="Destination channel…",
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
    )
    async def pick_channel(
        self, interaction: discord.Interaction, select: discord.ui.ChannelSelect
    ) -> None:
        self.target_channel_id = select.values[0].id
        await self.refresh(interaction)

    # Row 2 — who to ping (roles and/or users)
    @discord.ui.select(
        cls=discord.ui.MentionableSelect, row=2, min_values=0, max_values=25,
        placeholder="Ping specific roles / people (optional)…",
    )
    async def pick_mentions(
        self, interaction: discord.Interaction, select: discord.ui.MentionableSelect
    ) -> None:
        self.mention_roles = [v for v in select.values if isinstance(v, discord.Role)]
        self.mention_users = [v for v in select.values if not isinstance(v, discord.Role)]
        await self.refresh(interaction)

    # Row 3 — toggles
    @discord.ui.button(label="Clear fields", emoji="🧹", style=discord.ButtonStyle.secondary, row=3)
    async def clear_fields(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.draft.fields.clear()
        await self.refresh(interaction)

    @discord.ui.button(label="Timestamp", emoji="🕓", style=discord.ButtonStyle.secondary, row=3)
    async def toggle_timestamp(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.draft.timestamp = not self.draft.timestamp
        button.style = (
            discord.ButtonStyle.success if self.draft.timestamp else discord.ButtonStyle.secondary
        )
        await self.refresh(interaction)

    @discord.ui.button(label="@everyone", style=discord.ButtonStyle.secondary, row=3)
    async def toggle_everyone(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.ping_everyone = not self.ping_everyone
        if self.ping_everyone:
            self.ping_here = False
            self.here_btn.style = discord.ButtonStyle.secondary
        button.style = (
            discord.ButtonStyle.danger if self.ping_everyone else discord.ButtonStyle.secondary
        )
        await self.refresh(interaction)

    @discord.ui.button(label="@here", style=discord.ButtonStyle.secondary, row=3)
    async def here_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.ping_here = not self.ping_here
        if self.ping_here:
            self.ping_everyone = False
            self.toggle_everyone.style = discord.ButtonStyle.secondary
        button.style = (
            discord.ButtonStyle.danger if self.ping_here else discord.ButtonStyle.secondary
        )
        await self.refresh(interaction)

    # Row 4 — send / cancel
    @discord.ui.button(label="Send", emoji="✅", style=discord.ButtonStyle.success, row=4)
    async def send(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.target_channel_id is None:
            await interaction.response.send_message(
                "Pick a destination channel first.", ephemeral=True
            )
            return
        if self.draft.is_empty():
            await interaction.response.send_message(
                "The embed is empty — add a title, description, or a field first.",
                ephemeral=True,
            )
            return
        channel = interaction.guild.get_channel(self.target_channel_id)
        if channel is None:
            await interaction.response.send_message("That channel is gone.", ephemeral=True)
            return
        perms = channel.permissions_for(interaction.guild.me)
        if not (perms.view_channel and perms.send_messages):
            await interaction.response.send_message(
                f"I can't post in {channel.mention} — missing View/Send there.", ephemeral=True
            )
            return

        parts: list[str] = []
        if self.ping_everyone:
            parts.append("@everyone")
        elif self.ping_here:
            parts.append("@here")
        parts += [r.mention for r in self.mention_roles]
        parts += [u.mention for u in self.mention_users]
        content = " ".join(parts) or None
        allowed = discord.AllowedMentions(
            everyone=self.ping_everyone or self.ping_here,
            roles=list(self.mention_roles) or False,
            users=list(self.mention_users) or False,
        )
        subst = lambda t: apply_placeholders(  # noqa: E731
            t, guild=interaction.guild, author=interaction.user, channel=channel
        )
        try:
            sent = await channel.send(
                content=content, embed=self.draft.to_embed(preview=False, subst=subst),
                allowed_mentions=allowed,
            )
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Couldn't post: {exc}", ephemeral=True)
            return
        log.info("Announcement by %s in #%s (%s)", interaction.user, channel.name, channel.id)
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.response.edit_message(
            content=f"✅ Posted in {channel.mention}. [Jump to message]({sent.jump_url})",
            view=self,
        )

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.secondary, row=4)
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


class AnnounceCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    async def _staff_ok(self, interaction: discord.Interaction) -> bool:
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                return is_head_or_owner(interaction, self.bot.settings)
            return await is_staff(interaction, s, event.id, self.bot.settings)

    @app_commands.command(
        name="announce", description="Build a custom embed announcement and post it (staff)."
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def announce(self, interaction: discord.Interaction) -> None:
        if not await self._staff_ok(interaction):
            await interaction.response.send_message("Staff only.", ephemeral=True)
            return
        view = EmbedBuilderView(interaction.user.id)
        await interaction.response.send_message(
            content=view._panel_text(), embed=view.preview_embed(interaction),
            view=view, ephemeral=True,
        )
        view.message = await interaction.original_response()


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(AnnounceCog(bot))

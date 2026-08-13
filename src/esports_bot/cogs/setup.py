"""/setup commands — preview, backup, and (guarded) destructive build.

Setup preview never changes anything. Confirm requires a token issued by
preview, verifies Community + resource limits, backs up the server structure,
removes non-preserved resources, then builds the event structure idempotently.
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import EsportsBot
from ..domain.enums import ResourceOwnerType, ResourceType
from ..domain.server_blueprint import slug
from ..domain.setup_plan import (
    ChannelInfo,
    GuildSnapshot,
    RoleInfo,
    plan_preview,
    serialise_backup,
)
from ..infra import db
from ..infra.discord_gateway import DiscordResourceGateway
from ..infra.discord_resources import DiscordResourceService
from ..infra.resource_repository import SqlResourceRepository
from ..repositories.core import EventRepository, GameRepository
from ..services.setup_service import SetupService
from .checks import HEAD_ROLE_NAME, is_head_or_owner

log = logging.getLogger(__name__)
_BACKUP_DIR = Path("data/backups")


def _flow_embed(event_name: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎮 {event_name} — How It Works",
        colour=discord.Colour.blurple(),
        description="Welcome! Here's how to take part in the E-Sports tryouts:",
    )
    embed.add_field(
        name="1️⃣ Verify",
        value="Complete verification in **#verify** to get the **Audience** role.",
        inline=False,
    )
    embed.add_field(
        name="2️⃣ Apply",
        value="When applications open, go to **#apply** and press **Apply for Tryouts**. "
        "Fill in the short form (name, school email, Facebook, year & section, game).",
        inline=False,
    )
    embed.add_field(
        name="3️⃣ Get approved",
        value="Staff review your application. Once approved you become an **Applicant** "
        "and unlock team formation.",
        inline=False,
    )
    embed.add_field(
        name="4️⃣ Team up",
        value="Create a team with `/team create` or join one with `/team join <id>` "
        "(browse the team forums). Leaders recruit with `/recruit player`.",
        inline=False,
    )
    embed.add_field(
        name="5️⃣ Get ready",
        value="Staff post the mechanics and bracket. Check in with `/tryout checkin` "
        "before the tryout begins.",
        inline=False,
    )
    embed.add_field(
        name="6️⃣ Compete",
        value="Play your matches during the tryout. Results appear in each game's "
        "**battle-results** channel.",
        inline=False,
    )
    embed.add_field(
        name="7️⃣ Win",
        value="The champion team's members become official **Players**! 🏆",
        inline=False,
    )
    embed.set_footer(text="Roles: Audience (everyone) → Applicant (approved) → Player (champions)")
    return embed


def snapshot_guild(guild: discord.Guild) -> GuildSnapshot:
    roles = tuple(
        RoleInfo(id=r.id, name=r.name, managed=r.managed, is_default=r.is_default())
        for r in guild.roles
    )
    kind_map = {
        discord.ChannelType.category: "category",
        discord.ChannelType.text: "text",
        discord.ChannelType.voice: "voice",
        discord.ChannelType.forum: "forum",
        discord.ChannelType.stage_voice: "stage",
    }
    channels = tuple(
        ChannelInfo(
            id=c.id, name=c.name,
            kind=kind_map.get(c.type, c.type.name),
            category_id=c.category_id,
        )
        for c in guild.channels
    )
    return GuildSnapshot(roles=roles, channels=channels, features=frozenset(guild.features))


def protected_channel_ids(guild: discord.Guild) -> set[int]:
    """Channels Discord won't let us delete on a Community server (+ system channels)."""
    ids: set[int] = set()
    for ch in (
        guild.rules_channel,
        guild.public_updates_channel,
        guild.system_channel,
        getattr(guild, "safety_alerts_channel", None),
    ):
        if ch is not None:
            ids.add(ch.id)
    return ids


class SetupCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot
        self._tokens: dict[tuple[int, int], str] = {}

    setup_group = app_commands.Group(
        name="setup",
        description="Set up the Discord server for the event.",
        default_permissions=discord.Permissions(administrator=True),
        guild_only=True,
    )

    async def _event_and_games(self, guild_id: int):
        async with db.session_scope() as s:
            ev = await EventRepository(s).get_active(guild_id)
            if ev is None:
                return None, []
            games = await GameRepository(s).list_games_for_event(ev.id)
            return ev.id, [slug(g.name) for g in games]

    @setup_group.command(name="preview", description="Preview what setup will preserve vs remove.")
    async def preview(self, interaction: discord.Interaction) -> None:
        if not is_head_or_owner(interaction, self.bot.settings):
            await interaction.response.send_message("E-Sports Head only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        event_id, shorts = await self._event_and_games(interaction.guild_id)
        if event_id is None:
            await interaction.followup.send(
                "No active event. Run `/event create` and add games first.", ephemeral=True
            )
            return

        snap = snapshot_guild(interaction.guild)
        preview = plan_preview(
            snap, num_games=len(shorts),
            always_preserve_ids=protected_channel_ids(interaction.guild),
        )
        token = secrets.token_hex(3)
        self._tokens[(interaction.guild_id, interaction.user.id)] = token

        proj = preview.projection
        embed = discord.Embed(
            title="Setup Preview (nothing changed yet)",
            colour=discord.Colour.green() if preview.can_proceed else discord.Colour.red(),
        )
        embed.add_field(name="Preserve", value=str(len(preview.preserve)), inline=True)
        embed.add_field(name="Remove", value=str(len(preview.remove)), inline=True)
        embed.add_field(name="Games", value=str(len(shorts)), inline=True)
        embed.add_field(
            name="Community",
            value="✅ enabled" if preview.community_ok else "❌ required",
            inline=True,
        )
        if proj:
            embed.add_field(
                name="Projected resources",
                value=(
                    f"roles ~{proj.roles}, categories ~{proj.categories}, "
                    f"channels ~{proj.channels}"
                ),
                inline=False,
            )
        if preview.warnings:
            embed.add_field(
                name="⚠️ Warnings",
                value="\n".join(preview.warnings)[:1024],
                inline=False,
            )
        embed.add_field(
            name="⚠️ This is destructive",
            value=(
                f"Setup removes {len(preview.remove)} non-preserved resources, then builds the "
                f"event structure. To proceed run:\n`/setup confirm token:{token}`"
                if preview.can_proceed
                else "Resolve the warnings above before running setup."
            ),
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_group.command(
        name="grant-audience",
        description="Give the Audience role to all current (human) members.",
    )
    async def grant_audience(self, interaction: discord.Interaction) -> None:
        if not is_head_or_owner(interaction, self.bot.settings):
            await interaction.response.send_message("E-Sports Head only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            role_id = await resources.find(
                event.id, ResourceOwnerType.SYSTEM, None, "role_audience"
            )
        role = interaction.guild.get_role(role_id) if role_id else None
        if role is None:
            await interaction.followup.send(
                "No Audience role found. Run `/setup confirm` first.", ephemeral=True
            )
            return

        # Make sure the full member list is loaded (requires Server Members Intent).
        if not interaction.guild.chunked:
            await interaction.guild.chunk()
        members = list(interaction.guild.members)
        log.info("grant-audience: processing %d members", len(members))

        granted = skipped = failed = 0
        for i, member in enumerate(members, start=1):
            if member.bot or role in member.roles:
                skipped += 1
                continue
            try:
                await member.add_roles(role, reason="Bulk grant Audience (existing members)")
                granted += 1
            except discord.HTTPException:
                failed += 1
            if i % 25 == 0:
                log.info("grant-audience: %d/%d processed", i, len(members))
        log.info(
            "grant-audience done: granted=%d skipped=%d failed=%d", granted, skipped, failed
        )
        note = f" ({failed} failed)" if failed else ""
        await interaction.followup.send(
            f"✅ Granted **Audience** to {granted} members; {skipped} already had it or are bots"
            f"{note}. New members still verify via the external bot.",
            ephemeral=True,
        )

    @setup_group.command(
        name="post-guide", description="Post the 'how it works' guide in #how-it-works."
    )
    async def post_guide(self, interaction: discord.Interaction) -> None:
        if not is_head_or_owner(interaction, self.bot.settings):
            await interaction.response.send_message("E-Sports Head only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            channel_id = await resources.find(
                event.id, ResourceOwnerType.SYSTEM, None, "ch_info"
            )
            event_name = f"{event.name} {event.year}"
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if channel is None:
            await interaction.followup.send(
                "No #how-it-works channel found. Run `/setup confirm` first.", ephemeral=True
            )
            return
        await channel.send(embed=_flow_embed(event_name))
        await interaction.followup.send(f"Posted the guide in {channel.mention}.", ephemeral=True)

    @setup_group.command(name="backup", description="Save the current server structure to a file.")
    async def backup(self, interaction: discord.Interaction) -> None:
        if not is_head_or_owner(interaction, self.bot.settings):
            await interaction.response.send_message("E-Sports Head only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        snap = snapshot_guild(interaction.guild)
        _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        path = _BACKUP_DIR / f"server-structure-{interaction.guild_id}.json"
        path.write_text(serialise_backup(snap), encoding="utf-8")
        await interaction.followup.send(
            "Server structure backed up.", file=discord.File(path), ephemeral=True
        )

    @setup_group.command(
        name="confirm", description="Perform destructive setup (needs preview token)."
    )
    @app_commands.describe(token="The token shown by /setup preview")
    async def confirm(self, interaction: discord.Interaction, token: str) -> None:
        if not is_head_or_owner(interaction, self.bot.settings):
            await interaction.response.send_message("E-Sports Head only.", ephemeral=True)
            return
        expected = self._tokens.get((interaction.guild_id, interaction.user.id))
        if not expected or token != expected:
            await interaction.response.send_message(
                "Invalid or expired token. Run `/setup preview` first.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        event_id, shorts = await self._event_and_games(interaction.guild_id)
        if event_id is None:
            await interaction.followup.send("No active event.", ephemeral=True)
            return

        snap = snapshot_guild(interaction.guild)
        preview = plan_preview(
            snap, num_games=len(shorts),
            always_preserve_ids=protected_channel_ids(interaction.guild),
        )
        if not preview.can_proceed:
            await interaction.followup.send(
                "Cannot proceed:\n" + "\n".join(preview.warnings), ephemeral=True
            )
            return

        # Backup first.
        _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        (_BACKUP_DIR / f"server-structure-{interaction.guild_id}.json").write_text(
            serialise_backup(snap), encoding="utf-8"
        )

        # Find the preserved E-Sports Head role so permissions can reference it.
        head_id = next(
            (r.id for r in snap.roles if r.name.casefold() == HEAD_ROLE_NAME.casefold()),
            None,
        )

        gateway = DiscordResourceGateway(interaction.guild)
        async with db.session_scope() as s:
            resources = DiscordResourceService(gateway, SqlResourceRepository(s))
            setup_service = SetupService(resources, gateway)
            if head_id is not None:
                await resources.register_existing(
                    event_id, ResourceType.ROLE, ResourceOwnerType.SYSTEM, None,
                    "role_head", head_id,
                )
            removed = await setup_service.remove_preexisting(preview.remove)
            report = await setup_service.build(event_id, shorts)
            applied, failed = await setup_service.apply_permissions(event_id, shorts)

        self._tokens.pop((interaction.guild_id, interaction.user.id), None)
        msg = (
            f"Setup complete. Removed {removed} resources; created ~{report.roles} roles, "
            f"{report.categories} categories, {report.channels} channels; "
            f"applied permissions to {applied} channels."
        )
        if failed:
            msg += (
                f"\n\n⚠️ **{failed} channels could not get their permissions** (403 Missing "
                "Permissions). Give the bot's role **Manage Roles** and drag it **above "
                "@E-Sports Head** in Server Settings → Roles (or grant it Administrator), "
                "then re-run `/setup preview` → `/setup confirm` to finish applying permissions."
            )
        else:
            msg += " Run `/system health`, then `/staff add` your committee."
        await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(SetupCog(bot))

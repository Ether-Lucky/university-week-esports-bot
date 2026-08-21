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
from ..domain.enums import ResourceOwnerType, ResourceStatus, ResourceType
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
        value="Staff review your application. Once approved you become an **Applicant** for "
        "your game and can start teaming up (you can `/switch-game` before joining a team).",
        inline=False,
    )
    embed.add_field(
        name="4️⃣ Team up",
        value=(
            "• **Make a team:** `/team create name:<name>` — you become the leader; your team "
            "is posted to the **team forum**.\n"
            "• **Join a team:** press **Join Team** on a team's forum post (or `/team join "
            "team_id:<id>`).\n"
            "• **No team yet?** `/findteam ign:<> role:<>` posts you to the **looking-for-team "
            "forum** with a **Recruit** button leaders can press."
        ),
        inline=False,
    )
    embed.add_field(
        name="5️⃣ Get ready",
        value="Staff post the **mechanics** and the **bracket** link, and set the tryout "
        "date/time. Check in with `/tryout checkin` before the tryout begins.",
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


def _member_commands_embed(event_name: str) -> discord.Embed:
    """Command reference for participants — posted in #how-it-works below the flow guide."""
    embed = discord.Embed(
        title=f"💬 {event_name} — Your Commands",
        colour=discord.Colour.blurple(),
        description=(
            "Every slash command you can use as a participant. Type `/` in any channel "
            "to see them. (Most need you to be an **approved Applicant** first.)"
        ),
    )
    embed.add_field(
        name="👥 Teams",
        value=(
            "• `/team create name:<name>` — start a team; you become the leader\n"
            "• `/team join team_id:<id>` — ask to join (the leader approves)\n"
            "• `/team view team_id:<id>` — see a team's roster\n"
            "• `/team leave` — leave your current team\n"
            "• `/team kick member:<@member>` — leaders: remove a member from your team\n"
            "• `/team disband` — leaders: disband your team"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔎 Finding a team",
        value=(
            "• `/findteam ign:<name> role:<role>` — post yourself on the LFT forum "
            "so leaders can recruit you\n"
            "• `/lft cancel` — take down your looking-for-team post"
        ),
        inline=False,
    )
    embed.add_field(
        name="📣 Recruiting (team leaders)",
        value=(
            "• `/recruit player` — invite a player to your team\n"
            "• `/recruit accept` · `/recruit decline reason:<why>` — respond to join "
            "requests (you can also use the buttons in your DMs)"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎮 Your application & tryout",
        value=(
            "• `/switch-game game:<name>` — change your game (before joining a team)\n"
            "• `/tryout status` — check tryout readiness for your game\n"
            "• `/tryout checkin` — check in before your tryout starts"
        ),
        inline=False,
    )
    embed.set_footer(text="Stuck? Read the flow guide above or ask staff in your game's channel.")
    return embed


def _staff_guide_embed(event_name: str) -> discord.Embed:
    """Command reference for staff/committee — posted in #staff-commands."""
    embed = discord.Embed(
        title=f"🛠️ {event_name} — Staff Command Guide",
        colour=discord.Colour.dark_teal(),
        description=(
            "Commands here are **staff-only**. Members can't run them — their guide "
            "lives in **#how-it-works**. Steps roughly follow the event lifecycle."
        ),
    )
    embed.add_field(
        name="🏗️ Setup & event (Head)",
        value=(
            "• `/setup preview` → `/setup confirm token:<token>` — build the server\n"
            "• `/setup grant-audience` — give Audience to existing members\n"
            "• `/setup post-guide` — (re)post these guides\n"
            "• `/event create` · `/event configure add-game` · `/event advance` · "
            "`/event status`\n"
            "• `/staff add` · `/staff remove` · `/staff list`"
        ),
        inline=False,
    )
    embed.add_field(
        name="📝 Applications",
        value=(
            "• `/application post-button` — place the Apply button in **#apply**\n"
            "• `/application list` — pending applications\n"
            "• `/application approve application_id:<id>`\n"
            "• `/application reject application_id:<id> reason:<why>`\n"
            "• `/application backfill-roles` — re-grant roles to approved applicants"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎯 Mechanics & tournament",
        value=(
            "• `/mechanics create` — build a game's rules (embed builder)\n"
            "• `/mechanics preview` — privately check the saved draft before posting\n"
            "• `/mechanics publish` — post the mechanics to the game's channel\n"
            "• `/tournament set` — set the Challonge bracket URL"
        ),
        inline=False,
    )
    embed.add_field(
        name="🏆 Tryouts & results",
        value=(
            "• `/tryout schedule` · `/tryout status` · `/tryout start` "
            "(builds per-game tryout channels + hides the rest)\n"
            "• `/tryout checkin-all` — check every team member in at once\n"
            "• `/tryout appoint game: member:` — grant Player for a game with no teams\n"
            "• `/tryout resync-channels` — re-apply tryout channel perms & focus (no restart)\n"
            "• `/match battle-ended` · `/match correct reason:<why>` — record results\n"
            "• `/tryout crown` · `/tryout end` — crown champions & finalize (restores channels)"
        ),
        inline=False,
    )
    embed.add_field(
        name="📊 Dashboard & announcements",
        value=(
            "• `/announce` — open the embed builder: customize title, description, "
            "colour, author, images & fields, pick a channel, ping any roles/people, then Send\n"
            "• `/dashboard refresh` — rebuild the live dashboard now\n"
            "• `/dashboard follow #channel` / `/dashboard unfollow` — mirror this event's "
            "dashboard into another server that invited the bot"
        ),
        inline=False,
    )
    embed.add_field(
        name="🧹 Moderation & data",
        value=(
            "• `/player lookup member:<@member>` — show a member's full DB record\n"
            "• `/lft delete` — remove a member's looking-for-team post\n"
            "• `/team disband` — disband a team\n"
            "• `/team lock-creation closed:<true/false>` — stop/allow new teams "
            "(existing teams still fill up)\n"
            "• `/team resync-posts` — refresh all team forum posts (roster + Join button)\n"
            "• `/member restore` — re-grant a returning member's roles from kept data\n"
            "• `/export` — download event data as CSV\n"
            "• `/system status` · `/system archive`"
        ),
        inline=False,
    )
    embed.set_footer(text="Only Head/Committee/staff can use these — participants get an error.")
    return embed


def _placeholders_guide_embed(event_name: str) -> discord.Embed:
    """Reference for the /announce embed-builder placeholders — posted in #staff-commands."""
    from .announce import PLACEHOLDERS

    embed = discord.Embed(
        title=f"🔤 {event_name} — Announcement Placeholders",
        colour=discord.Colour.dark_teal(),
        description=(
            "Type these in any text field of the **/announce** embed builder "
            "(title, description, fields, footer, author). Each one is replaced with a "
            "live value when the announcement is sent."
        ),
    )
    lines = [f"`{token}` — {desc}" for token, desc in PLACEHOLDERS]
    embed.add_field(name="Available placeholders", value="\n".join(lines)[:1024], inline=False)
    embed.set_footer(
        text="Example: “Posted by {user} on {date}” → your mention and today’s date."
    )
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
        # Manage Server (not Administrator) so the E-Sports Head role can see these
        # once granted that permission; the runtime check still restricts to Head/owner.
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    async def _tracked_resource_ids(self, event_id: int) -> set[int]:
        """Discord IDs the bot already created for this event — keep, don't re-make."""
        async with db.session_scope() as s:
            repo = SqlResourceRepository(s)
            rows = await repo.list_by_status(event_id, ResourceStatus.CREATED)
            return {r.discord_id for r in rows if r.discord_id is not None}

    async def _event_and_games(self, guild_id: int):
        async with db.session_scope() as s:
            ev = await EventRepository(s).get_active(guild_id)
            if ev is None:
                return None, []
            games = await GameRepository(s).list_games_for_event(ev.id)
            return ev.id, [(slug(g.name), g.name) for g in games]

    @setup_group.command(name="preview", description="Preview what setup will preserve vs remove.")
    async def preview(self, interaction: discord.Interaction) -> None:
        if not is_head_or_owner(interaction, self.bot.settings):
            await interaction.response.send_message("E-Sports Head only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        event_id, games = await self._event_and_games(interaction.guild_id)
        if event_id is None:
            await interaction.followup.send(
                "No active event. Run `/event create` and add games first.", ephemeral=True
            )
            return

        snap = snapshot_guild(interaction.guild)
        keep_ids = protected_channel_ids(interaction.guild) | await self._tracked_resource_ids(
            event_id
        )
        preview = plan_preview(snap, num_games=len(games), always_preserve_ids=keep_ids)
        token = secrets.token_hex(3)
        self._tokens[(interaction.guild_id, interaction.user.id)] = token

        proj = preview.projection
        embed = discord.Embed(
            title="Setup Preview (nothing changed yet)",
            colour=discord.Colour.green() if preview.can_proceed else discord.Colour.red(),
        )
        embed.add_field(name="Preserve", value=str(len(preview.preserve)), inline=True)
        embed.add_field(name="Remove", value=str(len(preview.remove)), inline=True)
        embed.add_field(name="Games", value=str(len(games)), inline=True)
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
        if preview.remove:
            lines = [f"• {kind}: {name}" for kind, _id, name in preview.remove]
            shown, text = [], ""
            for line in lines:
                if len(text) + len(line) + 1 > 1000:
                    break
                shown.append(line)
                text += line + "\n"
            hidden = len(lines) - len(shown)
            if hidden:
                text += f"…and {hidden} more"
            embed.add_field(name=f"🗑️ Will remove ({len(lines)})", value=text, inline=False)
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

    async def _post_or_update_guide(
        self, guild: discord.Guild, event_id: int, channel_purpose: str,
        guide_purpose: str, embed: discord.Embed,
    ) -> discord.abc.GuildChannel | None:
        """Post (or edit in place) one guide message. Returns the channel it lives in, or None."""
        async with db.session_scope() as s:
            repo = SqlResourceRepository(s)
            resources = DiscordResourceService(DiscordResourceGateway(guild), repo)
            channel_id = await resources.find(
                event_id, ResourceOwnerType.SYSTEM, None, channel_purpose
            )
            guide_row = await repo.get(event_id, ResourceOwnerType.SYSTEM, None, guide_purpose)
            guide_msg_id = guide_row.discord_id if guide_row else None
            guide_row_id = guide_row.id if guide_row else None
        channel = guild.get_channel(channel_id) if channel_id else None
        if channel is None:
            return None

        edited = False
        if guide_msg_id:  # try to update the existing guide message in place
            try:
                msg = await channel.fetch_message(guide_msg_id)
                await msg.edit(embed=embed)
                edited = True
            except discord.HTTPException:
                edited = False
        if not edited:
            msg = await channel.send(embed=embed)
            async with db.session_scope() as s:
                repo = SqlResourceRepository(s)
                if guide_row_id is not None:
                    await repo.set_created(guide_row_id, msg.id)
                else:
                    row = await repo.add_pending(
                        event_id, ResourceType.MESSAGE, ResourceOwnerType.SYSTEM, None,
                        guide_purpose,
                    )
                    await repo.set_created(row.id, msg.id)
        return channel

    @setup_group.command(
        name="post-guide",
        description="Post the member guide in #how-it-works and the staff guide in #staff-commands.",
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
            event_name, event_id = f"{event.name} {event.year}", event.id

        member_channel = await self._post_or_update_guide(
            interaction.guild, event_id, "ch_info", "guide_message", _flow_embed(event_name)
        )
        # Second message in the same channel: the member command reference.
        await self._post_or_update_guide(
            interaction.guild, event_id, "ch_info", "member_commands_message",
            _member_commands_embed(event_name),
        )
        staff_channel = await self._post_or_update_guide(
            interaction.guild, event_id, "ch_staff_commands", "staff_guide_message",
            _staff_guide_embed(event_name),
        )
        # Second staff message: the /announce placeholder reference.
        await self._post_or_update_guide(
            interaction.guild, event_id, "ch_staff_commands", "placeholder_guide_message",
            _placeholders_guide_embed(event_name),
        )
        if member_channel is None and staff_channel is None:
            await interaction.followup.send(
                "No guide channels found. Run `/setup confirm` first.", ephemeral=True
            )
            return
        parts = []
        if member_channel:
            parts.append(f"member guide in {member_channel.mention}")
        if staff_channel:
            parts.append(f"staff guide in {staff_channel.mention}")
        await interaction.followup.send("Posted the " + " and the ".join(parts) + ".", ephemeral=True)

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

        event_id, games = await self._event_and_games(interaction.guild_id)
        if event_id is None:
            await interaction.followup.send("No active event.", ephemeral=True)
            return
        shorts = [s for s, _ in games]

        snap = snapshot_guild(interaction.guild)
        keep_ids = protected_channel_ids(interaction.guild) | await self._tracked_resource_ids(
            event_id
        )
        preview = plan_preview(snap, num_games=len(games), always_preserve_ids=keep_ids)
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
            report = await setup_service.build(event_id, games)
            applied, failed = await setup_service.apply_permissions(event_id, shorts)

        self._tokens.pop((interaction.guild_id, interaction.user.id), None)
        from ..infra import dashboard
        await dashboard.refresh(interaction.guild, event_id)  # post the dashboard + pin to top
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

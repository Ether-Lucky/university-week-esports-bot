"""Gateway that performs the actual Discord API calls for resource management.

Isolated behind a Protocol so the resource service can be unit-tested with a
fake. The concrete ``DiscordResourceGateway`` wraps a ``discord.Guild``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from ..domain.enums import ResourceType
from ..domain.permissions import PermFlags

if TYPE_CHECKING:
    import discord

_CHANNEL_TYPES = {
    ResourceType.CATEGORY,
    ResourceType.TEXT_CHANNEL,
    ResourceType.VOICE_CHANNEL,
    ResourceType.FORUM_CHANNEL,
    ResourceType.STAGE_CHANNEL,
}


class ResourceGateway(Protocol):
    """Creates/deletes/checks Discord resources, returning their snowflake IDs."""

    def bot_top_role_position(self) -> int: ...

    def find_role_by_name(self, name: str) -> int | None: ...

    async def create_role(self, name: str, **kwargs: Any) -> int: ...

    async def create_category(self, name: str, overwrites: Any | None = None) -> int: ...

    async def create_text_channel(
        self, name: str, *, category_id: int | None = None,
        overwrites: Any | None = None, topic: str | None = None,
    ) -> int: ...

    async def create_voice_channel(
        self, name: str, *, category_id: int | None = None, overwrites: Any | None = None,
    ) -> int: ...

    async def create_forum_channel(
        self, name: str, *, category_id: int | None = None,
        overwrites: Any | None = None, topic: str | None = None,
    ) -> int: ...

    async def create_stage_channel(
        self, name: str, *, category_id: int | None = None, overwrites: Any | None = None,
    ) -> int: ...

    async def delete(self, resource_type: ResourceType, discord_id: int) -> None: ...

    async def exists(self, resource_type: ResourceType, discord_id: int) -> bool: ...

    async def set_overwrites(
        self, channel_id: int, entries: list[tuple[int | None, PermFlags]]
    ) -> None: ...


class DiscordResourceGateway:
    """Concrete gateway backed by a live ``discord.Guild``."""

    def __init__(self, guild: discord.Guild) -> None:
        self._guild = guild

    def bot_top_role_position(self) -> int:
        return self._guild.me.top_role.position

    def find_role_by_name(self, name: str) -> int | None:
        import discord

        role = discord.utils.get(self._guild.roles, name=name)
        return role.id if role else None

    def _category(self, category_id: int | None):
        if category_id is None:
            return None
        chan = self._guild.get_channel(category_id)
        return chan

    async def create_role(self, name: str, **kwargs: Any) -> int:
        role = await self._guild.create_role(name=name, **kwargs)
        return role.id

    async def create_category(self, name: str, overwrites: Any | None = None) -> int:
        chan = await self._guild.create_category(name=name, overwrites=overwrites or {})
        return chan.id

    async def create_text_channel(
        self, name: str, *, category_id: int | None = None,
        overwrites: Any | None = None, topic: str | None = None,
    ) -> int:
        chan = await self._guild.create_text_channel(
            name=name, category=self._category(category_id),
            overwrites=overwrites or {}, topic=topic,
        )
        return chan.id

    async def create_voice_channel(
        self, name: str, *, category_id: int | None = None, overwrites: Any | None = None,
    ) -> int:
        chan = await self._guild.create_voice_channel(
            name=name, category=self._category(category_id), overwrites=overwrites or {},
        )
        return chan.id

    async def create_forum_channel(
        self, name: str, *, category_id: int | None = None,
        overwrites: Any | None = None, topic: str | None = None,
    ) -> int:
        chan = await self._guild.create_forum(
            name=name, category=self._category(category_id),
            overwrites=overwrites or {}, topic=topic,
        )
        return chan.id

    async def create_stage_channel(
        self, name: str, *, category_id: int | None = None, overwrites: Any | None = None,
    ) -> int:
        chan = await self._guild.create_stage_channel(
            name=name, category=self._category(category_id), overwrites=overwrites or {},
        )
        return chan.id

    async def delete(self, resource_type: ResourceType, discord_id: int) -> None:
        obj = self._resolve(resource_type, discord_id)
        if obj is not None:
            await obj.delete()
        # A 404 / already-gone resource is treated as success by the caller.

    async def exists(self, resource_type: ResourceType, discord_id: int) -> bool:
        return self._resolve(resource_type, discord_id) is not None

    async def set_overwrites(
        self, channel_id: int, entries: list[tuple[int | None, PermFlags]]
    ) -> None:
        import discord

        channel = self._guild.get_channel(channel_id)
        if channel is None:
            return
        overwrites: dict[Any, discord.PermissionOverwrite] = {}
        for role_id, flags in entries:
            target = self._guild.default_role if role_id is None else self._guild.get_role(role_id)
            if target is None:
                continue
            overwrites[target] = discord.PermissionOverwrite(
                view_channel=flags.view,
                send_messages=flags.send,
                connect=flags.connect,
            )
        if overwrites:
            await channel.edit(overwrites=overwrites)

    def _resolve(self, resource_type: ResourceType, discord_id: int):
        if resource_type == ResourceType.ROLE:
            return self._guild.get_role(discord_id)
        if resource_type in _CHANNEL_TYPES:
            return self._guild.get_channel(discord_id)
        # FORUM_POST / MESSAGE resolution requires the parent channel; handled elsewhere.
        return self._guild.get_channel(discord_id)

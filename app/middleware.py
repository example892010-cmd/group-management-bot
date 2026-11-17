"""Per-group protection middleware with independent SQLite settings."""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import Message

log = logging.getLogger(__name__)
LINK_RE = re.compile(r"(?:https?://|www\.|t\.me/|telegram\.me/)", re.IGNORECASE)
MEDIA_FIELDS = ("photo", "video", "animation", "audio", "document", "voice", "video_note")


class GroupProtectionMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.admin_cache: dict[tuple[int, int], tuple[bool, float]] = {}
        self.admin_cache_ttl = 20.0

    async def _is_admin(self, message: Message, user_id: int) -> bool:
        key = (message.chat.id, user_id)
        now = time.monotonic()
        cached = self.admin_cache.get(key)
        if cached and now - cached[1] < self.admin_cache_ttl:
            return cached[0]
        try:
            member = await message.bot.get_chat_member(message.chat.id, user_id)
            result = member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
        except Exception as exc:
            log.debug("Could not check admin state for %s in %s: %s", user_id, message.chat.id, exc)
            result = False
        self.admin_cache[key] = (result, now)
        return result

    async def __call__(self, handler: Callable[[Message, dict[str, Any]], Awaitable[Any]], event: Message, data: dict[str, Any]) -> Any:
        if not isinstance(event, Message) or event.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
            return await handler(event, data)

        store = data.get("store")
        settings = data.get("settings")
        if store is None or settings is None:
            return await handler(event, data)

        chat_id = event.chat.id
        user = event.from_user
        await store.register_group(chat_id, event.chat.title or "", event.chat.username or "")
        if await store.is_group_blocked(chat_id):
            return None

        global_settings = await store.get_settings()
        is_owner = bool(user and user.id in settings.owner_ids)
        if global_settings.get("maintenance_mode", False) and not is_owner:
            return None

        if user:
            await store.record_user(chat_id, user.id, user.username or "", user.full_name)
        for joined in event.new_chat_members or []:
            await store.record_user(chat_id, joined.id, joined.username or "", joined.full_name)
        await store.increment_stat("messages_seen")

        cfg = await store.get_group_settings(chat_id)
        if user and user.is_bot:
            return None

        # Bot protection: remove newly joined bots, but never the bot itself.
        if cfg.get("anti_bot", False) and event.new_chat_members:
            for member in event.new_chat_members:
                if member.is_bot and member.id != getattr(event.bot, "id", None):
                    try:
                        await event.bot.ban_chat_member(chat_id, member.id)
                    except Exception as exc:
                        log.warning("Could not remove joined bot %s from %s: %s", member.id, chat_id, exc)

        # Feature enforcement is skipped for admins and the configured bot owner.
        is_admin = is_owner
        if user and not is_admin:
            is_admin = await self._is_admin(event, user.id)

        if is_admin or not user:
            return await handler(event, data)

        text = event.text or event.caption or ""
        if cfg.get("anti_forward", False) or cfg.get("lock_forwards", False):
            if getattr(event, "forward_origin", None) is not None:
                await self._delete(event)
                return None

        if cfg.get("anti_link", False) or cfg.get("lock_links", False):
            # Catch visible URLs as well as clickable text links whose URL is hidden.
            entities = list(event.entities or []) + list(event.caption_entities or [])
            has_entity_link = any(
                getattr(getattr(entity, "type", None), "value", getattr(entity, "type", None))
                in {"url", "text_link"}
                for entity in entities
            )
            if (text and LINK_RE.search(text)) or has_entity_link:
                await self._delete(event)
                return None

        media_lock = cfg.get("lock_media", False)
        if media_lock and any(getattr(event, field, None) for field in MEDIA_FIELDS):
            await self._delete(event)
            return None
        if cfg.get("lock_stickers", False) and event.sticker:
            await self._delete(event)
            return None
        if cfg.get("lock_gifs", False) and event.animation:
            await self._delete(event)
            return None
        if cfg.get("lock_polls", False) and event.poll:
            await self._delete(event)
            return None
        if cfg.get("lock_messages", False) or cfg.get("lock_all", False):
            # Permit commands so admins can still manage settings; ordinary user commands are suppressed.
            if not (event.text and event.text.startswith("/")):
                await self._delete(event)
                return None

        duplicate_guard = data.get("duplicate_guard")
        if cfg.get("anti_spam", False) and text and duplicate_guard:
            if duplicate_guard.is_duplicate(chat_id, user.id, text):
                await self._delete(event)
                return None

        flood = data.get("flood")
        if cfg.get("anti_flood", True) and flood and flood.is_flooding(chat_id, user.id):
            await self._delete(event)
            return None

        slow_guard = data.get("slow_guard")
        seconds = int(cfg.get("slowmode_seconds", 0) or 0)
        if slow_guard and seconds and not (event.text and event.text.startswith("/")):
            if not slow_guard.allow(chat_id, user.id, seconds):
                await self._delete(event)
                return None

        return await handler(event, data)

    @staticmethod
    async def _delete(message: Message) -> None:
        try:
            await message.delete()
        except Exception as exc:
            log.debug("Message deletion failed in %s: %s", message.chat.id, exc)

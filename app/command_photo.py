"""Attach the owner's shared command photo to text command responses.

The middleware only acts while a slash-command message is being handled. It
leaves ordinary group replies, callback-button navigation, broadcasts and
/start (which has its own welcome-photo setting) untouched.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.methods import SendMessage, SendPhoto
from aiogram.types import Message


ACTIVE_COMMAND: ContextVar[str | None] = ContextVar("aniflix_active_command", default=None)


class CommandRequestContextMiddleware(BaseMiddleware):
    """Expose the current slash command to the Bot API session middleware."""

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        command_name: str | None = None
        text = getattr(event, "text", None)
        if isinstance(text, str) and text.startswith("/"):
            token = text.split(maxsplit=1)[0]
            command_name = token[1:].split("@", 1)[0].lower() or None
        token = ACTIVE_COMMAND.set(command_name)
        try:
            return await handler(event, data)
        finally:
            ACTIVE_COMMAND.reset(token)


def _copy_send_message_to_photo(method: SendMessage, photo_file_id: str) -> SendPhoto:
    """Build a SendPhoto request while preserving all shared API parameters."""
    values: dict[str, Any] = {
        "chat_id": method.chat_id,
        "photo": photo_file_id,
        "caption": method.text,
    }
    send_message_fields = getattr(SendMessage, "model_fields", {})
    send_photo_fields = getattr(SendPhoto, "model_fields", {})
    shared_fields = set(send_message_fields) & set(send_photo_fields)
    for field in shared_fields - {"chat_id", "text", "photo", "caption"}:
        value = getattr(method, field, None)
        if value is not None:
            values[field] = value
    entities = getattr(method, "entities", None)
    if entities and "caption_entities" in send_photo_fields:
        values["caption_entities"] = entities
    if send_photo_fields:
        values = {key: value for key, value in values.items() if key in send_photo_fields}
    return SendPhoto(**values)


class CommandPhotoApiMiddleware:
    """Turn command SendMessage responses into photo captions where possible."""

    def __init__(self, store: Any) -> None:
        self.store = store

    async def __call__(self, make_request, bot, method):
        command_name = ACTIVE_COMMAND.get()
        if (
            not command_name
            or command_name in {"start", "owner", "admin", "broadcast", "cancel"}
            or not isinstance(method, SendMessage)
        ):
            return await make_request(bot, method)

        settings = await self.store.get_settings()
        photo_file_id = settings.get("command_photo_file_id") or ""
        if not photo_file_id:
            return await make_request(bot, method)

        # Telegram captions are limited to 1024 characters. For longer command
        # outputs, send the image first and then preserve the complete text.
        if len(method.text) > 1024:
            photo_values: dict[str, Any] = {"chat_id": method.chat_id, "photo": photo_file_id}
            shared_fields = set(getattr(SendMessage, "model_fields", {})) & set(getattr(SendPhoto, "model_fields", {}))
            for field in shared_fields - {"chat_id", "text", "photo", "caption"}:
                value = getattr(method, field, None)
                if value is not None:
                    photo_values[field] = value
            # Keep the inline keyboard on the full text message, not duplicated
            # on both the leading image and the following long text response.
            photo_values.pop("reply_markup", None)
            model_fields = getattr(SendPhoto, "model_fields", {})
            if model_fields:
                photo_values = {key: value for key, value in photo_values.items() if key in model_fields}
            await make_request(bot, SendPhoto(**photo_values))
            return await make_request(bot, method)

        photo_method = _copy_send_message_to_photo(method, photo_file_id)
        return await make_request(bot, photo_method)

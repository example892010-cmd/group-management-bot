"""Application entry point, health endpoint and polling-session restart support."""
from __future__ import annotations

import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
)

from .command_catalog import group_command_pairs, owner_command_pairs, PRIVATE_COMMANDS
from .config import Settings
from .command_photo import CommandPhotoApiMiddleware, CommandRequestContextMiddleware
from .conversations import Cooldown
from .extra_handlers import router as extra_router
from .handlers import router as main_router
from .middleware import GroupProtectionMiddleware
from .moderation import DuplicateGuard, FloodGuard, JoinBurstGuard, SlowModeGuard
from .runtime import RuntimeControl
from .storage import SQLiteStore


def configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    default_log_path = Path(os.getenv("DATA_DIR", ".")).expanduser() / "logs" / "aniflix.log"
    log_path = Path(os.getenv("LOG_FILE", str(default_log_path))).expanduser()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers: list[logging.Handler] = [logging.StreamHandler(), RotatingFileHandler(
            log_path, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
        )]
    except OSError:
        handlers = [logging.StreamHandler()]
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )


configure_logging()
log = logging.getLogger(__name__)


async def health_handler(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "aniflix-group-management-bot"})


def group_commands() -> list[BotCommand]:
    return [BotCommand(command=name, description=description) for name, description in group_command_pairs()]


def private_commands() -> list[BotCommand]:
    return [BotCommand(command=name, description=description) for name, description in PRIVATE_COMMANDS]


def owner_commands() -> list[BotCommand]:
    return [BotCommand(command=name, description=description) for name, description in owner_command_pairs()]


async def run_async() -> None:
    settings = Settings.from_env()
    store = SQLiteStore(
        settings.database_path,
        settings.data_dir,
        seed_dir=Path(__file__).resolve().parent.parent,
    )
    await store.connect()

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=None))
    bot.session.middleware.register(CommandPhotoApiMiddleware(store))
    dp = Dispatcher(storage=MemoryStorage())
    runtime_control = RuntimeControl()
    flood = FloodGuard(limit=7, window_seconds=10.0)
    raid_guard = JoinBurstGuard(limit=6, window_seconds=15.0)
    cooldown = Cooldown(seconds=6.0)
    slow_guard = SlowModeGuard()
    duplicate_guard = DuplicateGuard()

    # Extra command router is included first so its command handlers run before
    # the legacy group's text fallback handler.
    dp.include_router(extra_router)
    dp.include_router(main_router)
    protection_middleware = GroupProtectionMiddleware()
    # Command context must wrap the message handler so outgoing text replies can
    # inherit the shared owner-configured command photo.
    dp.message.outer_middleware(CommandRequestContextMiddleware())
    dp.message.outer_middleware(protection_middleware)
    dp.workflow_data.update(
        store=store, settings=settings, cooldown=cooldown, flood=flood,
        raid_guard=raid_guard, slow_guard=slow_guard,
        duplicate_guard=duplicate_guard, runtime_control=runtime_control,
        protection_middleware=protection_middleware,
    )

    # Command-menu failures must not prevent polling from starting. The
    # decorated handlers remain available even if Telegram rejects a menu update.
    menu_updates = [
        ("group", group_commands(), BotCommandScopeAllGroupChats()),
        ("private", private_commands(), BotCommandScopeAllPrivateChats()),
    ]
    for owner_id in settings.owner_ids:
        menu_updates.append((f"owner {owner_id}", owner_commands(), BotCommandScopeChat(chat_id=owner_id)))
    for label, commands, scope in menu_updates:
        try:
            await bot.set_my_commands(commands, scope=scope)
        except Exception:
            log.exception("Could not update %s Telegram command menu; handlers remain registered", label)
    await bot.delete_webhook(drop_pending_updates=True)

    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=settings.port)
    await site.start()
    log.info("Health endpoint started on port %s", settings.port)

    polling_options = {
        "allowed_updates": dp.resolve_used_update_types(),
        "close_bot_session": False,
    }
    try:
        while True:
            runtime_control.restart_event.clear()
            polling_task = asyncio.create_task(dp.start_polling(bot, **polling_options))
            restart_task = asyncio.create_task(runtime_control.restart_event.wait())
            done, pending = await asyncio.wait(
                {polling_task, restart_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if restart_task in done and runtime_control.restart_event.is_set():
                log.warning("Owner requested a polling-session restart")
                await dp.stop_polling()
                await polling_task
                continue
            restart_task.cancel()
            await asyncio.gather(restart_task, return_exceptions=True)
            await polling_task
            break
    finally:
        await runner.cleanup()
        await bot.session.close()
        await store.close()


def run() -> None:
    asyncio.run(run_async())


if __name__ == "__main__":
    run()

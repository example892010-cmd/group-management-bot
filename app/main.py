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

from .config import Settings
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
    commands = [
        ("start", "Start the bot"), ("help", "Show all commands"),
        ("id", "Show user and group IDs"), ("info", "Show user information"),
        ("admins", "List group administrators"), ("staff", "List group staff"),
        ("rules", "View group rules"), ("report", "Report a message or member"), ("reports", "Review reports (admins)"),
        ("ping", "Check bot response"), ("about", "About this bot"),
        ("ban", "Ban a member (reply)"), ("unban", "Unban by user ID"),
        ("kick", "Remove a member (reply or ID)"), ("mute", "Mute a member (reply)"),
        ("unmute", "Unmute a member (reply)"), ("warn", "Warn a member (reply)"),
        ("warnings", "View a member's warnings"), ("resetwarns", "Clear a member's warnings"),
        ("purge", "Delete messages from a replied message"), ("pin", "Pin a replied message"),
        ("unpin", "Unpin a message"), ("promote", "Promote a member"), ("demote", "Demote an admin"),
        ("setwelcome", "Set a custom welcome"), ("welcome", "View or toggle welcome"),
        ("resetwelcome", "Reset the welcome message"), ("setgoodbye", "Set a custom goodbye"),
        ("goodbye", "View or toggle goodbye"), ("resetgoodbye", "Reset the goodbye message"),
        ("setrules", "Set this group's rules"), ("filter", "Add a keyword filter"),
        ("stop", "Remove a keyword filter"), ("filters", "List this group's filters"),
        ("save", "Save a group note"), ("get", "Get a group note"), ("notes", "List group notes"),
        ("antispam", "Toggle duplicate spam protection"), ("antiflood", "Toggle flood protection"),
        ("antilink", "Toggle link protection"), ("antiforward", "Toggle forward protection"),
        ("antibot", "Toggle anti-bot joins"), ("lock", "Lock a group feature"),
        ("unlock", "Unlock a group feature"), ("locks", "Show lock settings"),
        ("settings", "Show group settings"), ("setdescription", "Change group description"),
        ("settitle", "Change group title"), ("slowmode", "Set slowmode seconds"),
    ]
    return [BotCommand(command=name, description=description) for name, description in commands]


def private_commands() -> list[BotCommand]:
    return [BotCommand(command=name, description=description) for name, description in [
        ("start", "Start the bot"), ("help", "Show help"), ("about", "About this bot"),
    ]]


def owner_commands() -> list[BotCommand]:
    return [BotCommand(command=name, description=description) for name, description in [
        ("owner", "Open the owner command list"), ("stats", "View real bot statistics"),
        ("groups", "List registered groups"), ("users", "View recorded users"),
        ("broadcast", "Broadcast a replied message"), ("blockgroup", "Block a registered group"),
        ("unblockgroup", "Unblock a group"), ("leave", "Leave a registered group"),
        ("restart", "Restart the polling session"), ("maintenance", "Enable maintenance mode"),
        ("disablemaintenance", "Disable maintenance mode"), ("logs", "Download recent logs"),
        ("clearcache", "Clear in-memory caches"), ("backup", "Download a SQLite backup"),
    ]]


async def run_async() -> None:
    settings = Settings.from_env()
    store = SQLiteStore(
        settings.database_path,
        settings.data_dir,
        seed_dir=Path(__file__).resolve().parent.parent,
    )
    await store.connect()

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=None))
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
    dp.message.outer_middleware(protection_middleware)
    dp.workflow_data.update(
        store=store, settings=settings, cooldown=cooldown, flood=flood,
        raid_guard=raid_guard, slow_guard=slow_guard,
        duplicate_guard=duplicate_guard, runtime_control=runtime_control,
        protection_middleware=protection_middleware,
    )

    await bot.set_my_commands(group_commands(), scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands(private_commands(), scope=BotCommandScopeAllPrivateChats())
    for owner_id in settings.owner_ids:
        await bot.set_my_commands(owner_commands(), scope=BotCommandScopeChat(chat_id=owner_id))
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

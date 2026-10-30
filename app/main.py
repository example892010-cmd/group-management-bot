"""Application entry point and Render health endpoint."""
from __future__ import annotations

import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from .config import Settings
from .conversations import ConversationEngine, Cooldown
from .handlers import router
from .moderation import FloodGuard
from .storage import MongoStore

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger(__name__)


async def health_handler(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "aniflix-group-management-bot"})


async def run_async() -> None:
    settings = Settings.from_env()
    store = MongoStore(settings.mongo_url, settings.db_name, settings.data_dir)
    await store.connect()

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=None))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    dp.workflow_data.update(
        store=store,
        settings=settings,
        engine=ConversationEngine(),
        cooldown=Cooldown(seconds=6.0),
        flood=FloodGuard(limit=7, window_seconds=10.0),
    )
    await bot.set_my_commands([
        BotCommand(command="start", description="Start the bot"),
        BotCommand(command="myid", description="Show your numeric Telegram ID"),
        BotCommand(command="help", description="Show bot help"),
        BotCommand(command="admin", description="Open the owner admin panel"),
        BotCommand(command="cancel", description="Cancel an admin action"),
        BotCommand(command="warn", description="Warn a member (reply to message)"),
        BotCommand(command="mute", description="Mute a member (reply to message)"),
        BotCommand(command="unmute", description="Unmute a member (reply to message)"),
        BotCommand(command="ban", description="Ban a member (reply to message)"),
        BotCommand(command="unban", description="Unban a member by ID"),
    ])
    await bot.delete_webhook(drop_pending_updates=True)

    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=settings.port)
    await site.start()
    log.info("Health endpoint started on port %s", settings.port)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), close_bot_session=False)
    finally:
        await runner.cleanup()
        await bot.session.close()
        await store.close()


def run() -> None:
    asyncio.run(run_async())


if __name__ == "__main__":
    run()

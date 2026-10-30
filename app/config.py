"""Environment configuration for the ANIFLIX group bot."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    mongo_url: str
    db_name: str
    owner_ids: frozenset[int]
    bot_channel_username: str = "@ANIFLIXANIMETAMIL"
    port: int = 10000
    data_dir: Path = Path(".")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        token = os.getenv("BOT_TOKEN", "").strip()
        mongo_url = os.getenv("MONGODB_URL", "").strip()
        db_name = os.getenv("DB_NAME", "aniflix_group_bot").strip()
        owner_raw = os.getenv("OWNER_ID", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN is missing. Add your Telegram bot token to the environment.")
        if not mongo_url:
            raise RuntimeError("MONGODB_URL is missing. Add your MongoDB Atlas connection string.")
        if not owner_raw:
            raise RuntimeError("OWNER_ID is missing. Add your numeric Telegram user ID.")
        try:
            owner_ids = frozenset(int(part.strip()) for part in owner_raw.split(",") if part.strip())
        except ValueError as exc:
            raise RuntimeError("OWNER_ID must contain numeric Telegram user IDs, separated by commas.") from exc
        if not owner_ids:
            raise RuntimeError("At least one numeric OWNER_ID is required.")
        return cls(
            bot_token=token,
            mongo_url=mongo_url,
            db_name=db_name,
            owner_ids=owner_ids,
            bot_channel_username=os.getenv("BOT_CHANNEL_USERNAME", "@ANIFLIXANIMETAMIL").strip(),
            port=int(os.getenv("PORT", "10000")),
            data_dir=Path(os.getenv("DATA_DIR", ".")).resolve(),
        )

"""MongoDB persistence and TXT snapshot management."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, AsyncMongoClient, ReturnDocument

from .catalog import Catalog, normalize_title, parse_title_lines

log = logging.getLogger(__name__)

DEFAULT_SETTINGS: dict[str, Any] = {
    "conversation_enabled": True,
    "gif_reactions": True,
    "sticker_reactions": True,
    "spelling_correction": True,
    "anti_link": False,
    "anti_flood": True,
    "welcome_enabled": True,
    "tanglish_enabled": True,
    "english_enabled": True,
    "tamil_enabled": True,
}


class MongoStore:
    def __init__(self, mongo_url: str, db_name: str, data_dir: Path) -> None:
        self.client = AsyncMongoClient(mongo_url, serverSelectionTimeoutMS=12000)
        self.db = self.client[db_name]
        self.data_dir = data_dir
        self.anime = self.db["anime_titles"]
        self.settings = self.db["bot_settings"]
        self.stats = self.db["bot_stats"]
        self.admins = self.db["authorized_admins"]
        self.replies = self.db["custom_replies"]
        self.warnings = self.db["warnings"]
        self._catalog_lock = asyncio.Lock()
        self.catalog = Catalog()

    async def connect(self) -> None:
        await self.client.admin.command("ping")
        await self.anime.create_index([("status", ASCENDING)])
        await self.warnings.create_index([("chat_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
        await self.replies.create_index([("category", ASCENDING)])
        count = await self.anime.count_documents({})
        if count == 0:
            self.catalog = Catalog(
                available=self._read_txt("available_anime.txt"),
                unavailable=self._read_txt("unavailable_anime.txt"),
            )
            await self._write_catalog_to_db(self.catalog)
        else:
            docs = await self.anime.find({}, {"_id": 0, "title": 1, "status": 1}).to_list(length=None)
            available = [d["title"] for d in docs if d.get("status") == "available"]
            unavailable = [d["title"] for d in docs if d.get("status") == "unavailable"]
            self.catalog = Catalog(available, unavailable)
        await self._write_txt_snapshots(self.catalog)
        current = await self.settings.find_one({"_id": "global"})
        if current is None:
            await self.settings.insert_one({"_id": "global", **DEFAULT_SETTINGS})
        log.info("MongoDB connected; loaded %s available and %s unavailable anime titles", len(self.catalog.available), len(self.catalog.unavailable))

    async def close(self) -> None:
        await self.client.close()

    def _read_txt(self, filename: str) -> list[str]:
        path = self.data_dir / filename
        try:
            return parse_title_lines(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []

    async def _write_txt_snapshots(self, catalog: Catalog) -> None:
        await asyncio.to_thread(self._write_txt_snapshots_sync, catalog)

    def _write_txt_snapshots_sync(self, catalog: Catalog) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for status, filename in (("available", "available_anime.txt"), ("unavailable", "unavailable_anime.txt")):
            path = self.data_dir / filename
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(catalog.export_text(status), encoding="utf-8")
            temporary.replace(path)

    async def _write_catalog_to_db(self, catalog: Catalog) -> None:
        docs = [
            {"_id": normalize_title(title), "title": title, "status": status}
            for status in ("available", "unavailable")
            for title in catalog.titles(status) if normalize_title(title)
        ]
        await self.anime.delete_many({})
        if docs:
            await self.anime.insert_many(docs, ordered=False)

    async def get_catalog(self) -> Catalog:
        # The bot uses an in-memory catalog for matching; this returns a copy for safe edits.
        return Catalog(list(self.catalog.available), list(self.catalog.unavailable))

    async def save_catalog(self, catalog: Catalog) -> None:
        async with self._catalog_lock:
            await self._write_catalog_to_db(catalog)
            await self._write_txt_snapshots(catalog)
            self.catalog = Catalog(list(catalog.available), list(catalog.unavailable))

    async def get_settings(self) -> dict[str, Any]:
        doc = await self.settings.find_one({"_id": "global"}) or {}
        return {**DEFAULT_SETTINGS, **{k: v for k, v in doc.items() if k != "_id"}}

    async def set_setting(self, key: str, value: Any) -> None:
        if key not in DEFAULT_SETTINGS:
            raise ValueError(f"Unsupported setting: {key}")
        await self.settings.update_one({"_id": "global"}, {"$set": {key: value}}, upsert=True)

    async def add_admin(self, user_id: int) -> None:
        await self.admins.update_one({"_id": int(user_id)}, {"$set": {"added_at": datetime.now(timezone.utc)}}, upsert=True)

    async def remove_admin(self, user_id: int) -> None:
        await self.admins.delete_one({"_id": int(user_id)})

    async def is_authorized_admin(self, user_id: int, owner_ids: frozenset[int]) -> bool:
        return user_id in owner_ids or await self.admins.find_one({"_id": int(user_id)}) is not None

    async def list_admins(self) -> list[int]:
        return [int(doc["_id"]) async for doc in self.admins.find({}, {"_id": 1})]

    async def add_custom_reply(self, category: str, text: str) -> bool:
        clean = text.strip()
        if not clean:
            return False
        key = hashlib.sha256(f"{category}\0{clean}".encode("utf-8")).hexdigest()
        result = await self.replies.update_one(
            {"_id": key}, {"$setOnInsert": {"category": category, "text": clean}}, upsert=True
        )
        return result.upserted_id is not None

    async def get_custom_replies(self, category: str) -> list[str]:
        return [doc["text"] async for doc in self.replies.find({"category": category}, {"text": 1})]

    async def remove_custom_reply(self, category: str, text: str) -> bool:
        key = hashlib.sha256(f"{category}\0{text.strip()}".encode("utf-8")).hexdigest()
        result = await self.replies.delete_one({"_id": key})
        return result.deleted_count > 0

    async def increment_stat(self, name: str, amount: int = 1) -> None:
        await self.stats.update_one({"_id": "global"}, {"$inc": {name: amount}}, upsert=True)

    async def get_stats(self) -> dict[str, int]:
        doc = await self.stats.find_one({"_id": "global"}) or {}
        doc.pop("_id", None)
        return {key: int(value) for key, value in doc.items() if isinstance(value, (int, float))}

    async def add_warning(self, chat_id: int, user_id: int) -> int:
        doc = await self.warnings.find_one_and_update(
            {"chat_id": int(chat_id), "user_id": int(user_id)},
            {"$inc": {"count": 1}}, upsert=True, return_document=ReturnDocument.AFTER,
        )
        return int(doc.get("count", 1)) if doc else 1

    async def clear_warnings(self, chat_id: int, user_id: int) -> None:
        await self.warnings.delete_one({"chat_id": int(chat_id), "user_id": int(user_id)})

    async def warning_count(self, chat_id: int, user_id: int) -> int:
        doc = await self.warnings.find_one({"chat_id": int(chat_id), "user_id": int(user_id)})
        return int(doc.get("count", 0)) if doc else 0

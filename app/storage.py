"""SQLite persistence and TXT snapshot management."""
from __future__ import annotations

import asyncio
from contextlib import closing
import hashlib
import json
import logging
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


class SQLiteStore:
    """Small async-facing SQLite store; blocking SQLite work runs in worker threads."""

    def __init__(self, database_path: str | Path, data_dir: Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.data_dir = data_dir
        self._catalog_lock = asyncio.Lock()
        self.catalog = Catalog()

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.database_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    async def _run(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    def _initialize_sync(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS anime_titles (
                    normalized_title TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('available','unavailable'))
                );
                CREATE INDEX IF NOT EXISTS idx_anime_status ON anime_titles(status);
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bot_stats (
                    name TEXT PRIMARY KEY,
                    value INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS authorized_admins (
                    user_id INTEGER PRIMARY KEY,
                    added_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS custom_replies (
                    reply_key TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    text TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_replies_category ON custom_replies(category);
                CREATE TABLE IF NOT EXISTS conversation_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger_text TEXT NOT NULL,
                    normalized_trigger TEXT NOT NULL,
                    first_token TEXT NOT NULL,
                    reply_text TEXT NOT NULL,
                    UNIQUE(normalized_trigger, reply_text)
                );
                CREATE INDEX IF NOT EXISTS idx_conversation_first_token
                    ON conversation_entries(first_token);
                CREATE TABLE IF NOT EXISTS warnings (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(chat_id, user_id)
                );
            """)
            for key, value in DEFAULT_SETTINGS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO bot_settings(key, value) VALUES (?, ?)",
                    (key, json.dumps(value)),
                )

    async def connect(self) -> None:
        await self._run(self._initialize_sync)
        rows = await self._run(self._fetch_anime_sync)
        if not rows:
            self.catalog = Catalog(
                available=self._read_txt("available_anime.txt"),
                unavailable=self._read_txt("unavailable_anime.txt"),
            )
            await self._write_catalog_to_db(self.catalog)
        else:
            available = [r["title"] for r in rows if r["status"] == "available"]
            unavailable = [r["title"] for r in rows if r["status"] == "unavailable"]
            self.catalog = Catalog(available, unavailable)
        await self._write_txt_snapshots(self.catalog)
        # Seed only user-provided trigger/reply TXT entries. INSERT OR IGNORE makes
        # startup repeatable and preserves entries imported later through the panel.
        await self.import_conversation_text_files()
        log.info(
            "SQLite connected at %s; loaded %s available and %s unavailable anime titles",
            self.database_path, len(self.catalog.available), len(self.catalog.unavailable)
        )

    async def close(self) -> None:
        return None

    def _fetch_anime_sync(self):
        with closing(self._connect()) as conn, conn:
            return [dict(r) for r in conn.execute(
                "SELECT title, status FROM anime_titles ORDER BY title COLLATE NOCASE"
            ).fetchall()]

    def _read_txt(self, filename: str) -> list[str]:
        try:
            return parse_title_lines((self.data_dir / filename).read_text(encoding="utf-8"))
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

    def _replace_catalog_sync(self, catalog: Catalog) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM anime_titles")
            conn.executemany(
                "INSERT INTO anime_titles(normalized_title, title, status) VALUES (?, ?, ?)",
                [
                    (normalize_title(title), title, status)
                    for status in ("available", "unavailable")
                    for title in catalog.titles(status) if normalize_title(title)
                ],
            )

    async def _write_catalog_to_db(self, catalog: Catalog) -> None:
        await self._run(self._replace_catalog_sync, catalog)

    async def get_catalog(self) -> Catalog:
        return Catalog(list(self.catalog.available), list(self.catalog.unavailable))

    async def save_catalog(self, catalog: Catalog) -> None:
        async with self._catalog_lock:
            await self._write_catalog_to_db(catalog)
            await self._write_txt_snapshots(catalog)
            self.catalog = Catalog(list(catalog.available), list(catalog.unavailable))

    def _get_settings_sync(self):
        with closing(self._connect()) as conn, conn:
            return {r["key"]: json.loads(r["value"]) for r in conn.execute(
                "SELECT key, value FROM bot_settings"
            ).fetchall()}

    async def get_settings(self) -> dict[str, Any]:
        return {**DEFAULT_SETTINGS, **await self._run(self._get_settings_sync)}

    def _set_setting_sync(self, key: str, value: Any) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO bot_settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    async def set_setting(self, key: str, value: Any) -> None:
        if key not in DEFAULT_SETTINGS:
            raise ValueError(f"Unsupported setting: {key}")
        await self._run(self._set_setting_sync, key, value)

    def _add_admin_sync(self, user_id: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO authorized_admins(user_id, added_at) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET added_at=excluded.added_at",
                (int(user_id), datetime.now(timezone.utc).isoformat()),
            )

    async def add_admin(self, user_id: int) -> None:
        await self._run(self._add_admin_sync, user_id)

    def _remove_admin_sync(self, user_id: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM authorized_admins WHERE user_id=?", (int(user_id),))

    async def remove_admin(self, user_id: int) -> None:
        await self._run(self._remove_admin_sync, user_id)

    def _is_admin_sync(self, user_id: int) -> bool:
        with closing(self._connect()) as conn, conn:
            return conn.execute("SELECT 1 FROM authorized_admins WHERE user_id=?", (int(user_id),)).fetchone() is not None

    async def is_authorized_admin(self, user_id: int, owner_ids: frozenset[int]) -> bool:
        return user_id in owner_ids or await self._run(self._is_admin_sync, user_id)

    def _list_admins_sync(self) -> list[int]:
        with closing(self._connect()) as conn, conn:
            return [int(r["user_id"]) for r in conn.execute("SELECT user_id FROM authorized_admins ORDER BY user_id")]

    async def list_admins(self) -> list[int]:
        return await self._run(self._list_admins_sync)

    def _add_reply_sync(self, category: str, clean: str, key: str) -> bool:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO custom_replies(reply_key, category, text) VALUES (?, ?, ?)",
                (key, category, clean),
            )
            return cur.rowcount > 0

    async def add_custom_reply(self, category: str, text: str) -> bool:
        clean = text.strip()
        if not clean:
            return False
        key = hashlib.sha256(f"{category}\0{clean}".encode("utf-8")).hexdigest()
        return await self._run(self._add_reply_sync, category, clean, key)

    def _get_replies_sync(self, category: str) -> list[str]:
        with closing(self._connect()) as conn, conn:
            return [r["text"] for r in conn.execute(
                "SELECT text FROM custom_replies WHERE category=? ORDER BY rowid", (category,)
            )]

    async def get_custom_replies(self, category: str) -> list[str]:
        return await self._run(self._get_replies_sync, category)

    def _remove_reply_sync(self, key: str) -> bool:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute("DELETE FROM custom_replies WHERE reply_key=?", (key,))
            return cur.rowcount > 0

    async def remove_custom_reply(self, category: str, text: str) -> bool:
        key = hashlib.sha256(f"{category}\0{text.strip()}".encode("utf-8")).hexdigest()
        return await self._run(self._remove_reply_sync, key)


    @staticmethod
    def _prepare_conversation_rows(content: str) -> tuple[list[tuple[str, str, str, str]], int]:
        rows: list[tuple[str, str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        invalid = 0
        for raw_line in content.splitlines():
            line = raw_line.strip().lstrip("\ufeff")
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                invalid += 1
                continue
            trigger, reply = (part.strip() for part in line.split("=", 1))
            normalized = normalize_title(trigger)
            if not normalized or not reply or len(trigger) > 250 or len(reply) > 4000:
                invalid += 1
                continue
            pair = (normalized, reply)
            if pair in seen:
                continue
            seen.add(pair)
            rows.append((trigger, normalized, normalized.split()[0], reply))
        return rows, invalid

    def _import_conversations_sync(self, content: str) -> dict[str, int]:
        rows, invalid = self._prepare_conversation_rows(content)
        inserted = 0
        with closing(self._connect()) as conn:
            with conn:
                for start in range(0, len(rows), 1000):
                    before = conn.total_changes
                    conn.executemany(
                        """INSERT OR IGNORE INTO conversation_entries
                        (trigger_text, normalized_trigger, first_token, reply_text)
                        VALUES (?, ?, ?, ?)""",
                        rows[start:start + 1000],
                    )
                    inserted += conn.total_changes - before
        return {
            "valid": len(rows),
            "added": inserted,
            "duplicates": len(rows) - inserted,
            "invalid": invalid,
            "total": self._count_conversations_sync(),
        }

    def _count_conversations_sync(self) -> int:
        with closing(self._connect()) as conn, conn:
            return int(conn.execute("SELECT COUNT(*) FROM conversation_entries").fetchone()[0])

    async def import_conversations(self, content: str) -> dict[str, int]:
        """Append a bulk trigger = reply TXT file; existing pairs are never erased."""
        return await self._run(self._import_conversations_sync, content)

    def _import_conversation_text_files_sync(self, folder: Path) -> int:
        if not folder.exists():
            return 0
        imported = 0
        for path in sorted(folder.glob("*.txt")):
            try:
                content = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                continue
            report = self._import_conversations_sync(content)
            imported += report["added"]
        return imported

    async def import_conversation_text_files(self) -> int:
        folder = self.data_dir / "conversation_replies"
        if not folder.exists():
            folder = Path(__file__).resolve().parent.parent / "conversation_replies"
        return await self._run(self._import_conversation_text_files_sync, folder)

    def _get_conversation_reply_sync(self, message: str) -> str | None:
        normalized_message = normalize_title(message)
        if not normalized_message:
            return None
        tokens = list(dict.fromkeys(normalized_message.split()))
        placeholders = ",".join("?" for _ in tokens)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""SELECT normalized_trigger, reply_text
                    FROM conversation_entries
                    WHERE first_token IN ({placeholders})""",
                tokens,
            ).fetchall()
        message_padded = f" {normalized_message} "
        matched: list[tuple[int, str, str]] = []
        for row in rows:
            trigger = row["normalized_trigger"]
            if f" {trigger} " in message_padded:
                matched.append((len(trigger), trigger, row["reply_text"]))
        if not matched:
            return None
        longest = max(item[0] for item in matched)
        best = [(trigger, reply) for size, trigger, reply in matched if size == longest]
        # Randomize only among replies for the most-specific matched trigger(s).
        choices = list(dict.fromkeys(reply for _, reply in best))
        return random.choice(choices) if choices else None

    async def get_conversation_reply(self, message: str) -> str | None:
        return await self._run(self._get_conversation_reply_sync, message)

    async def count_conversations(self) -> int:
        return await self._run(self._count_conversations_sync)

    def _export_conversations_sync(self) -> str:
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                """SELECT trigger_text, reply_text FROM conversation_entries
                   ORDER BY normalized_trigger COLLATE NOCASE, id"""
            ).fetchall()
        return "".join(f"{row['trigger_text']} = {row['reply_text']}\\n" for row in rows)

    async def export_conversations(self) -> str:
        return await self._run(self._export_conversations_sync)

    def _increment_stat_sync(self, name: str, amount: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO bot_stats(name, value) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET value=value+excluded.value",
                (name, int(amount)),
            )

    async def increment_stat(self, name: str, amount: int = 1) -> None:
        await self._run(self._increment_stat_sync, name, amount)

    def _get_stats_sync(self) -> dict[str, int]:
        with closing(self._connect()) as conn, conn:
            return {r["name"]: int(r["value"]) for r in conn.execute("SELECT name, value FROM bot_stats")}

    async def get_stats(self) -> dict[str, int]:
        return await self._run(self._get_stats_sync)

    def _add_warning_sync(self, chat_id: int, user_id: int) -> int:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO warnings(chat_id, user_id, count) VALUES (?, ?, 1) "
                "ON CONFLICT(chat_id, user_id) DO UPDATE SET count=count+1",
                (int(chat_id), int(user_id)),
            )
            return int(conn.execute(
                "SELECT count FROM warnings WHERE chat_id=? AND user_id=?",
                (int(chat_id), int(user_id)),
            ).fetchone()["count"])

    async def add_warning(self, chat_id: int, user_id: int) -> int:
        return await self._run(self._add_warning_sync, chat_id, user_id)

    def _clear_warnings_sync(self, chat_id: int, user_id: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (int(chat_id), int(user_id)))

    async def clear_warnings(self, chat_id: int, user_id: int) -> None:
        await self._run(self._clear_warnings_sync, chat_id, user_id)

    def _warning_count_sync(self, chat_id: int, user_id: int) -> int:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT count FROM warnings WHERE chat_id=? AND user_id=?",
                (int(chat_id), int(user_id)),
            ).fetchone()
            return int(row["count"]) if row else 0

    async def warning_count(self, chat_id: int, user_id: int) -> int:
        return await self._run(self._warning_count_sync, chat_id, user_id)

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
    "maintenance_mode": False,
}


class SQLiteStore:
    """Small async-facing SQLite store; blocking SQLite work runs in worker threads."""

    def __init__(
        self, database_path: str | Path, data_dir: Path, seed_dir: Path | None = None
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.data_dir = Path(data_dir).expanduser().resolve()
        # Optional read-only source for first-run seed files when DATA_DIR is a
        # separate persistent mount (for example /var/data on Render).
        self.seed_dir = Path(seed_dir).expanduser().resolve() if seed_dir else None
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
                CREATE TABLE IF NOT EXISTS registered_groups (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    username TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    blocked INTEGER NOT NULL DEFAULT 0,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS group_settings (
                    chat_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY(chat_id, key)
                );
                CREATE TABLE IF NOT EXISTS group_rules (
                    chat_id INTEGER PRIMARY KEY,
                    rules TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS group_notes (
                    chat_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    PRIMARY KEY(chat_id, name)
                );
                CREATE TABLE IF NOT EXISTS group_filters (
                    chat_id INTEGER NOT NULL,
                    trigger_text TEXT NOT NULL,
                    reply_text TEXT NOT NULL,
                    PRIMARY KEY(chat_id, trigger_text)
                );
                CREATE TABLE IF NOT EXISTS warnings (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(chat_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS seen_users (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    full_name TEXT NOT NULL DEFAULT '',
                    last_seen TEXT NOT NULL,
                    PRIMARY KEY(chat_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_seen_users_user ON seen_users(user_id);
                CREATE TABLE IF NOT EXISTS group_reports (
                    report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    reporter_id INTEGER NOT NULL,
                    target_id INTEGER,
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
            """)
            # In-place migration for databases created by earlier bot versions.
            group_columns = {row[1] for row in conn.execute("PRAGMA table_info(registered_groups)")}
            if "blocked" not in group_columns:
                conn.execute("ALTER TABLE registered_groups ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0")
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
        persistent_snapshot = self.data_dir / filename
        source_path = persistent_snapshot
        if not source_path.is_file() and self.seed_dir is not None:
            source_path = self.seed_dir / filename
        try:
            return parse_title_lines(source_path.read_text(encoding="utf-8"))
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

    def _clear_conversations_sync(self) -> int:
        with closing(self._connect()) as conn, conn:
            before = int(conn.execute("SELECT COUNT(*) FROM conversation_entries").fetchone()[0])
            conn.execute("DELETE FROM conversation_entries")
            # Reset the auto-increment counter so the cleared library starts fresh.
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'conversation_entries'")
            return before

    async def clear_conversations(self) -> int:
        """Delete every saved custom conversation trigger/reply pair."""
        return await self._run(self._clear_conversations_sync)

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

    def _register_group_sync(self, chat_id: int, title: str, username: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn, conn:
            conn.execute("""INSERT INTO registered_groups(chat_id,title,username,active,first_seen,last_seen)
                VALUES(?,?,?,1,?,?) ON CONFLICT(chat_id) DO UPDATE SET
                title=excluded.title, username=excluded.username, active=1, last_seen=excluded.last_seen""",
                (int(chat_id), title or "", username or "", now, now))

    async def register_group(self, chat_id: int, title: str, username: str = "") -> None:
        await self._run(self._register_group_sync, chat_id, title, username)

    def _list_groups_sync(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn, conn:
            return [dict(r) for r in conn.execute("SELECT * FROM registered_groups WHERE active=1 ORDER BY first_seen")]

    async def list_groups(self) -> list[dict[str, Any]]:
        return await self._run(self._list_groups_sync)

    def _deactivate_group_sync(self, chat_id: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE registered_groups SET active=0, last_seen=? WHERE chat_id=?", (datetime.now(timezone.utc).isoformat(), int(chat_id)))

    async def deactivate_group(self, chat_id: int) -> None:
        await self._run(self._deactivate_group_sync, chat_id)

    def _set_group_setting_sync(self, chat_id: int, key: str, value: Any) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("""INSERT INTO group_settings(chat_id,key,value) VALUES(?,?,?)
                ON CONFLICT(chat_id,key) DO UPDATE SET value=excluded.value""",
                (int(chat_id), key, json.dumps(value)))

    async def set_group_setting(self, chat_id: int, key: str, value: Any) -> None:
        allowed = {
            "anti_link", "anti_flood", "anti_raid", "anti_spam", "anti_forward",
            "anti_bot", "welcome_enabled", "goodbye_enabled", "welcome_text",
            "goodbye_text", "slowmode_seconds", "lock_all", "lock_media",
            "lock_stickers", "lock_gifs", "lock_links", "lock_polls",
            "lock_forwards", "lock_messages", "permissions_baseline",
        }
        if key not in allowed:
            raise ValueError("Unsupported group setting")
        await self._run(self._set_group_setting_sync, chat_id, key, value)

    def _get_group_settings_sync(self, chat_id: int) -> dict[str, Any]:
        with closing(self._connect()) as conn, conn:
            return {r["key"]: json.loads(r["value"]) for r in conn.execute(
                "SELECT key,value FROM group_settings WHERE chat_id=?", (int(chat_id),))}

    async def get_group_settings(self, chat_id: int) -> dict[str, Any]:
        return await self._run(self._get_group_settings_sync, chat_id)

    def _set_rules_sync(self, chat_id: int, rules: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("INSERT INTO group_rules(chat_id,rules) VALUES(?,?) ON CONFLICT(chat_id) DO UPDATE SET rules=excluded.rules", (int(chat_id), rules))

    async def set_rules(self, chat_id: int, rules: str) -> None:
        await self._run(self._set_rules_sync, chat_id, rules)

    def _get_rules_sync(self, chat_id: int) -> str:
        with closing(self._connect()) as conn, conn:
            row = conn.execute("SELECT rules FROM group_rules WHERE chat_id=?", (int(chat_id),)).fetchone()
            return row["rules"] if row else "No group rules have been set yet."

    async def get_rules(self, chat_id: int) -> str:
        return await self._run(self._get_rules_sync, chat_id)

    def _save_note_sync(self, chat_id: int, name: str, content: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("INSERT INTO group_notes(chat_id,name,content) VALUES(?,?,?) ON CONFLICT(chat_id,name) DO UPDATE SET content=excluded.content", (int(chat_id), name.casefold(), content))

    async def save_note(self, chat_id: int, name: str, content: str) -> None:
        await self._run(self._save_note_sync, chat_id, name, content)

    def _get_note_sync(self, chat_id: int, name: str) -> str | None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute("SELECT content FROM group_notes WHERE chat_id=? AND name=?", (int(chat_id), name.casefold())).fetchone()
            return row["content"] if row else None

    async def get_note(self, chat_id: int, name: str) -> str | None:
        return await self._run(self._get_note_sync, chat_id, name)

    def _list_notes_sync(self, chat_id: int) -> list[str]:
        with closing(self._connect()) as conn, conn:
            return [r["name"] for r in conn.execute("SELECT name FROM group_notes WHERE chat_id=? ORDER BY name", (int(chat_id),))]

    async def list_notes(self, chat_id: int) -> list[str]:
        return await self._run(self._list_notes_sync, chat_id)

    def _list_filters_sync(self, chat_id: int) -> list[str]:
        with closing(self._connect()) as conn, conn:
            return [r["trigger_text"] for r in conn.execute(
                "SELECT trigger_text FROM group_filters WHERE chat_id=? ORDER BY trigger_text", (int(chat_id),)
            )]

    async def list_filters(self, chat_id: int) -> list[str]:
        return await self._run(self._list_filters_sync, chat_id)

    def _save_filter_sync(self, chat_id: int, trigger: str, reply: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("INSERT INTO group_filters(chat_id,trigger_text,reply_text) VALUES(?,?,?) ON CONFLICT(chat_id,trigger_text) DO UPDATE SET reply_text=excluded.reply_text", (int(chat_id), trigger.casefold(), reply))

    async def save_filter(self, chat_id: int, trigger: str, reply: str) -> None:
        await self._run(self._save_filter_sync, chat_id, trigger, reply)

    def _remove_filter_sync(self, chat_id: int, trigger: str) -> bool:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute("DELETE FROM group_filters WHERE chat_id=? AND trigger_text=?", (int(chat_id), trigger.casefold()))
            return cur.rowcount > 0

    async def remove_filter(self, chat_id: int, trigger: str) -> bool:
        return await self._run(self._remove_filter_sync, chat_id, trigger)

    def _get_filter_sync(self, chat_id: int, text: str) -> str | None:
        with closing(self._connect()) as conn, conn:
            rows = conn.execute("SELECT trigger_text,reply_text FROM group_filters WHERE chat_id=? ORDER BY length(trigger_text) DESC", (int(chat_id),)).fetchall()
            folded = text.casefold()
            for row in rows:
                if row["trigger_text"] in folded:
                    return row["reply_text"]
            return None

    async def get_filter_reply(self, chat_id: int, text: str) -> str | None:
        return await self._run(self._get_filter_sync, chat_id, text)

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


    def _record_user_sync(self, chat_id: int, user_id: int, username: str, full_name: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """INSERT INTO seen_users(chat_id,user_id,username,full_name,last_seen)
                VALUES(?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET
                username=excluded.username, full_name=excluded.full_name, last_seen=excluded.last_seen""",
                (int(chat_id), int(user_id), username or "", full_name or "", now),
            )

    async def record_user(self, chat_id: int, user_id: int, username: str = "", full_name: str = "") -> None:
        await self._run(self._record_user_sync, chat_id, user_id, username, full_name)

    def _user_stats_sync(self) -> tuple[int, list[dict[str, Any]]]:
        with closing(self._connect()) as conn, conn:
            count = int(conn.execute("SELECT COUNT(DISTINCT user_id) FROM seen_users").fetchone()[0])
            rows = [dict(row) for row in conn.execute(
                "SELECT user_id, username, full_name, MAX(last_seen) AS last_seen "
                "FROM seen_users GROUP BY user_id ORDER BY last_seen DESC LIMIT 100"
            ).fetchall()]
            return count, rows

    async def get_user_stats(self) -> tuple[int, list[dict[str, Any]]]:
        return await self._run(self._user_stats_sync)

    def _set_group_blocked_sync(self, chat_id: int, blocked: bool) -> bool:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "UPDATE registered_groups SET blocked=? WHERE chat_id=? AND active=1",
                (1 if blocked else 0, int(chat_id)),
            )
            return cur.rowcount > 0

    async def set_group_blocked(self, chat_id: int, blocked: bool) -> bool:
        return await self._run(self._set_group_blocked_sync, chat_id, blocked)

    def _is_group_blocked_sync(self, chat_id: int) -> bool:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT blocked FROM registered_groups WHERE chat_id=? AND active=1", (int(chat_id),)
            ).fetchone()
            return bool(row["blocked"]) if row else False

    async def is_group_blocked(self, chat_id: int) -> bool:
        return await self._run(self._is_group_blocked_sync, chat_id)

    def _add_report_sync(self, chat_id: int, reporter_id: int, target_id: int | None, reason: str) -> int:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO group_reports(chat_id,reporter_id,target_id,reason,created_at) VALUES(?,?,?,?,?)",
                (int(chat_id), int(reporter_id), int(target_id) if target_id is not None else None,
                 (reason or "")[:1000], datetime.now(timezone.utc).isoformat()),
            )
            return int(cur.lastrowid)

    async def add_report(self, chat_id: int, reporter_id: int, target_id: int | None, reason: str = "") -> int:
        return await self._run(self._add_report_sync, chat_id, reporter_id, target_id, reason)

    def _report_count_sync(self) -> int:
        with closing(self._connect()) as conn, conn:
            return int(conn.execute("SELECT COUNT(*) FROM group_reports").fetchone()[0])

    async def count_reports(self) -> int:
        return await self._run(self._report_count_sync)

    def _list_reports_sync(self, chat_id: int, limit: int) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn, conn:
            return [dict(row) for row in conn.execute(
                "SELECT report_id, reporter_id, target_id, reason, created_at FROM group_reports "
                "WHERE chat_id=? ORDER BY report_id DESC LIMIT ?", (int(chat_id), max(1, min(int(limit), 50)))
            ).fetchall()]

    async def list_reports(self, chat_id: int, limit: int = 10) -> list[dict[str, Any]]:
        return await self._run(self._list_reports_sync, chat_id, limit)

    def _backup_sync(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(str(self.database_path), timeout=30)
        target = sqlite3.connect(str(destination), timeout=30)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return destination

    async def create_backup(self, destination: str | Path) -> Path:
        return await self._run(self._backup_sync, Path(destination).expanduser().resolve())

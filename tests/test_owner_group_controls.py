import sqlite3

import pytest

from app.storage import SQLiteStore


@pytest.mark.asyncio
async def test_seen_users_are_unique_across_groups_and_reports_are_counted(tmp_path):
    store = SQLiteStore(tmp_path / "owner.db", tmp_path)
    await store.connect()
    await store.record_user(-1001, 55, "anime_fan", "Anime Fan")
    await store.record_user(-1002, 55, "anime_fan", "Anime Fan")
    await store.record_user(-1002, 56, "another", "Another User")
    total, users = await store.get_user_stats()
    assert total == 2
    assert {row["user_id"] for row in users} == {55, 56}
    await store.add_report(-1001, 55, 56, "Please review this message")
    assert await store.count_reports() == 1
    await store.close()


@pytest.mark.asyncio
async def test_blocked_groups_are_independent_and_survive_registration_updates(tmp_path):
    store = SQLiteStore(tmp_path / "blocked.db", tmp_path)
    await store.connect()
    await store.register_group(-2001, "Group A")
    await store.register_group(-2002, "Group B")
    assert await store.set_group_blocked(-2001, True)
    assert await store.is_group_blocked(-2001) is True
    assert await store.is_group_blocked(-2002) is False
    await store.register_group(-2001, "Group A renamed")
    assert await store.is_group_blocked(-2001) is True
    assert await store.set_group_blocked(-2001, False)
    assert await store.is_group_blocked(-2001) is False
    await store.close()


@pytest.mark.asyncio
async def test_new_group_settings_filters_and_global_maintenance_persist(tmp_path):
    store = SQLiteStore(tmp_path / "settings.db", tmp_path)
    await store.connect()
    await store.set_group_setting(-3001, "anti_forward", True)
    await store.set_group_setting(-3001, "welcome_text", "Welcome {mention}")
    await store.set_group_setting(-3001, "slowmode_seconds", 12)
    await store.set_group_setting(-3002, "anti_forward", False)
    cfg_a = await store.get_group_settings(-3001)
    cfg_b = await store.get_group_settings(-3002)
    assert cfg_a["anti_forward"] is True
    assert cfg_a["welcome_text"] == "Welcome {mention}"
    assert cfg_a["slowmode_seconds"] == 12
    assert cfg_b["anti_forward"] is False
    assert "welcome_text" not in cfg_b
    await store.set_setting("maintenance_mode", True)
    assert (await store.get_settings())["maintenance_mode"] is True
    await store.close()


@pytest.mark.asyncio
async def test_sqlite_backup_is_consistent_and_readable(tmp_path):
    store = SQLiteStore(tmp_path / "primary.db", tmp_path)
    await store.connect()
    await store.register_group(-4001, "Backup Test")
    backup = await store.create_backup(tmp_path / "backups" / "snapshot.db")
    assert backup.exists()
    with sqlite3.connect(backup) as conn:
        row = conn.execute("SELECT title FROM registered_groups WHERE chat_id=-4001").fetchone()
    assert row == ("Backup Test",)
    await store.close()


@pytest.mark.asyncio
async def test_legacy_group_schema_migrates_without_dropping_data(tmp_path):
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE registered_groups (
            chat_id INTEGER PRIMARY KEY, title TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
        )""")
        conn.execute("INSERT INTO registered_groups VALUES(-5001,'Legacy Group','',1,'now','now')")
    store = SQLiteStore(db, tmp_path)
    await store.connect()
    groups = await store.list_groups()
    assert groups[0]["chat_id"] == -5001
    assert groups[0]["title"] == "Legacy Group"
    assert groups[0]["blocked"] == 0
    await store.close()


@pytest.mark.asyncio
async def test_anime_seed_files_copy_to_new_persistent_data_directory(tmp_path):
    seed_dir = tmp_path / "repository"
    data_dir = tmp_path / "persistent"
    seed_dir.mkdir()
    data_dir.mkdir()
    (seed_dir / "available_anime.txt").write_text("Naruto\nJujutsu Kaisen\n", encoding="utf-8")
    (seed_dir / "unavailable_anime.txt").write_text("Example Unavailable\n", encoding="utf-8")

    store = SQLiteStore(data_dir / "bot.db", data_dir, seed_dir=seed_dir)
    await store.connect()
    catalog = await store.get_catalog()

    assert set(catalog.available) == {"Naruto", "Jujutsu Kaisen"}
    assert set(catalog.unavailable) == {"Example Unavailable"}
    assert (data_dir / "available_anime.txt").read_text(encoding="utf-8").strip()
    await store.close()


@pytest.mark.asyncio
async def test_persistent_anime_snapshot_takes_precedence_over_repository_seed(tmp_path):
    seed_dir = tmp_path / "repository"
    data_dir = tmp_path / "persistent"
    seed_dir.mkdir()
    data_dir.mkdir()
    (seed_dir / "available_anime.txt").write_text("Bundled Title\n", encoding="utf-8")
    (data_dir / "available_anime.txt").write_text("User Saved Title\n", encoding="utf-8")
    (data_dir / "unavailable_anime.txt").write_text("", encoding="utf-8")

    store = SQLiteStore(data_dir / "bot.db", data_dir, seed_dir=seed_dir)
    await store.connect()
    catalog = await store.get_catalog()

    assert catalog.available == ["User Saved Title"]
    await store.close()

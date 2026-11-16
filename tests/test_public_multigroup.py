import pytest
from app.storage import SQLiteStore


@pytest.mark.asyncio
async def test_group_settings_are_isolated(tmp_path):
    store = SQLiteStore(tmp_path / "groups.db", tmp_path)
    await store.connect()
    await store.register_group(-1001, "Group One")
    await store.register_group(-1002, "Group Two")
    await store.set_group_setting(-1001, "anti_link", True)
    assert (await store.get_group_settings(-1001))["anti_link"] is True
    assert "anti_link" not in await store.get_group_settings(-1002)
    groups = await store.list_groups()
    assert {g["chat_id"] for g in groups} == {-1001, -1002}
    await store.close()


@pytest.mark.asyncio
async def test_rules_notes_and_filters_are_group_scoped(tmp_path):
    store = SQLiteStore(tmp_path / "content.db", tmp_path)
    await store.connect()
    await store.set_rules(-2001, "Be respectful")
    await store.save_note(-2001, "welcome", "Welcome to group one")
    await store.save_filter(-2001, "hello there", "Hello from group one")
    assert await store.get_rules(-2001) == "Be respectful"
    assert "No group rules" in await store.get_rules(-2002)
    assert await store.get_note(-2001, "welcome") == "Welcome to group one"
    assert await store.get_note(-2002, "welcome") is None
    assert await store.get_filter_reply(-2001, "well hello there friend") == "Hello from group one"
    assert await store.get_filter_reply(-2002, "hello there") is None
    assert await store.remove_filter(-2001, "hello there") is True
    assert await store.remove_filter(-2001, "hello there") is False
    await store.close()

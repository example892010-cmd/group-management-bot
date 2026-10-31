import pytest

from app.storage import SQLiteStore


@pytest.mark.asyncio
async def test_bulk_import_is_additive_deduplicated_and_matches_whole_phrases(tmp_path):
    store = SQLiteStore(tmp_path / "bot.db", tmp_path)
    await store.connect()
    baseline = await store.count_conversations()

    report = await store.import_conversations(
        "# sample library\n"
        "zztesthello = Hey bro!\n"
        "zztestgreeting = Hello there!\n"
        "zztesthello = Hey bro!\n"
        "zztestthis = This is a different trigger.\n"
        "broken line\n"
    )

    assert report["added"] == 3
    assert report["duplicates"] == 0
    assert report["invalid"] == 1
    assert await store.get_conversation_reply("zztesthello") == "Hey bro!"
    assert await store.get_conversation_reply("zztestthis") == "This is a different trigger."
    assert await store.get_conversation_reply("zztesthelloish") is None
    assert await store.get_conversation_reply("unmatched message") is None

    second = await store.import_conversations("zztesthello = Hey bro!\nzztesthello = New reply!\n")
    assert second["added"] == 1
    assert second["duplicates"] == 1
    assert await store.count_conversations() == baseline + 4

    exported = await store.export_conversations()
    assert "zztesthello = Hey bro!" in exported
    assert "zztesthello = New reply!" in exported
    await store.close()


@pytest.mark.asyncio
async def test_large_import_is_chunked_and_counted(tmp_path):
    store = SQLiteStore(tmp_path / "large.db", tmp_path)
    await store.connect()
    baseline = await store.count_conversations()
    content = "".join(f"trigger{i} = reply{i}\n" for i in range(100_000))
    report = await store.import_conversations(content)
    assert report["added"] == 100_000
    assert report["total"] == baseline + 100_000
    assert await store.get_conversation_reply("trigger99999") == "reply99999"
    await store.close()

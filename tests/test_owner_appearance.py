"""Regression coverage for owner-only welcome and command-photo controls."""
from pathlib import Path
import ast

import pytest

from app.storage import DEFAULT_SETTINGS, SQLiteStore

ROOT = Path(__file__).resolve().parents[1]


def _function_source(path: str, function_name: str) -> str:
    source = (ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} was not found in {path}")


def test_welcome_and_command_photo_settings_are_registered_defaults():
    assert DEFAULT_SETTINGS["welcome_message_text"]
    assert DEFAULT_SETTINGS["welcome_photo_file_id"] == ""
    assert DEFAULT_SETTINGS["command_photo_file_id"] == ""


@pytest.mark.asyncio
async def test_welcome_and_command_photo_settings_persist_in_sqlite(tmp_path):
    store = SQLiteStore(tmp_path / "appearance.db", tmp_path)
    await store.connect()
    await store.set_setting("welcome_message_text", "Hello ANIFLIX users!")
    await store.set_setting("welcome_photo_file_id", "telegram-welcome-photo-file-id")
    await store.set_setting("command_photo_file_id", "telegram-command-photo-file-id")

    # Re-open the same database to confirm these settings survive a restart.
    reopened = SQLiteStore(tmp_path / "appearance.db", tmp_path)
    await reopened.connect()
    settings = await reopened.get_settings()
    assert settings["welcome_message_text"] == "Hello ANIFLIX users!"
    assert settings["welcome_photo_file_id"] == "telegram-welcome-photo-file-id"
    assert settings["command_photo_file_id"] == "telegram-command-photo-file-id"
    await store.close()
    await reopened.close()


def test_owner_command_opens_the_inline_panel_not_a_text_command_dump():
    source = _function_source("app/extra_handlers.py", "owner_command")
    assert "main_menu()" in source
    assert "reply_markup" in source
    assert "owner_help_text()" not in source


def test_appearance_callbacks_and_upload_handlers_require_owner_authorization():
    source = _function_source("app/handlers.py", "appearance_actions")
    assert "_authorized_callback(callback, store, settings)" in source
    assert '"welcome_photo"' in source
    assert '"command_photo"' in source
    assert '"clear_welcome_photo"' in source
    assert '"clear_command_photo"' in source

    for name in ("receive_welcome_photo", "receive_command_photo", "receive_welcome_text"):
        handler = _function_source("app/handlers.py", name)
        assert "is_panel_admin(message.from_user.id, store, settings)" in handler


def test_start_uses_custom_welcome_photo_and_exposes_help_inline_button():
    start = _function_source("app/extra_handlers.py", "public_start_command")
    assert "welcome_message_text" in start
    assert "welcome_photo_file_id" in start
    assert "answer_photo" in start
    assert 'if len(text) > 1024' in start
    source = (ROOT / "app/extra_handlers.py").read_text(encoding="utf-8")
    assert 'text="❓ Browse Help"' in source


def test_command_photo_is_applied_only_during_non_start_slash_command_responses():
    source = (ROOT / "app/command_photo.py").read_text(encoding="utf-8")
    assert "ACTIVE_COMMAND" in source
    assert 'command_name in {"start", "owner", "admin", "broadcast", "cancel"}' in source
    assert '"owner", "admin", "broadcast", "cancel"' in source
    assert "command_photo_file_id" in source
    assert "isinstance(method, SendMessage)" in source
    assert "ownerpanel:broadcast_" not in source
    assert "len(method.text) > 1024" in source
    assert "return await make_request(bot, method)" in source


def test_about_version_remains_quoted_and_owner_developer_identity_is_unchanged():
    from app.presentation import VERSION, about_text

    about = about_text()
    assert VERSION == "1.2.0"
    assert f'"{VERSION}"' in about
    assert "Owner: @TANJIROKAMADO404" in about
    assert "Developer: @TANJIROKAMADO404" in about


def test_global_owner_tools_are_wired_to_inline_callback_actions():
    keyboard_source = (ROOT / "app/keyboards.py").read_text(encoding="utf-8")
    handler_source = (ROOT / "app/handlers.py").read_text(encoding="utf-8")
    for action in ("stats", "groups", "users", "broadcast", "block", "unblock",
                   "leave", "maintenance", "restart", "clearcache", "logs", "backup"):
        assert f'"ownerpanel:{action}"' in keyboard_source
        assert f'action == "{action}"' in handler_source or f'action in {{"block", "unblock", "leave"}}' in handler_source
    assert '"panel:global"' in keyboard_source
    assert "def global_owner_menu" in keyboard_source
    assert 'F.data.startswith("ownerpanel:")' in handler_source


def test_owner_panel_is_protected_for_private_owner_callbacks():
    source = _function_source("app/handlers.py", "owner_panel_actions")
    assert "_authorized_callback(callback, store, settings)" in source
    auth = _function_source("app/handlers.py", "_authorized_callback")
    assert "ChatType.PRIVATE" in auth
    assert "is_panel_admin(callback.from_user.id, store, settings)" in auth

"""Guard the command handler permission boundaries against accidental regressions."""
from __future__ import annotations

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def function_source(file_name: str, function_name: str) -> str:
    tree = ast.parse((APP_DIR / file_name).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return ast.unparse(node)
    raise AssertionError(f"Missing function {function_name} in {file_name}")


def test_group_admin_command_helpers_enforce_current_chat_admin_status():
    main_handlers = {
        "set_rules_command", "save_note_command", "add_filter_command",
        "remove_filter_command", "warn_command", "mute_command",
        "unmute_command", "ban_command", "unban_command",
    }
    for name in main_handlers:
        source = function_source("handlers.py", name)
        assert "is_chat_admin" in source, name

    extra_handlers = {
        "kick_command", "warnings_command", "reset_warnings_command", "purge_command",
        "pin_command", "unpin_command", "promote_command", "demote_command",
        "set_welcome_command", "reset_welcome_command", "set_goodbye_command",
        "reset_goodbye_command", "set_description_command", "set_title_command",
        "slowmode_command",
    }
    for name in extra_handlers:
        source = function_source("extra_handlers.py", name)
        assert "require_group_admin" in source, name

    assert "require_group_admin" in function_source("extra_handlers.py", "_toggle")
    assert "require_group_admin" in function_source("extra_handlers.py", "_lock_change")


def test_group_admin_verification_explains_bot_permission_failure():
    main_check = function_source("handlers.py", "is_chat_admin")
    extra_check = function_source("extra_handlers.py", "require_group_admin")
    assert "couldn't verify" in main_check
    assert "administrator" in main_check
    assert "couldn't verify" in extra_check


def test_every_owner_control_checks_owner_identity_or_owner_helper():
    owner_direct_checks = {
        "owner_groups_command", "owner_stats_command", "broadcast_command",
    }
    for name in owner_direct_checks:
        source = function_source("handlers.py", name)
        assert "settings.owner_ids" in source, name

    owner_helper_checks = {
        "owner_command", "users_command", "block_group_command", "unblock_group_command",
        "leave_group_command", "maintenance_command", "disable_maintenance_command",
        "restart_command", "clear_cache_command", "backup_command", "logs_command",
    }
    for name in owner_helper_checks:
        source = function_source("extra_handlers.py", name)
        assert "owner_private" in source, name

    assert "is_panel_admin" in function_source("handlers.py", "admin_command")
    assert "settings.owner_ids" in function_source("handlers.py", "broadcast_callback")

"""Regression tests tying command decorators, Telegram menus and help pages together."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from app.command_catalog import (
    GROUP_COMMAND_SECTIONS,
    PRIVATE_COMMANDS,
    OWNER_COMMANDS,
    group_command_pairs,
    owner_command_pairs,
)
from app.presentation import (
    VERSION, about_text, help_home_text, help_section_text, owner_help_text,
)

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def registered_commands() -> Counter[str]:
    result: Counter[str] = Counter()
    for file_name in ("handlers.py", "extra_handlers.py"):
        tree = ast.parse((APP_DIR / file_name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                for call in ast.walk(decorator):
                    if (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)
                        and call.func.id == "Command"
                        and call.args
                        and isinstance(call.args[0], ast.Constant)
                        and isinstance(call.args[0].value, str)
                    ):
                        result[call.args[0].value] += 1
    return result


def test_every_required_public_and_group_admin_command_has_one_handler():
    expected = {
        "start", "help", "id", "info", "admins", "staff", "rules", "report", "ping", "about",
        "ban", "unban", "kick", "mute", "unmute", "warn", "warnings", "resetwarns",
        "purge", "pin", "unpin", "promote", "demote", "setwelcome", "welcome",
        "resetwelcome", "setgoodbye", "goodbye", "resetgoodbye", "setrules", "filter",
        "stop", "filters", "save", "get", "notes", "antispam", "antiflood", "antilink",
        "antiforward", "antibot", "lock", "unlock", "locks", "settings", "setdescription",
        "settitle", "slowmode",
    }
    actual = registered_commands()
    assert expected <= actual.keys()
    assert all(actual[name] == 1 for name in expected)


def test_every_required_owner_command_has_one_handler():
    expected = {
        "owner", "stats", "groups", "users", "broadcast", "blockgroup", "unblockgroup",
        "leave", "restart", "maintenance", "disablemaintenance", "logs", "clearcache", "backup",
    }
    actual = registered_commands()
    assert expected <= actual.keys()
    assert all(actual[name] == 1 for name in expected)


def test_no_duplicate_command_handlers_are_registered():
    duplicates = {name: count for name, count in registered_commands().items() if count > 1}
    assert duplicates == {}


def test_group_menu_and_help_pages_cover_the_same_commands():
    menu_names = {name for name, _ in group_command_pairs()}
    registered = registered_commands()
    assert menu_names <= registered.keys()
    assert all(registered[name] == 1 for name in menu_names)
    section_names = {
        name
        for _, commands in GROUP_COMMAND_SECTIONS.values()
        for name, _ in commands
    }
    assert menu_names == section_names
    for section_key, (_, commands) in GROUP_COMMAND_SECTIONS.items():
        page = help_section_text(section_key)
        assert page is not None
        for name, _ in commands:
            assert f"/{name}" in page


def test_owner_menu_contains_owner_commands_and_base_private_commands():
    names = {name for name, _ in owner_command_pairs()}
    registered = registered_commands()
    assert names <= registered.keys()
    assert all(registered[name] == 1 for name in names)
    assert {name for name, _ in PRIVATE_COMMANDS} <= names
    assert {name for name, _ in OWNER_COMMANDS} <= names
    page = owner_help_text()
    for name, _ in OWNER_COMMANDS:
        assert f"/{name}" in page


def test_about_contains_quoted_version_and_requested_owner_developer():
    page = about_text()
    assert VERSION
    assert f'"{VERSION}"' in page
    assert "@TANJIROKAMADO404" in page
    assert "Owner:" in page
    assert "Developer:" in page


def test_help_home_discloses_owner_group_features_only_in_designated_group():
    owner_group_page = help_home_text(is_group=True, is_owner_private=False, is_owner_group=True)
    public_group_page = help_home_text(is_group=True, is_owner_private=False, is_owner_group=False)
    assert "OWNER-GROUP FEATURES" in owner_group_page
    assert "OWNER-GROUP FEATURES" not in public_group_page
    assert "administrators of this group" in public_group_page


def test_owner_help_notice_is_private_owner_scoped():
    owner_page = help_home_text(is_group=False, is_owner_private=True, is_owner_group=False)
    regular_page = help_home_text(is_group=False, is_owner_private=False, is_owner_group=False)
    assert "OWNER_ID" in owner_page
    assert "OWNER_ID" not in regular_page

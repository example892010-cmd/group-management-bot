"""Human-readable about and help text, kept separate for easy testing."""
from __future__ import annotations

from .command_catalog import GROUP_COMMAND_SECTIONS, OWNER_COMMANDS

VERSION = "1.2.0"
OWNER_HANDLE = "@TANJIROKAMADO404"
DEVELOPER_HANDLE = "@TANJIROKAMADO404"


def about_text() -> str:
    return (
        "🍥 <b>ANIFLIX GROUP MANAGEMENT BOT</b>\n\n"
        f"📦 Version: <code>\"{VERSION}\"</code>\n"
        f"👑 Owner: {OWNER_HANDLE}\n"
        f"🛠 Developer: {DEVELOPER_HANDLE}\n\n"
        "Python • SQLite • Public multi-group management\n"
        "Each group's settings and records are stored separately."
    )


def help_home_text(is_group: bool, is_owner_private: bool, is_owner_group: bool) -> str:
    lines = ["🍥 <b>ANIFLIX GROUP MANAGEMENT BOT</b>", "", "Choose a category below to view its commands."]
    if is_group:
        lines.append("Group-admin commands work only for administrators of this group.")
    elif is_owner_private:
        lines.append("Owner commands are protected by OWNER_ID and work only in this private chat.")
    else:
        lines.append("Add the bot to a group to use the group-management commands.")
    if is_owner_group:
        lines.extend([
            "",
            "🍥 <b>OWNER-GROUP FEATURES</b>",
            "Anime availability, Tamil search and custom TXT auto-replies are active only in this designated group.",
        ])
    return "\n".join(lines)


def help_section_text(section: str) -> str | None:
    entry = GROUP_COMMAND_SECTIONS.get(section)
    if not entry:
        return None
    title, commands = entry
    lines = [f"<b>{title}</b>"]
    lines.extend(f"<code>/{name}</code> — {description}" for name, description in commands)
    return "\n".join(lines)


def owner_help_text() -> str:
    lines = ["👑 <b>BOT OWNER COMMANDS</b>", "<i>Private chat only • OWNER_ID required</i>"]
    lines.extend(f"<code>/{name}</code> — {description}" for name, description in OWNER_COMMANDS)
    return "\n".join(lines)

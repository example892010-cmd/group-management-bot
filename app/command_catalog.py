"""Single source of truth for Telegram command menus and interactive help."""
from __future__ import annotations

PUBLIC_COMMANDS: list[tuple[str, str]] = [
    ("start", "Start the bot"),
    ("help", "Browse commands by category"),
    ("id", "Show your user and group IDs"),
    ("info", "Show user information"),
    ("admins", "List group administrators"),
    ("staff", "List group staff"),
    ("rules", "View this group's rules"),
    ("report", "Report a message or member"),
    ("ping", "Check whether the bot is responding"),
    ("about", "About the bot, owner and version"),
]

GROUP_ADMIN_COMMANDS: list[tuple[str, str]] = [
    ("ban", "Ban a member (reply to their message)"),
    ("unban", "Unban a member by numeric user ID"),
    ("kick", "Remove a member (reply or user ID)"),
    ("mute", "Mute a member (reply to their message)"),
    ("unmute", "Unmute a member (reply to their message)"),
    ("warn", "Warn a member (reply to their message)"),
    ("warnings", "View a member's warning count"),
    ("resetwarns", "Clear a member's warnings"),
    ("purge", "Delete messages from a replied message"),
    ("pin", "Pin a replied message"),
    ("unpin", "Remove a pin"),
    ("promote", "Promote a member (reply or user ID)"),
    ("demote", "Demote an administrator"),
    ("reports", "Review reports saved in this group"),
]

WELCOME_RULES_COMMANDS: list[tuple[str, str]] = [
    ("setwelcome", "Set this group's welcome message"),
    ("welcome", "View or toggle welcome messages"),
    ("resetwelcome", "Reset the welcome message"),
    ("setgoodbye", "Set this group's goodbye message"),
    ("goodbye", "View or toggle goodbye messages"),
    ("resetgoodbye", "Reset the goodbye message"),
    ("setrules", "Set this group's rules"),
    ("filter", "Add a keyword reply: keyword = reply"),
    ("stop", "Remove a keyword filter"),
    ("filters", "List this group's filters"),
    ("save", "Save a note: name then content"),
    ("get", "Get a saved note by name"),
    ("notes", "List saved notes"),
]

PROTECTION_COMMANDS: list[tuple[str, str]] = [
    ("antispam", "Toggle duplicate-message protection"),
    ("antiflood", "Toggle flood protection"),
    ("antilink", "Toggle link protection"),
    ("antiforward", "Toggle forwarded-message protection"),
    ("antibot", "Toggle automatic bot-join removal"),
    ("antiraid", "Toggle join-burst alerts (no CAPTCHA)"),
    ("lock", "Lock a group feature"),
    ("unlock", "Unlock a group feature"),
    ("locks", "View this group's lock settings"),
]

GROUP_SETTINGS_COMMANDS: list[tuple[str, str]] = [
    ("settings", "View this group's settings"),
    ("setdescription", "Change the group description"),
    ("settitle", "Change the group title"),
    ("slowmode", "Set slowmode seconds (0 to disable)"),
]

OWNER_COMMANDS: list[tuple[str, str]] = [
    ("owner", "Open the owner command list"),
    ("admin", "Open the private owner control panel"),
    ("stats", "View real bot statistics"),
    ("groups", "List registered groups"),
    ("users", "View recorded group users"),
    ("broadcast", "Broadcast a replied message to groups"),
    ("blockgroup", "Block a registered group by ID"),
    ("unblockgroup", "Unblock a registered group by ID"),
    ("leave", "Make the bot leave a group by ID"),
    ("restart", "Reconnect the polling session"),
    ("maintenance", "Enable maintenance mode"),
    ("disablemaintenance", "Disable maintenance mode"),
    ("logs", "Get recent application logs"),
    ("clearcache", "Clear in-memory caches"),
    ("backup", "Download a SQLite database backup"),
]

PRIVATE_COMMANDS: list[tuple[str, str]] = [
    ("start", "Start the bot"),
    ("help", "Browse available commands"),
    ("about", "About the bot, owner and version"),
]

GROUP_COMMAND_SECTIONS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "public": ("🌐 PUBLIC COMMANDS", PUBLIC_COMMANDS),
    "admin": ("🛡 GROUP ADMIN COMMANDS", GROUP_ADMIN_COMMANDS),
    "welcome": ("👋 WELCOME, RULES & NOTES", WELCOME_RULES_COMMANDS),
    "protection": ("🔐 GROUP PROTECTION", PROTECTION_COMMANDS),
    "settings": ("⚙️ GROUP SETTINGS", GROUP_SETTINGS_COMMANDS),
}


def group_command_pairs() -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for _, commands in GROUP_COMMAND_SECTIONS.values():
        result.extend(commands)
    return result


def owner_command_pairs() -> list[tuple[str, str]]:
    # The owner-specific scope replaces the default private scope, so include
    # its basic commands as well as the global owner controls.
    return [*PRIVATE_COMMANDS, *OWNER_COMMANDS]

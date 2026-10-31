"""Inline keyboards for the private admin panel."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def keyboard(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=data) for label, data in row]
        for row in rows
    ])


def main_menu() -> InlineKeyboardMarkup:
    return keyboard([
        [("🍥 Anime Manager", "panel:anime"), ("💬 Reply Manager", "panel:replies")],
        [("🗣 Conversation Settings", "panel:conversation"), ("🛡 Group Moderation", "panel:moderation")],
        [("📊 Statistics", "panel:stats"), ("👥 Admin Access", "panel:admins")],
    ])


def anime_menu() -> InlineKeyboardMarkup:
    return keyboard([
        [("➕ Add Available", "anime:add:available"), ("➕ Add Unavailable", "anime:add:unavailable")],
        [("➖ Remove Available", "anime:remove:available"), ("➖ Remove Unavailable", "anime:remove:unavailable")],
        [("📋 View Available", "anime:view:available"), ("📋 View Unavailable", "anime:view:unavailable")],
        [("📤 Upload Available TXT", "anime:upload:available"), ("📤 Upload Unavailable TXT", "anime:upload:unavailable")],
        [("📥 Download Available TXT", "anime:export:available"), ("📥 Download Unavailable TXT", "anime:export:unavailable")],
        [("⬅️ Main Menu", "panel:home")],
    ])


def back_home() -> InlineKeyboardMarkup:
    return keyboard([[("⬅️ Main Menu", "panel:home")]])


def conversation_settings(settings: dict) -> InlineKeyboardMarkup:
    labels = {
        "conversation_enabled": "Conversation replies",
        "gif_reactions": "GIF reactions",
        "sticker_reactions": "Sticker reactions",
        "spelling_correction": "Spelling correction",
        "tanglish_enabled": "Tanglish replies",
        "english_enabled": "English replies",
        "tamil_enabled": "Tamil replies",
        "welcome_enabled": "Welcome messages",
    }
    rows = []
    for key, label in labels.items():
        state = "✅ ON" if settings.get(key, False) else "❌ OFF"
        rows.append([(f"{state} · {label}", f"setting:toggle:{key}")])
    rows.append([("⬅️ Main Menu", "panel:home")])
    return keyboard(rows)


def moderation_settings(settings: dict) -> InlineKeyboardMarkup:
    rows = []
    for key, label in (("anti_link", "Anti-link"), ("anti_flood", "Anti-flood")):
        state = "✅ ON" if settings.get(key, False) else "❌ OFF"
        rows.append([(f"{state} · {label}", f"setting:toggle:{key}")])
    rows.append([("📖 Moderation Commands", "panel:modhelp")])
    rows.append([("⬅️ Main Menu", "panel:home")])
    return keyboard(rows)


def reply_menu() -> InlineKeyboardMarkup:
    return keyboard([
        [("➕ Add Unavailable Reply", "reply:add:unavailable")],
        [("➕ Add Available Reply", "reply:add:available")],
        [("➕ Add Conversation Reply", "reply:add:conversation")],
        [("➕ Add GIF Reply", "reply:add:gif"), ("➕ Add Sticker Reply", "reply:add:sticker")],
        [("📋 View Custom Replies", "reply:view"), ("➖ Remove Reply", "reply:remove")],
        [("⬅️ Main Menu", "panel:home")],
    ])


def admin_menu() -> InlineKeyboardMarkup:
    return keyboard([
        [("➕ Add Admin", "admins:add"), ("➖ Remove Admin", "admins:remove")],
        [("📋 List Admins", "admins:list")],
        [("⬅️ Main Menu", "panel:home")],
    ])

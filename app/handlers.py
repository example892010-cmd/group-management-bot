"""Telegram handlers for anime lookup, conversations, admin panel and moderation."""
from __future__ import annotations

import html
import io
import random
import re
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    ChatPermissions,
    Message,
)

from .catalog import Catalog, parse_title_lines
from .config import Settings
from .conversations import Cooldown
from .keyboards import (
    admin_menu,
    anime_menu,
    back_home,
    conversation_settings,
    main_menu,
    moderation_settings,
    reply_menu,
)
from .moderation import FloodGuard
from .storage import SQLiteStore

router = Router(name="aniflix-group-bot")


class AdminFlow(StatesGroup):
    waiting_titles = State()
    waiting_txt = State()
    waiting_custom_reply = State()
    waiting_conversation_txt = State()
    waiting_remove_reply = State()
    waiting_admin_id = State()
    waiting_remove_admin_id = State()


UNAVAILABLE_REPLIES = [
    "😂 Tamil Dub Illa Bro, Vantha Upload Panrom! 💚 {channel}",
    "🍥 Ithu Innum Tamil La Varala Bro! Vantha Upload Panrom! {channel}",
    "🥲 Tamil Audio Available Illa Bro, Vantha Kandippa Upload Panrom! ❤️ {channel}",
    "😁 Tamil La Illa Bro, Available Aana Namma Channel La Upload Panrom! {channel}",
    "🔥 Tamil Dub Innum Release Aagala Bro! {channel}",
    "🤧 Tamil Audio Innum Varala Nanba, Vantha Upload Panrom! {channel}",
    "💚 Ippo Tamil Dub Available Illa Bro! Vantha Namma Channel La Upload Panrom! {channel}",
    "😭 Tamil La Innum Kedaikala Bro, Vantha Upload Panrom! {channel}",
    "😅 Indha Anime Ku Tamil Audio Illa Bro! Vantha Upload Panrom! {channel}",
    "🍿 Tamil Dub Vandha Namma Channel La Share Panrom Bro! {channel}",
    "💫 Tamil Version Innum Illa Nanba! Available Aana Upload Panrom! {channel}",
    "🫡 Ippo Tamil Audio Illa Bro, Update Vandha Upload Panrom! {channel}",
]
AVAILABLE_REPLIES = [
    "🔥 {title} Tamil La Available Bro! 💚 {channel}",
    "🍥 {title} Ku Tamil Audio Iruku Nanba! {channel}",
    "😁 Good news bro! {title} Tamil Dub Available! {channel}",
    "💚 {title} Tamil Audio La Paakalam Bro! {channel}",
    "🎧 {title} Tamil Version Available Nanba! {channel}",
    "✨ {title} Tamil La Kedaikuthu Bro! {channel}",
]
LINK_PATTERN = re.compile(r"(?:https?://|www\.|t\.me/|telegram\.me/)", re.IGNORECASE)


def muted_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=False, can_send_audios=False, can_send_documents=False,
        can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
        can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False,
        can_add_web_page_previews=False,
    )


async def is_panel_admin(user_id: int, store: SQLiteStore, settings: Settings) -> bool:
    return await store.is_authorized_admin(user_id, settings.owner_ids)


async def is_chat_admin(message: Message, store: SQLiteStore, settings: Settings) -> bool:
    if message.from_user and await is_panel_admin(message.from_user.id, store, settings):
        return True
    if not message.from_user:
        return False
    try:
        member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
        return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
    except Exception:
        return False


def root_panel_text() -> str:
    return "🍥 ANIFLIX GROUP BOT\n\nChoose a section to manage the bot."


@router.message(Command("myid"))
async def my_id_command(message: Message) -> None:
    if message.from_user:
        await message.answer(f"Your Telegram user ID: {message.from_user.id}")


@router.message(Command("start"), StateFilter(None))
async def start_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if message.chat.type == ChatType.PRIVATE:
        if message.from_user and await is_panel_admin(message.from_user.id, store, settings):
            await message.answer("🍥 Welcome to ANIFLIX Group Bot.\n\nUse /admin to open the control panel.")
        else:
            await message.answer("🍥 ANIFLIX Group Bot is active in its groups.")


@router.message(Command("admin"), StateFilter(None))
async def admin_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if message.chat.type != ChatType.PRIVATE:
        await message.answer("Open the bot's private chat and send /admin to access the control panel.")
        return
    if not message.from_user or not await is_panel_admin(message.from_user.id, store, settings):
        await message.answer("⛔ You are not authorized to open this panel.")
        return
    await message.answer(root_panel_text(), reply_markup=main_menu())


@router.message(Command("cancel"))
async def cancel_admin_action(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("✅ Action cancelled.")


async def _authorized_callback(callback: CallbackQuery, store: SQLiteStore, settings: Settings) -> bool:
    if callback.from_user and await is_panel_admin(callback.from_user.id, store, settings):
        return True
    await callback.answer("You are not authorized.", show_alert=True)
    return False


@router.callback_query(F.data.startswith("panel:"))
async def panel_navigation(callback: CallbackQuery, state: FSMContext, store: SQLiteStore, settings: Settings) -> None:
    if not await _authorized_callback(callback, store, settings):
        return
    await state.clear()
    action = callback.data.split(":", 1)[1]
    if action == "home":
        await callback.message.edit_text(root_panel_text(), reply_markup=main_menu())
    elif action == "anime":
        await callback.message.edit_text("🍥 **Anime Manager**\nChoose an action.", reply_markup=anime_menu(), parse_mode="Markdown")
    elif action == "replies":
        await callback.message.edit_text("💬 **Reply Manager**\nAdd custom reply lines for anime and conversations.", reply_markup=reply_menu(), parse_mode="Markdown")
    elif action == "conversation":
        current = await store.get_settings()
        await callback.message.edit_text("🗣 Conversation Settings\nToggle the features below.", reply_markup=conversation_settings(current))
    elif action == "moderation":
        current = await store.get_settings()
        await callback.message.edit_text("🛡 Group Moderation\nToggle protections. Commands are listed below.", reply_markup=moderation_settings(current))
    elif action == "stats":
        stats = await store.get_stats()
        catalog = await store.get_catalog()
        text = (
            "📊 ANIFLIX BOT STATISTICS\n\n"
            f"✅ Available anime: {len(catalog.available)}\n"
            f"❌ Unavailable anime: {len(catalog.unavailable)}\n"
            f"💬 Messages checked: {stats.get('messages_seen', 0)}\n"
            f"🗣 Conversation replies: {stats.get('conversation_replies', 0)}\n"
            f"🍥 Anime matches: {stats.get('anime_matches', 0)}\n"
            f"✍️ Spelling corrections: {stats.get('corrections', 0)}\n"
            f"🎞 Media reactions: {stats.get('media_reactions', 0)}"
        )
        await callback.message.edit_text(text, reply_markup=back_home())
    elif action == "admins":
        await callback.message.edit_text("👥 Admin Access\nOnly the owner can add or remove panel admins.", reply_markup=admin_menu())
    elif action == "modhelp":
        text = (
            "🛡 MODERATION COMMANDS\n\n"
            "/warn — warn a member (reply to their message)\n"
            "/mute — mute a member (reply to their message)\n"
            "/unmute — unmute a member (reply to their message)\n"
            "/ban — ban a member (reply to their message)\n"
            "/unban USER_ID — unban by numeric Telegram ID\n\n"
            "The bot must be an administrator with the required permissions."
        )
        await callback.message.edit_text(text, reply_markup=moderation_settings(await store.get_settings()))
    await callback.answer()


@router.callback_query(F.data.startswith("anime:"))
async def anime_actions(callback: CallbackQuery, state: FSMContext, store: SQLiteStore, settings: Settings) -> None:
    if not await _authorized_callback(callback, store, settings):
        return
    _, action, status = callback.data.split(":")
    catalog = await store.get_catalog()
    if action in {"add", "remove"}:
        await state.set_state(AdminFlow.waiting_titles)
        await state.update_data(action=action, status=status)
        verb = "add" if action == "add" else "remove"
        await callback.message.answer(
            f"Send the anime titles to {verb}, one title per line, for the {status.upper()} list.\n\n"
            "Example:\nNaruto\nJujutsu Kaisen\nGintama\n\nSend /cancel to stop."
        )
    elif action == "upload":
        await state.set_state(AdminFlow.waiting_txt)
        await state.update_data(status=status)
        await callback.message.answer(f"Send the replacement `{status}_anime.txt` as a TXT document. Existing titles in that list will be replaced. Use /cancel to stop.", parse_mode="Markdown")
    elif action == "view":
        content = catalog.export_text(status)
        if not content:
            await callback.message.answer(f"The {status} anime list is empty.")
        else:
            await callback.message.answer_document(BufferedInputFile(content.encode("utf-8"), filename=f"{status}_anime.txt"), caption=f"📋 {status.title()} anime · {len(catalog.titles(status))} titles")
    elif action == "export":
        content = catalog.export_text(status) or "# No anime titles saved yet. Add one title per line.\n"
        await callback.message.answer_document(
            BufferedInputFile(content.encode("utf-8"), filename=f"{status}_anime.txt"),
            caption=f"📥 {status.title()} anime · {len(catalog.titles(status))} titles",
        )
    await callback.answer()


@router.message(AdminFlow.waiting_titles, F.chat.type == ChatType.PRIVATE)
async def receive_title_lines(message: Message, state: FSMContext, store: SQLiteStore, settings: Settings) -> None:
    if not message.from_user or not await is_panel_admin(message.from_user.id, store, settings):
        await state.clear()
        return
    if not message.text:
        await message.answer("Please send plain text, with one anime title per line.")
        return
    data = await state.get_data()
    action = data.get("action")
    status = data.get("status")
    incoming = parse_title_lines(message.text)
    catalog = await store.get_catalog()
    if not incoming:
        await message.answer("No valid anime titles were found. Send one title per line.")
        return
    if action == "add":
        report = catalog.add(status, incoming)
        await store.save_catalog(catalog)
        reply = (
            f"✅ Added: {len(report['added'])}\n"
            f"♻️ Already in this list: {len(report['duplicates'])}\n"
            f"⚠️ Already in the other list: {len(report['conflicts'])}\n"
            f"📁 Total in {status}: {len(catalog.titles(status))}"
        )
        if report["conflicts"]:
            reply += "\n\nAlready assigned to the other TXT file:\n" + "\n".join(report["conflicts"][:20])
    else:
        report = catalog.remove(status, incoming)
        await store.save_catalog(catalog)
        reply = (
            f"✅ Removed: {len(report['removed'])}\n"
            f"❓ Not found: {len(report['not_found'])}\n"
            f"📁 Total in {status}: {len(catalog.titles(status))}"
        )
    await state.clear()
    await message.answer(reply)


@router.message(AdminFlow.waiting_txt, F.chat.type == ChatType.PRIVATE, F.document)
async def receive_txt_file(message: Message, state: FSMContext, store: SQLiteStore, settings: Settings) -> None:
    if not message.from_user or not await is_panel_admin(message.from_user.id, store, settings):
        await state.clear()
        return
    document = message.document
    if not document or not (document.file_name or "").lower().endswith(".txt"):
        await message.answer("Please upload a .txt document. The current list has not been changed.")
        return
    if document.file_size and document.file_size > 2_000_000:
        await message.answer("TXT file is too large. Please keep it under 2 MB.")
        return
    buffer = io.BytesIO()
    await message.bot.download(document, destination=buffer)
    try:
        content = buffer.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError:
        await message.answer("The file must be UTF-8 encoded. The current list has not been changed.")
        return
    incoming = parse_title_lines(content)
    if not incoming:
        await message.answer("The TXT file has no valid titles. The current list has not been changed.")
        return
    data = await state.get_data()
    status = data.get("status")
    catalog = await store.get_catalog()
    report = catalog.replace(status, incoming)
    await store.save_catalog(catalog)
    await state.clear()
    await message.answer(
        f"✅ Replaced {status}_anime.txt\n"
        f"📥 Imported: {len(report['replaced'])}\n"
        f"⚠️ Skipped because they are in the other list: {len(report['conflicts'])}\n"
        f"📁 Total in {status}: {len(catalog.titles(status))}"
    )


@router.message(AdminFlow.waiting_txt, F.chat.type == ChatType.PRIVATE)
async def waiting_for_txt_document(message: Message) -> None:
    await message.answer("Please send the TXT file as a document attachment, or use /cancel.")


@router.callback_query(F.data.startswith("reply:add:"))
async def add_reply_start(callback: CallbackQuery, state: FSMContext, store: SQLiteStore, settings: Settings) -> None:
    if not await _authorized_callback(callback, store, settings):
        return
    category = callback.data.split(":", 2)[2]
    await state.set_state(AdminFlow.waiting_custom_reply)
    await state.update_data(reply_category=category)
    if category == "conversation":
        await callback.message.answer(
            "Send trigger = reply lines. Example:\nhi = Hey bro! 👋\nhow are you = I'm good!\n"
            "These are added to your saved conversation library. Use /cancel to stop."
        )
    else:
        await callback.message.answer(f"Send one or more {category} reply messages, one per line. Use /cancel to stop.")
    await callback.answer()


@router.message(AdminFlow.waiting_custom_reply, F.chat.type == ChatType.PRIVATE)
async def receive_custom_replies(message: Message, state: FSMContext, store: SQLiteStore, settings: Settings) -> None:
    if not message.from_user or not await is_panel_admin(message.from_user.id, store, settings):
        await state.clear()
        return
    if not message.text:
        await message.answer("Please send the reply messages as text, one per line.")
        return
    data = await state.get_data()
    category = data.get("reply_category", "conversation")
    if category == "conversation":
        report = await store.import_conversations(message.text)
        await state.clear()
        await message.answer(
            f"✅ Saved {report['added']:,} conversation entries.\n"
            f"♻️ Duplicates skipped: {report['duplicates']:,}\n"
            f"⚠️ Invalid lines skipped: {report['invalid']:,}\n"
            f"💬 Total saved: {report['total']:,}"
        )
        return
    lines = [line.strip() for line in message.text.splitlines() if line.strip()]
    added = 0
    for line in lines:
        if await store.add_custom_reply(category, line):
            added += 1
    await state.clear()
    await message.answer(f"✅ Saved {added} new {category} replies. Existing duplicates were skipped.")


@router.callback_query(F.data == "reply:remove")
async def remove_reply_start(callback: CallbackQuery, state: FSMContext, store: SQLiteStore, settings: Settings) -> None:
    if not await _authorized_callback(callback, store, settings):
        return
    await state.set_state(AdminFlow.waiting_remove_reply)
    await callback.message.answer("Send the exact custom reply as: category | full reply text\nCategories: unavailable, available, conversation, gif, sticker")
    await callback.answer()


@router.message(AdminFlow.waiting_remove_reply, F.chat.type == ChatType.PRIVATE)
async def receive_remove_reply(message: Message, state: FSMContext, store: SQLiteStore, settings: Settings) -> None:
    if not message.from_user or not await is_panel_admin(message.from_user.id, store, settings):
        await state.clear()
        return
    category, separator, reply_text = (message.text or "").partition("|")
    category = category.strip().lower()
    if not separator or category not in {"unavailable", "available", "conversation", "gif", "sticker"} or not reply_text.strip():
        await message.answer("Use: category | full reply text. Example: gif | Semma reaction bro 😂")
        return
    removed = await store.remove_custom_reply(category, reply_text.strip())
    await state.clear()
    await message.answer("✅ Custom reply removed." if removed else "No exact matching custom reply was found.")


@router.callback_query(F.data == "reply:view")
async def view_replies(callback: CallbackQuery, store: SQLiteStore, settings: Settings) -> None:
    if not await _authorized_callback(callback, store, settings):
        return
    sections = []
    for category in ("unavailable", "available", "conversation", "gif", "sticker"):
        items = await store.get_custom_replies(category)
        sections.append(f"{category.title()} ({len(items)}):\n" + ("\n".join(f"• {item}" for item in items) or "None"))
    content = "💬 CUSTOM REPLIES\n\n" + "\n\n".join(sections)
    if len(content) <= 3900:
        await callback.message.answer(content)
    else:
        await callback.message.answer_document(BufferedInputFile(content.encode("utf-8"), filename="custom_replies.txt"))
    await callback.answer()


@router.callback_query(F.data.startswith("setting:toggle:"))
async def toggle_setting(callback: CallbackQuery, store: SQLiteStore, settings: Settings) -> None:
    if not await _authorized_callback(callback, store, settings):
        return
    key = callback.data.split(":", 2)[2]
    current = await store.get_settings()
    await store.set_setting(key, not bool(current.get(key, False)))
    updated = await store.get_settings()
    if key in {"anti_link", "anti_flood"}:
        await callback.message.edit_reply_markup(reply_markup=moderation_settings(updated))
    else:
        await callback.message.edit_reply_markup(reply_markup=conversation_settings(updated))
    await callback.answer(f"{key.replace('_', ' ').title()}: {'ON' if updated[key] else 'OFF'}")


@router.callback_query(F.data.startswith("admins:"))
async def admin_access_actions(callback: CallbackQuery, state: FSMContext, store: SQLiteStore, settings: Settings) -> None:
    if not await _authorized_callback(callback, store, settings):
        return
    if callback.from_user.id not in settings.owner_ids:
        await callback.answer("Only the owner can change admin access.", show_alert=True)
        return
    action = callback.data.split(":", 1)[1]
    if action == "add":
        await state.set_state(AdminFlow.waiting_admin_id)
        await callback.message.answer("Send the numeric Telegram user ID to authorize as a panel admin.")
    elif action == "remove":
        await state.set_state(AdminFlow.waiting_remove_admin_id)
        await callback.message.answer("Send the numeric Telegram user ID to remove from panel admins.")
    elif action == "list":
        ids = await store.list_admins()
        await callback.message.answer("👥 Authorized panel admins:\n" + ("\n".join(map(str, ids)) if ids else "No additional admins."))
    await callback.answer()


@router.message(AdminFlow.waiting_admin_id, F.chat.type == ChatType.PRIVATE)
async def receive_admin_id(message: Message, state: FSMContext, store: SQLiteStore, settings: Settings) -> None:
    if not message.from_user or message.from_user.id not in settings.owner_ids:
        await state.clear()
        return
    try:
        user_id = int((message.text or "").strip())
        if user_id <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Send a valid numeric Telegram user ID.")
        return
    await store.add_admin(user_id)
    await state.clear()
    await message.answer(f"✅ Added {user_id} as a panel admin.")


@router.message(AdminFlow.waiting_remove_admin_id, F.chat.type == ChatType.PRIVATE)
async def receive_remove_admin_id(message: Message, state: FSMContext, store: SQLiteStore, settings: Settings) -> None:
    if not message.from_user or message.from_user.id not in settings.owner_ids:
        await state.clear()
        return
    try:
        user_id = int((message.text or "").strip())
        if user_id <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Send a valid numeric Telegram user ID.")
        return
    await store.remove_admin(user_id)
    await state.clear()
    await message.answer(f"✅ Removed {user_id} from panel admins.")


async def _get_reply_custom(store: SQLiteStore, category: str) -> list[str]:
    return await store.get_custom_replies(category)


def _is_group(message: Message) -> bool:
    return message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}


async def _handle_group_moderation(message: Message, store: SQLiteStore, settings: Settings, flood: FloodGuard) -> bool:
    if not message.from_user:
        return False
    current = await store.get_settings()
    if current.get("anti_link") and message.text and LINK_PATTERN.search(message.text):
        if not await is_chat_admin(message, store, settings):
            try:
                await message.delete()
                await message.answer(f"🚫 Links are disabled in this group, {message.from_user.mention_html()}.", parse_mode="HTML")
            except Exception:
                pass
            return True
    if current.get("anti_flood") and not await is_chat_admin(message, store, settings):
        if flood.is_flooding(message.chat.id, message.from_user.id):
            try:
                await message.bot.restrict_chat_member(
                    chat_id=message.chat.id,
                    user_id=message.from_user.id,
                    permissions=muted_permissions(),
                    until_date=datetime.now(timezone.utc) + timedelta(seconds=60),
                )
                await message.answer("🚦 Slow down a little, bro! You are temporarily muted for flooding.")
            except Exception:
                pass
            return True
    return False


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "🍥 ANIFLIX GROUP BOT\n\n"
        "I can check saved Tamil-anime availability, suggest corrected anime titles, chat casually, and react to GIFs/stickers.\n\n"
        "Admin moderation commands (reply to a member): /warn, /mute, /unmute, /ban.\n"
        "Panel owners: send /admin in my private chat."
    )


@router.message(Command("warn"))
async def warn_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not _is_group(message) or not await is_chat_admin(message, store, settings):
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target or target.is_bot:
        await message.reply("Reply to a member's message with /warn.")
        return
    count = await store.add_warning(message.chat.id, target.id)
    if count >= 3:
        try:
            await message.bot.restrict_chat_member(
                chat_id=message.chat.id, user_id=target.id,
                permissions=muted_permissions(),
                until_date=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
            await store.clear_warnings(message.chat.id, target.id)
            await message.answer(f"🔇 {target.mention_html()} reached 3 warnings and was muted for 10 minutes.", parse_mode="HTML")
        except Exception:
            await message.answer("⚠️ Could not apply the automatic mute. Check the bot's admin permissions.")
    else:
        await message.answer(f"⚠️ Warning {count}/3 for {target.mention_html()}.", parse_mode="HTML")


async def _moderation_target(message: Message) -> tuple[int | None, str | None]:
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
        return target.id, target.mention_html()
    return None, None


@router.message(Command("mute"))
async def mute_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not _is_group(message) or not await is_chat_admin(message, store, settings):
        return
    user_id, mention = await _moderation_target(message)
    if not user_id:
        await message.reply("Reply to a member's message with /mute.")
        return
    try:
        await message.bot.restrict_chat_member(
            chat_id=message.chat.id, user_id=user_id,
            permissions=muted_permissions(),
            until_date=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        await message.answer(f"🔇 {mention} has been muted for 30 minutes.", parse_mode="HTML")
    except Exception:
        await message.answer("⚠️ I could not mute that member. Check my admin permissions.")


@router.message(Command("unmute"))
async def unmute_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not _is_group(message) or not await is_chat_admin(message, store, settings):
        return
    user_id, mention = await _moderation_target(message)
    if not user_id:
        await message.reply("Reply to a member's message with /unmute.")
        return
    try:
        await message.bot.restrict_chat_member(
            chat_id=message.chat.id, user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True, can_send_audios=True, can_send_documents=True,
                can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        await message.answer(f"🔊 {mention} has been unmuted.", parse_mode="HTML")
    except Exception:
        await message.answer("⚠️ I could not unmute that member. Check my admin permissions.")


@router.message(Command("ban"))
async def ban_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not _is_group(message) or not await is_chat_admin(message, store, settings):
        return
    user_id, mention = await _moderation_target(message)
    if not user_id:
        await message.reply("Reply to a member's message with /ban.")
        return
    try:
        await message.bot.ban_chat_member(message.chat.id, user_id)
        await message.answer(f"⛔ {mention} has been banned.", parse_mode="HTML")
    except Exception:
        await message.answer("⚠️ I could not ban that member. Check my admin permissions.")


@router.message(Command("unban"))
async def unban_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not _is_group(message) or not await is_chat_admin(message, store, settings):
        return
    args = (message.text or "").split(maxsplit=1)
    if len(args) != 2 or not args[1].isdigit():
        await message.reply("Use /unban USER_ID with the member's numeric Telegram ID.")
        return
    try:
        await message.bot.unban_chat_member(message.chat.id, int(args[1]), only_if_banned=True)
        await message.answer("✅ Member unbanned.")
    except Exception:
        await message.answer("⚠️ I could not unban that user. Check the ID and my admin permissions.")


@router.message(F.new_chat_members)
async def welcome_new_members(message: Message, store: SQLiteStore) -> None:
    if not _is_group(message):
        return
    current = await store.get_settings()
    if not current.get("welcome_enabled", True):
        return
    for user in message.new_chat_members:
        if user.is_bot:
            continue
        await message.answer(f"🍥 Vanakkam {user.mention_html()}! Welcome to ANIFLIX group! ❤️", parse_mode="HTML")


async def _process_group_text(
    message: Message,
    store: SQLiteStore,
    settings: Settings,
    cooldown: Cooldown,
    flood: FloodGuard,
    catalog: Catalog,
) -> None:
    if not _is_group(message) or not message.from_user or message.from_user.is_bot or not message.text:
        return
    if message.text.startswith("/"):
        return
    if await _handle_group_moderation(message, store, settings, flood):
        return
    await store.increment_stat("messages_seen")
    user_id = message.from_user.id
    chat_id = message.chat.id

    match = catalog.find_mentioned(message.text)
    if match:
        title, status = match
        if not cooldown.allow(chat_id, user_id, time.monotonic()):
            return
        if status == "unavailable":
            custom = await _get_reply_custom(store, "unavailable")
            pool = UNAVAILABLE_REPLIES + custom
            response = random.choice(pool).replace("{channel}", settings.bot_channel_username).replace("{title}", title)
        else:
            custom = await _get_reply_custom(store, "available")
            pool = AVAILABLE_REPLIES + custom
            response = random.choice(pool).replace("{channel}", settings.bot_channel_username).replace("{title}", title)
        if settings.bot_channel_username and settings.bot_channel_username.casefold() not in response.casefold():
            response = f"{response} {settings.bot_channel_username}"
        await message.reply(response)
        await store.increment_stat("anime_matches")
        return

    current = await store.get_settings()
    if current.get("spelling_correction", True):
        suggestion = catalog.suggest_correction(message.text)
        if suggestion:
            if cooldown.allow(chat_id, user_id, time.monotonic()):
                safe_title = html.escape(suggestion)
                await message.reply(f"😁 Bro, you mean <b>{safe_title}</b>?\n\n🍥 {safe_title} Here 👇", parse_mode="HTML")
                await store.increment_stat("corrections")
            return

    if not current.get("conversation_enabled", True):
        return
    # Only user-added trigger/reply pairs in SQLite can produce conversation replies.
    # No hardcoded intent engine or fallback response is used.
    response = await store.get_conversation_reply(message.text)
    if response and cooldown.allow(chat_id, user_id, time.monotonic()):
        await message.reply(response)
        await store.increment_stat("conversation_replies")



@router.callback_query(F.data.startswith("conversation:"))
async def conversation_library_actions(
    callback: CallbackQuery, state: FSMContext, store: SQLiteStore, settings: Settings
) -> None:
    if not await _authorized_callback(callback, store, settings):
        return
    action = callback.data.split(":", 1)[1]
    if action == "upload":
        await state.set_state(AdminFlow.waiting_conversation_txt)
        await callback.message.answer(
            "📤 Send your conversation library as a UTF-8 .txt document.\n\n"
            "Format: trigger = reply\n"
            "Example: hi = Hey bro! 👋\n\n"
            "Imports are added to existing entries; duplicates are skipped, never replaced. "
            "Use /cancel to stop."
        )
    elif action == "count":
        total = await store.count_conversations()
        await callback.message.answer(f"💬 Saved conversation entries: {total:,}")
    elif action == "export":
        total = await store.count_conversations()
        if not total:
            await callback.message.answer("No conversation entries have been saved yet.")
        else:
            content = await store.export_conversations()
            await callback.message.answer_document(
                BufferedInputFile(content.encode("utf-8"), filename="aniflix_conversations.txt"),
                caption=f"📥 Exported {total:,} saved conversation entries.",
            )
    await callback.answer()


@router.message(AdminFlow.waiting_conversation_txt, F.chat.type == ChatType.PRIVATE, F.document)
async def receive_conversation_library(
    message: Message, state: FSMContext, store: SQLiteStore, settings: Settings
) -> None:
    if not message.from_user or not await is_panel_admin(message.from_user.id, store, settings):
        await state.clear()
        return
    document = message.document
    if not document or not (document.file_name or "").lower().endswith(".txt"):
        await message.answer("Please upload a .txt document. Nothing has been imported.")
        return
    # Telegram Bot API getFile downloads are limited to 20 MB for standard bots.
    if document.file_size and document.file_size > 20 * 1024 * 1024:
        await message.answer("This TXT is over Telegram's 20 MB bot-download limit. Split it into smaller TXT files.")
        return
    buffer = io.BytesIO()
    try:
        await message.bot.download(document, destination=buffer)
        content = buffer.getvalue().decode("utf-8-sig")
    except Exception:
        await message.answer("I couldn't read that file. Please send a UTF-8 encoded TXT file.")
        return
    if not content.strip():
        await message.answer("The TXT file is empty. Nothing has been imported.")
        return
    report = await store.import_conversations(content)
    await state.clear()
    await message.answer(
        "✅ Conversation TXT import finished\n\n"
        f"📄 Valid entries: {report['valid']:,}\n"
        f"➕ Newly saved: {report['added']:,}\n"
        f"♻️ Existing duplicates: {report['duplicates']:,}\n"
        f"⚠️ Invalid lines skipped: {report['invalid']:,}\n"
        f"💬 Total saved: {report['total']:,}\n\n"
        "Only these saved trigger/reply entries can generate conversation replies."
    )


@router.message(AdminFlow.waiting_conversation_txt, F.chat.type == ChatType.PRIVATE)
async def waiting_for_conversation_txt(message: Message) -> None:
    await message.answer("Please send the conversation library as a .txt document, or use /cancel.")


@router.message(Command("reloadreplies"))
async def reload_replies_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not message.from_user or not await is_panel_admin(message.from_user.id, store, settings):
        return
    total = await store.count_conversations()
    await message.answer(f"✅ Conversation library ready. {total:,} trigger/reply entries are saved in SQLite.")


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), F.text)
async def group_text_handler(
    message: Message,
    store: SQLiteStore,
    settings: Settings,
    cooldown: Cooldown,
    flood: FloodGuard,
) -> None:
    await _process_group_text(message, store, settings, cooldown, flood, store.catalog)


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), F.animation)
async def group_gif_handler(
    message: Message, store: SQLiteStore, settings: Settings,
    cooldown: Cooldown, flood: FloodGuard,
) -> None:
    if not message.from_user or message.from_user.is_bot:
        return
    if await _handle_group_moderation(message, store, settings, flood):
        return
    current = await store.get_settings()
    if not current.get("conversation_enabled", True) or not current.get("gif_reactions", True):
        return
    if not cooldown.allow(message.chat.id, message.from_user.id, time.monotonic()):
        return
    custom = await store.get_custom_replies("gif")
    if not custom:
        return
    await message.reply(random.choice(custom))
    await store.increment_stat("media_reactions")


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), F.sticker)
async def group_sticker_handler(
    message: Message, store: SQLiteStore, settings: Settings,
    cooldown: Cooldown, flood: FloodGuard,
) -> None:
    if not message.from_user or message.from_user.is_bot:
        return
    if await _handle_group_moderation(message, store, settings, flood):
        return
    current = await store.get_settings()
    if not current.get("conversation_enabled", True) or not current.get("sticker_reactions", True):
        return
    if not cooldown.allow(message.chat.id, message.from_user.id, time.monotonic()):
        return
    custom = await store.get_custom_replies("sticker")
    if not custom:
        return
    await message.reply(random.choice(custom))
    await store.increment_stat("media_reactions")

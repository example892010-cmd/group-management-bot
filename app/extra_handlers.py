"""Additional public group and bot-owner command handlers.

All group data access is keyed by chat_id. Global controls verify OWNER_ID and
are only accepted in the owner's private chat.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, ChatPermissions, Message

from .config import Settings
from .storage import SQLiteStore

log = logging.getLogger(__name__)
router = Router(name="aniflix-extra-commands")
GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}


def in_group(message: Message) -> bool:
    return message.chat.type in GROUP_TYPES


async def group_admin(message: Message, settings: Settings) -> bool:
    if not message.from_user:
        return False
    if message.from_user.id in settings.owner_ids:
        return True
    try:
        member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
        return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
    except Exception as exc:
        log.warning("Could not verify group admin status in %s: %s", message.chat.id, exc)
        return False


async def require_group_admin(message: Message, settings: Settings) -> bool:
    if not in_group(message):
        await message.reply("This command can only be used in a group.")
        return False
    if not await group_admin(message, settings):
        await message.reply("⛔ Only administrators of this group can use that command.")
        return False
    return True


def _args(message: Message) -> str:
    return (message.text or "").partition(" ")[2].strip()


async def target_user_id(message: Message) -> int | None:
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    raw = _args(message).split(maxsplit=1)[0] if _args(message) else ""
    return int(raw) if raw.isdigit() else None


async def owner_private(message: Message, settings: Settings) -> bool:
    allowed = bool(message.from_user and message.from_user.id in settings.owner_ids and message.chat.type == ChatType.PRIVATE)
    if not allowed:
        await message.reply("⛔ This command is restricted to the bot owner in private chat.")
    return allowed


@router.message(Command("owner"))
async def owner_command(message: Message, settings: Settings) -> None:
    if await owner_private(message, settings):
        await message.answer("🍥 ANIFLIX OWNER CONSOLE\n\n/owner · /stats · /groups · /users\n/broadcast · /blockgroup · /unblockgroup · /leave\n/restart · /maintenance · /disablemaintenance\n/logs · /clearcache · /backup")


@router.message(Command("users"))
async def users_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not await owner_private(message, settings):
        return
    total, users = await store.get_user_stats()
    lines = [f"{i}. {u['full_name'] or 'Unknown'} | {u['user_id']}" + (f" | @{u['username']}" if u['username'] else "") for i, u in enumerate(users[:50], 1)]
    await message.answer(f"👥 Unique users recorded: {total:,}\nShowing latest {len(lines)} of up to 50:\n" + ("\n".join(lines) if lines else "No group users recorded yet."))


@router.message(Command("blockgroup"))
async def block_group_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not await owner_private(message, settings):
        return
    raw = _args(message)
    if not raw.lstrip("-").isdigit():
        await message.reply("Usage: /blockgroup GROUP_ID")
        return
    chat_id = int(raw)
    changed = await store.set_group_blocked(chat_id, True)
    await message.answer("✅ Group blocked. The bot will ignore its updates." if changed else "No active registered group with that ID was found.")


@router.message(Command("unblockgroup"))
async def unblock_group_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not await owner_private(message, settings):
        return
    raw = _args(message)
    if not raw.lstrip("-").isdigit():
        await message.reply("Usage: /unblockgroup GROUP_ID")
        return
    changed = await store.set_group_blocked(int(raw), False)
    await message.answer("✅ Group unblocked." if changed else "No active registered group with that ID was found.")


@router.message(Command("leave"))
async def leave_group_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not await owner_private(message, settings):
        return
    raw = _args(message)
    if not raw.lstrip("-").isdigit():
        await message.reply("Usage: /leave GROUP_ID")
        return
    chat_id = int(raw)
    try:
        await message.bot.leave_chat(chat_id)
        await store.deactivate_group(chat_id)
        await message.answer(f"✅ Left group {chat_id} and marked it inactive.")
    except Exception as exc:
        log.warning("Owner leave command failed for %s: %s", chat_id, exc)
        await message.answer("⚠️ Could not leave that group. Check its ID and the bot's membership.")


@router.message(Command("maintenance"))
async def maintenance_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not await owner_private(message, settings):
        return
    await store.set_setting("maintenance_mode", True)
    await message.answer("🛠 Maintenance mode enabled. Non-owner group messages are paused.")


@router.message(Command("disablemaintenance"))
async def disable_maintenance_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not await owner_private(message, settings):
        return
    await store.set_setting("maintenance_mode", False)
    await message.answer("✅ Maintenance mode disabled. Group operation resumed.")


@router.message(Command("restart"))
async def restart_command(message: Message, settings: Settings, runtime_control=None) -> None:
    if not await owner_private(message, settings):
        return
    if runtime_control is None:
        await message.answer("⚠️ Restart control is unavailable in this runtime.")
        return
    runtime_control.request_restart()
    await message.answer("♻️ Restart requested. The Telegram polling session will reconnect; the database and health endpoint remain online.")


@router.message(Command("clearcache"))
async def clear_cache_command(
    message: Message, settings: Settings, flood=None, raid_guard=None,
    cooldown=None, slow_guard=None, duplicate_guard=None, protection_middleware=None,
) -> None:
    if not await owner_private(message, settings):
        return
    for obj, field_names in ((flood, ("recent",)), (raid_guard, ("recent", "alerted")), (cooldown, ("_last",)), (slow_guard, ("last_seen",)), (duplicate_guard, ("recent",))):
        if obj is None:
            continue
        for field in field_names:
            cache = getattr(obj, field, None)
            if hasattr(cache, "clear"):
                cache.clear()
    if protection_middleware is not None:
        cache = getattr(protection_middleware, "admin_cache", None)
        if hasattr(cache, "clear"):
            cache.clear()
    await message.answer("🧹 In-memory moderation, admin and rate-limit caches cleared. SQLite records were not changed.")


@router.message(Command("backup"))
async def backup_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not await owner_private(message, settings):
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = Path(settings.data_dir) / "backups" / f"aniflix_sqlite_backup_{stamp}.db"
    try:
        path = await store.create_backup(backup_path)
        await message.answer_document(BufferedInputFile(path.read_bytes(), filename=path.name), caption="✅ SQLite database backup. Existing data was not modified.")
    except Exception as exc:
        log.exception("Database backup failed")
        await message.answer(f"⚠️ Backup failed: {type(exc).__name__}")


@router.message(Command("logs"))
async def logs_command(message: Message, settings: Settings) -> None:
    if not await owner_private(message, settings):
        return
    default_log_path = Path(settings.data_dir) / "logs" / "aniflix.log"
    log_path = Path(os.getenv("LOG_FILE", str(default_log_path)))
    try:
        if not log_path.is_file() or log_path.stat().st_size == 0:
            await message.answer("No log file is available yet. Check the Render service logs.")
            return
        data = log_path.read_bytes()[-(1024 * 1024):]
        await message.answer_document(BufferedInputFile(data, filename="aniflix_recent_logs.txt"), caption="Latest application log output (up to 1 MB).")
    except OSError as exc:
        log.warning("Could not read application log: %s", exc)
        await message.answer("⚠️ Could not read the local log file. Render dashboard logs remain available.")


@router.message(Command("start"))
async def public_start_command(message: Message, settings: Settings) -> None:
    if in_group(message):
        await message.answer("🍥 ANIFLIX GROUP MANAGEMENT BOT is active here. Use /help to view commands.")
    elif message.from_user and message.from_user.id in settings.owner_ids:
        await message.answer("🍥 ANIFLIX GROUP MANAGEMENT BOT\nUse /owner for global owner controls.")
    else:
        await message.answer("🍥 ANIFLIX GROUP MANAGEMENT BOT\nAdd me to a group and promote me with the permissions you want me to manage.")


@router.message(F.left_chat_member)
async def goodbye_member(message: Message, store: SQLiteStore) -> None:
    if not in_group(message) or not message.left_chat_member or message.left_chat_member.is_bot:
        return
    cfg = await store.get_group_settings(message.chat.id)
    if not cfg.get("goodbye_enabled", False):
        return
    member = message.left_chat_member
    template = cfg.get("goodbye_text", "Goodbye {mention}!")
    mention = member.mention_html()
    safe_template = __import__("html").escape(template)
    rendered = safe_template.replace("{mention}", mention).replace("{first}", __import__("html").escape(member.first_name))
    rendered = rendered.replace("{username}", __import__("html").escape(member.username or ""))
    rendered = rendered.replace("{chat}", __import__("html").escape(message.chat.title or "this group"))
    await message.answer(rendered, parse_mode="HTML")


# ---- Public member commands and group-admin commands ----

@router.message(Command("staff"))
async def staff_command(message: Message) -> None:
    if not in_group(message):
        return
    try:
        admins = await message.bot.get_chat_administrators(message.chat.id)
        staff = [a for a in admins if not a.user.is_bot]
        lines = [f"• {a.user.full_name}" + (f" (@{a.user.username})" if a.user.username else "") for a in staff]
        await message.answer("👮 Group staff\n" + ("\n".join(lines) if lines else "No staff found."))
    except Exception:
        await message.answer("⚠️ I couldn't retrieve the group staff list.")


@router.message(Command("report"))
async def report_command(message: Message, store: SQLiteStore) -> None:
    if not in_group(message) or not message.from_user:
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if target and target.id == message.from_user.id:
        await message.reply("You cannot report yourself.")
        return
    reason = _args(message)
    report_id = await store.add_report(message.chat.id, message.from_user.id, target.id if target else None, reason)
    if target:
        label = target.mention_html()
        await message.answer(f"🚩 Report #{report_id} saved for {label}. Group admins can review it.", parse_mode="HTML")
    else:
        await message.answer(f"🚩 Report #{report_id} saved. Reply to a member's message with /report to report a specific member.")


@router.message(Command("reports"))
async def reports_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    reports = await store.list_reports(message.chat.id, 10)
    if not reports:
        await message.answer("✅ No reports have been saved for this group.")
        return
    lines = [f"#{item['report_id']} · reporter {item['reporter_id']} · target {item['target_id'] or 'not specified'} · {item['reason'] or 'No reason'}" for item in reports]
    await message.answer("🚩 Latest group reports\n" + "\n".join(lines))


@router.message(Command("kick"))
async def kick_command(message: Message, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    user_id = await target_user_id(message)
    if not user_id:
        await message.reply("Reply to a member's message or use /kick USER_ID.")
        return
    try:
        target = await message.bot.get_chat_member(message.chat.id, user_id)
        if target.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
            await message.reply("I won't kick a group administrator.")
            return
        await message.bot.ban_chat_member(message.chat.id, user_id)
        await message.bot.unban_chat_member(message.chat.id, user_id, only_if_banned=True)
        await message.answer("👢 Member removed from this group.")
    except Exception as exc:
        log.warning("Kick failed in %s for %s: %s", message.chat.id, user_id, exc)
        await message.reply("⚠️ Could not kick that member. Check the bot's ban permission.")


@router.message(Command("warnings"))
async def warnings_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    user_id = await target_user_id(message)
    if not user_id:
        await message.reply("Reply to a member or use /warnings USER_ID.")
        return
    count = await store.warning_count(message.chat.id, user_id)
    await message.answer(f"⚠️ User {user_id} has {count} warning(s) in this group.")


@router.message(Command("resetwarns"))
async def reset_warnings_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    user_id = await target_user_id(message)
    if not user_id:
        await message.reply("Reply to a member or use /resetwarns USER_ID.")
        return
    await store.clear_warnings(message.chat.id, user_id)
    await message.answer(f"✅ Warnings cleared for user {user_id} in this group.")


@router.message(Command("purge"))
async def purge_command(message: Message, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    if not message.reply_to_message:
        await message.reply("Reply to the first message to delete with /purge.")
        return
    start_id = message.reply_to_message.message_id
    end_id = message.message_id
    if end_id - start_id > 100:
        await message.reply("Purge is limited to 100 messages at a time. Choose a later starting message.")
        return
    deleted = 0
    for msg_id in range(start_id, end_id + 1):
        try:
            await message.bot.delete_message(message.chat.id, msg_id)
            deleted += 1
        except Exception:
            continue
    try:
        await message.answer(f"🧹 Deleted {deleted} message(s).", disable_notification=True)
    except Exception:
        pass


@router.message(Command("pin"))
async def pin_command(message: Message, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    if not message.reply_to_message:
        await message.reply("Reply to a message with /pin.")
        return
    try:
        await message.bot.pin_chat_message(message.chat.id, message.reply_to_message.message_id, disable_notification=True)
        await message.answer("📌 Message pinned.")
    except Exception:
        await message.reply("⚠️ Could not pin. Check the bot's pin permission.")


@router.message(Command("unpin"))
async def unpin_command(message: Message, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    try:
        if message.reply_to_message:
            await message.bot.unpin_chat_message(message.chat.id, message.reply_to_message.message_id)
        else:
            await message.bot.unpin_chat_message(message.chat.id)
        await message.answer("📌 Pin removed.")
    except Exception:
        await message.reply("⚠️ Could not unpin. Check the bot's pin permission.")


@router.message(Command("promote"))
async def promote_command(message: Message, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    user_id = await target_user_id(message)
    if not user_id:
        await message.reply("Reply to a member's message or use /promote USER_ID.")
        return
    if message.from_user and user_id == message.from_user.id:
        await message.reply("You cannot promote yourself through this command.")
        return
    try:
        await message.bot.promote_chat_member(
            message.chat.id, user_id,
            can_manage_chat=True, can_delete_messages=True, can_restrict_members=True,
            can_invite_users=True, can_pin_messages=True, can_manage_topics=True,
        )
        await message.answer("✅ Member promoted. Telegram may require the bot to have the appropriate promotion rights.")
    except Exception:
        await message.reply("⚠️ Could not promote. The bot needs administrator and promotion rights.")


@router.message(Command("demote"))
async def demote_command(message: Message, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    user_id = await target_user_id(message)
    if not user_id:
        await message.reply("Reply to an administrator's message or use /demote USER_ID.")
        return
    try:
        await message.bot.promote_chat_member(
            message.chat.id, user_id, can_manage_chat=False, can_delete_messages=False,
            can_manage_video_chats=False, can_restrict_members=False, can_promote_members=False,
            can_change_info=False, can_invite_users=False, can_post_stories=False,
            can_edit_stories=False, can_delete_stories=False, can_pin_messages=False,
            can_manage_topics=False,
        )
        await message.answer("✅ Admin privileges removed.")
    except Exception:
        await message.reply("⚠️ Could not demote. Check the bot's promotion rights.")


@router.message(Command("setwelcome"))
async def set_welcome_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    text = _args(message)
    if not text:
        await message.reply("Usage: /setwelcome Welcome {mention}!\nPlaceholders: {mention}, {first}, {username}, {chat}")
        return
    await store.set_group_setting(message.chat.id, "welcome_text", text[:1000])
    await store.set_group_setting(message.chat.id, "welcome_enabled", True)
    await message.answer("✅ Custom welcome saved for this group.")


@router.message(Command("welcome"))
async def show_welcome_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not in_group(message):
        return
    value = _args(message).casefold()
    if value in {"on", "off"}:
        if not await require_group_admin(message, settings):
            return
        await store.set_group_setting(message.chat.id, "welcome_enabled", value == "on")
        await message.answer(f"✅ Welcome messages {value.upper()}.")
        return
    cfg = await store.get_group_settings(message.chat.id)
    await message.answer("👋 Current welcome message:\n" + cfg.get("welcome_text", "🍥 Welcome {mention} to {chat}!"))


@router.message(Command("resetwelcome"))
async def reset_welcome_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    await store.set_group_setting(message.chat.id, "welcome_text", "🍥 Welcome {mention} to {chat}!")
    await store.set_group_setting(message.chat.id, "welcome_enabled", True)
    await message.answer("✅ Welcome message reset to the default.")


@router.message(Command("setgoodbye"))
async def set_goodbye_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    text = _args(message)
    if not text:
        await message.reply("Usage: /setgoodbye Goodbye {mention}!")
        return
    await store.set_group_setting(message.chat.id, "goodbye_text", text[:1000])
    await store.set_group_setting(message.chat.id, "goodbye_enabled", True)
    await message.answer("✅ Custom goodbye saved for this group.")


@router.message(Command("goodbye"))
async def goodbye_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not in_group(message):
        return
    value = _args(message).casefold()
    if value in {"on", "off"}:
        if not await require_group_admin(message, settings):
            return
        await store.set_group_setting(message.chat.id, "goodbye_enabled", value == "on")
        await message.answer(f"✅ Goodbye messages {value.upper()}.")
        return
    cfg = await store.get_group_settings(message.chat.id)
    await message.answer("👋 Current goodbye message:\n" + cfg.get("goodbye_text", "Goodbye {mention}!"))


@router.message(Command("resetgoodbye"))
async def reset_goodbye_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    await store.set_group_setting(message.chat.id, "goodbye_text", "Goodbye {mention}!")
    await store.set_group_setting(message.chat.id, "goodbye_enabled", False)
    await message.answer("✅ Goodbye message reset and disabled.")


async def _toggle(message: Message, store: SQLiteStore, settings: Settings, key: str, command: str) -> None:
    if not await require_group_admin(message, settings):
        return
    value = _args(message).casefold()
    if value not in {"on", "off"}:
        await message.reply(f"Usage: /{command} on|off")
        return
    await store.set_group_setting(message.chat.id, key, value == "on")
    await message.answer(f"✅ {command} is now {value.upper()} for this group.")


@router.message(Command("antispam"))
async def antispam_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    await _toggle(message, store, settings, "anti_spam", "antispam")


@router.message(Command("antiflood"))
async def antiflood_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    await _toggle(message, store, settings, "anti_flood", "antiflood")


@router.message(Command("antilink"))
async def antilink_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    await _toggle(message, store, settings, "anti_link", "antilink")


@router.message(Command("antiforward"))
async def antiforward_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    await _toggle(message, store, settings, "anti_forward", "antiforward")


@router.message(Command("antibot"))
async def antibot_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    await _toggle(message, store, settings, "anti_bot", "antibot")


@router.message(Command("locks"))
async def locks_command(message: Message, store: SQLiteStore) -> None:
    if not in_group(message):
        return
    cfg = await store.get_group_settings(message.chat.id)
    keys = ("all", "messages", "media", "stickers", "gifs", "links", "polls", "forwards")
    lines = [f"{key}: {'ON' if cfg.get('lock_' + key, False) else 'OFF'}" for key in keys]
    await message.answer("🔒 Group locks\n" + "\n".join(lines))


async def _lock_change(message: Message, store: SQLiteStore, settings: Settings, enabled: bool) -> None:
    if not await require_group_admin(message, settings):
        return
    kind = _args(message).casefold() or "messages"
    valid = {"all", "messages", "media", "stickers", "gifs", "links", "polls", "forwards"}
    if kind not in valid:
        await message.reply("Lock types: all, messages, media, stickers, gifs, links, polls, forwards")
        return

    permission_fields = {
        "messages": ("can_send_messages",),
        "all": ("can_send_messages", "can_send_audios", "can_send_documents", "can_send_photos", "can_send_videos", "can_send_video_notes", "can_send_voice_notes", "can_send_polls", "can_send_other_messages"),
        "media": ("can_send_audios", "can_send_documents", "can_send_photos", "can_send_videos", "can_send_video_notes", "can_send_voice_notes"),
        "stickers": ("can_send_other_messages",), "gifs": ("can_send_other_messages",),
        "polls": ("can_send_polls",),
    }
    fields = permission_fields.get(kind, ())
    cfg = await store.get_group_settings(message.chat.id)
    await store.set_group_setting(message.chat.id, f"lock_{kind}", enabled)
    cfg[f"lock_{kind}"] = enabled

    if fields:
        try:
            chat = await message.bot.get_chat(message.chat.id)
            current_permissions = chat.permissions.model_dump(exclude_none=True) if chat.permissions else {}
            baseline = cfg.get("permissions_baseline")
            if enabled and not baseline:
                baseline = dict(current_permissions)
                await store.set_group_setting(message.chat.id, "permissions_baseline", baseline)
            baseline = baseline or {}

            all_fields = set().union(*[set(items) for items in permission_fields.values()])
            permission_data = dict(current_permissions)
            for field in all_fields:
                locked = any(
                    cfg.get(f"lock_{lock_name}", False) and field in lock_fields
                    for lock_name, lock_fields in permission_fields.items()
                )
                if locked:
                    permission_data[field] = False
                elif field in baseline:
                    permission_data[field] = baseline[field]
            await message.bot.set_chat_permissions(message.chat.id, ChatPermissions(**permission_data))

            if not any(cfg.get(f"lock_{name}", False) for name in permission_fields):
                await store.set_group_setting(message.chat.id, "permissions_baseline", {})
        except Exception:
            log.exception("Could not apply lock permissions in %s", message.chat.id)
            await message.reply("⚠️ The lock setting was saved, but Telegram rejected the permission update. Check bot admin rights.")
            return

    # Links and forwards are filtered in middleware, not by Telegram permissions.
    await message.answer(f"🔒 {kind} lock {'enabled' if enabled else 'disabled'} for this group.")

@router.message(Command("lock"))
async def lock_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    await _lock_change(message, store, settings, True)


@router.message(Command("unlock"))
async def unlock_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    await _lock_change(message, store, settings, False)


@router.message(Command("settings"))
async def settings_command(message: Message, store: SQLiteStore) -> None:
    if not in_group(message):
        return
    cfg = await store.get_group_settings(message.chat.id)
    defaults = await store.get_settings()
    keys = ("anti_spam", "anti_flood", "anti_link", "anti_forward", "anti_bot", "anti_raid", "welcome_enabled", "goodbye_enabled")
    lines = [
        f"{key}: {'ON' if cfg.get(key, defaults.get(key, False)) else 'OFF'}"
        for key in keys
    ]
    lines.append(f"slowmode_seconds: {cfg.get('slowmode_seconds', 0)}")
    await message.answer("⚙️ This group's settings\n" + "\n".join(lines))


@router.message(Command("setdescription"))
async def set_description_command(message: Message, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    description = _args(message)
    if len(description) > 255:
        await message.reply("The group description must be 255 characters or fewer.")
        return
    if not description:
        await message.reply("Usage: /setdescription New group description")
        return
    try:
        await message.bot.set_chat_description(message.chat.id, description)
        await message.answer("✅ Group description updated.")
    except Exception:
        await message.reply("⚠️ Could not update the description. Check the bot's change-info permission.")


@router.message(Command("settitle"))
async def set_title_command(message: Message, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    title = _args(message)
    if not title or len(title) > 128:
        await message.reply("Usage: /settitle New group title (maximum 128 characters)")
        return
    try:
        await message.bot.set_chat_title(message.chat.id, title)
        await message.answer("✅ Group title updated.")
    except Exception:
        await message.reply("⚠️ Could not update the group title. Check the bot's change-info permission.")


@router.message(Command("slowmode"))
async def slowmode_command(message: Message, store: SQLiteStore, settings: Settings) -> None:
    if not await require_group_admin(message, settings):
        return
    raw = _args(message)
    if not raw.isdigit() or not 0 <= int(raw) <= 60:
        await message.reply("Usage: /slowmode SECONDS (0 to disable, maximum 60)")
        return
    seconds = int(raw)
    await store.set_group_setting(message.chat.id, "slowmode_seconds", seconds)
    await message.answer(f"🐢 Slowmode set to {seconds} second(s). It is enforced by the bot; admins are exempt.")


@router.message(Command("filters"))
async def filters_command(message: Message, store: SQLiteStore) -> None:
    if not in_group(message):
        return
    items = await store.list_filters(message.chat.id)
    await message.answer("🔎 Group filters\n" + ("\n".join(f"• {item}" for item in items) if items else "No filters saved in this group."))

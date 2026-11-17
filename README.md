# ANIFLIX GROUP MANAGEMENT BOT

A public, multi-group Telegram administration bot written in Python with **SQLite only**. Each group has independent rules, filters, notes, warnings, settings, lock flags and moderation records. Global owner commands are protected by `OWNER_ID`; the anime availability catalogue and custom conversation auto-replies are restricted to the one group configured as `OWNER_GROUP_ID`.

## Included features

- Public commands: `/start`, `/help`, `/id`, `/info`, `/admins`, `/staff`, `/rules`, `/report`, `/ping`, `/about`, `/notes`, `/get`.
- Group-admin moderation: `/ban`, `/unban`, `/kick`, `/mute`, `/unmute`, `/warn`, `/warnings`, `/resetwarns`, `/purge`, `/pin`, `/unpin`, `/promote`, `/demote`.
- Welcome/goodbye: `/setwelcome`, `/welcome`, `/resetwelcome`, `/setgoodbye`, `/goodbye`, `/resetgoodbye`.
- Rules, filters and notes: `/setrules`, `/filter`, `/stop`, `/filters`, `/save`, `/get`, `/notes`.
- Group protection: `/antispam`, `/antiflood`, `/antilink`, `/antiforward`, `/antibot`, `/lock`, `/unlock`, `/locks`.
- Group settings: `/settings`, `/setdescription`, `/settitle`, `/slowmode`.
- Owner-only private commands: `/owner`, `/stats`, `/groups`, `/users`, `/broadcast`, `/blockgroup`, `/unblockgroup`, `/leave`, `/restart`, `/maintenance`, `/disablemaintenance`, `/logs`, `/clearcache`, `/backup`.
- Owner-group-only features: Tamil anime availability auto-replies, title spelling suggestions, custom TXT trigger/reply responses, and custom conversation library replies. Leaving `OWNER_GROUP_ID` unset disables these group auto-replies.
- No CAPTCHA. Join-burst alerts can be enabled with `/antiraid on` by a group admin; the bot does not challenge or automatically remove normal members.
- `/health` and `/` HTTP health endpoints for Render and UptimeRobot.

## Permissions

| Permission level | Access |
|---|---|
| Bot owner | Global commands, owner panel, broadcast and registered-group controls. Every global command checks the numeric `OWNER_ID` value and is accepted only in the owner's private chat. |
| Group administrators | Moderation and settings for the current group only. Telegram admin status is checked using the current group ID. |
| Group members | Public commands, rules and `/report`. They cannot change settings or moderate members. |

Adding the bot to a group does not give its admins access to `/owner`, `/stats`, `/broadcast`, or any other global control. Group configuration queries and writes are always scoped by that group's numeric chat ID.

## Environment variables

Copy `.env.example` to `.env` locally, or add the same variables in the Render Environment tab.

| Variable | Required | Purpose |
|---|---:|---|
| `BOT_TOKEN` | Yes | BotFather token. Keep it secret. |
| `OWNER_ID` | Yes | Numeric Telegram user ID allowed to use all global controls. Multiple IDs can be comma-separated. |
| `OWNER_GROUP_ID` | No, recommended for special features | Numeric group ID where anime availability and custom conversation auto-replies are enabled. Leave blank to disable those features. |
| `DATABASE_PATH` | No | SQLite file path. Defaults to `./data/aniflix_group_management.db`. |
| `DATA_DIR` | No | Directory for anime TXT snapshots, database backups and default logs. Defaults to `.`. |
| `LOG_FILE` | No | Log file path. Defaults to `<DATA_DIR>/logs/aniflix.log`. |
| `LOG_LEVEL` | No | Logging level, default `INFO`. |
| `BOT_CHANNEL_USERNAME` | No | Channel included in availability replies. Defaults to `@ANIFLIXANIMETAMIL`. |
| `PORT` | No | Render provides this automatically; local default is `10000`. |

Never paste the bot token into a chat or commit a real `.env` file.

## Run locally

Python 3.12 is used by the deployment configuration.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
# Edit .env, then:
python main.py
```

The root `main.py` runs the application as a package entry point. The HTTP health route responds at `/health`.

## Telegram setup

1. Create a bot with BotFather and set `BOT_TOKEN`.
2. Add the numeric owner account to `OWNER_ID`.
3. Set `OWNER_GROUP_ID` to the numeric ID of the one group allowed to use the anime and custom conversation auto-replies. Do not set it to a public customer group.
4. Add the bot to groups. Promote it only with the rights needed for the features you want: deleting messages, restricting members, banning members, pinning messages, changing group info and promoting admins.
5. For ordinary group text processing (anime title detection in the owner group and group filters), disable BotFather privacy mode for the bot. Group membership and privacy settings affect which updates Telegram sends to it.
6. Group admins can then use the commands shown by `/help`. Telegram still validates the bot's own rights for each action.

## Owner-group data and anime TXT files

The special group reply features run only when `message.chat.id == OWNER_GROUP_ID`. Other groups can still use their own admin-configured `/filter` replies, notes, rules and group protection, but cannot access the owner's anime catalogue or conversation dataset.

Anime lists are one title per line in `available_anime.txt` and `unavailable_anime.txt`. The SQLite database is the source of truth after its first initialization; these files are synchronized snapshots. Custom conversation files in `conversation_replies/*.txt` use this format:

```text
trigger phrase = reply text
```

The owner's private `/admin` panel supports conversation TXT import, export, count and clear confirmation. Imports are additive, duplicate entries are skipped, and clearing requires confirmation. Telegram's standard bot file download limit is 20 MB, so split larger TXT files before upload.

## Group command notes

- For `/ban`, `/mute`, `/unmute`, `/warn`, `/kick`, `/pin`, `/promote` and related reply-based actions, reply to the target member's message. Commands that support numeric IDs also accept `USER_ID` where the usage message indicates it.
- `/report` saves a report in that group. Group admins can review the latest reports with the additional `/reports` command.
- `/lock` and `/unlock` support `all`, `messages`, `media`, `stickers`, `gifs`, `links`, `polls` and `forwards`. The bot stores each group's lock state separately.
- `/slowmode SECONDS` enforces a per-user delay of 0–60 seconds using the bot's runtime rate limiter. The configured delay persists; recent timestamps are in memory and reset on restart.
- `/antiflood` is a per-group setting; the current default is enabled. `/antispam` detects repeated identical messages from the same member within its short runtime window.
- `/antibot on` attempts to remove bot accounts when they join. This requires the bot to have ban permissions.

## Owner operations

- `/broadcast` must be used in the owner's private chat as a reply to the message to copy. The bot asks for confirmation and skips blocked groups.
- `/blockgroup GROUP_ID` and `/unblockgroup GROUP_ID` block or restore a registered group.
- `/leave GROUP_ID` makes the bot leave and marks that group inactive.
- `/maintenance` temporarily ignores non-owner messages in groups; `/disablemaintenance` resumes processing.
- `/restart` restarts the Telegram polling session while keeping the web health server and SQLite connection alive.
- `/backup` creates and sends a consistent SQLite backup. `/logs` sends the current local log file when available.
- `/users` lists unique user IDs observed in received group updates. It is not a count of every member in each Telegram group; Telegram does not provide a complete member list to ordinary bots.

## Render and UptimeRobot

The included `render.yaml` uses:

- Build command: `pip install -r requirements.txt`
- Start command: `python main.py`
- Health check: `/health`

After deployment, set `BOT_TOKEN` and `OWNER_ID`; set `OWNER_GROUP_ID` only if you want the owner-group special features. UptimeRobot can monitor the public service URL at `/health`.

**SQLite persistence warning:** Render Free services use an ephemeral filesystem. The database and log files stored there can be lost when the instance is replaced or redeployed. For persistent SQLite storage, attach a persistent disk on a plan that supports it, then set `DATABASE_PATH=/var/data/aniflix_group_management.db`, `DATA_DIR=/var/data`, and optionally `LOG_FILE=/var/data/logs/aniflix.log`. Do not assume the Free instance's local disk is permanent. Run `/backup` regularly and keep downloaded copies somewhere safe.

## Tests and verification scope

Install the development requirements and run:

```bash
pip install -r requirements-dev.txt
pytest -q
python -m compileall -q app tests main.py
```

The test suite covers SQLite group isolation, legacy schema migration, users/reports, database backup, anime catalog behaviour, custom conversation import/matching, and moderation helper logic. The Telegram API and Render deployment still need a live smoke test with a real bot token and the correct admin permissions; those credentials are not included in this repository.

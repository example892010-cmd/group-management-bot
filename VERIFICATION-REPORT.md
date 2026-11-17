# ANIFLIX Group Management Bot — Verification Report

## Local checks performed for this ZIP

- Python syntax compilation: `python -m compileall -q app tests main.py` — passed.
- Unit test suite: `pytest -q` — **33 passed**.
- Command inventory: all requested public/group-admin commands and all requested owner commands are present as handler registrations.
- SQLite multi-group isolation: group settings, rules, notes, filters, warnings and records are keyed by group ID.
- SQLite owner controls: unique-user tracking, reports, blocked-group state, maintenance setting and consistent backup are covered by tests.
- Legacy database migration: the `blocked` field is added in place without dropping existing registered groups.
- First-run seeding: bundled anime TXT files seed a new database on a separate persistent data mount, while existing mounted snapshots take precedence over repository defaults.
- Conversation features: additive TXT import, duplicate handling, phrase matching, large imports, export and clear-confirmation storage behaviour are covered by the existing tests.
- Moderation helpers: anti-flood, join-burst alert, duplicate-message and slowmode helper tests pass.
- Root Render entry point: `main.py` imports and calls `app.main.run` as a package entry point.

## Verification limits — read before deployment

This build environment has no network access and does not have `aiogram` installed. Therefore dependencies could not be installed here, and I could not run handler-import tests, connect to Telegram, verify real bot permissions, or deploy to Render. The ZIP is syntax-checked and its local unit tests pass, but it is **not represented as live-Telegram or live-Render tested**. Install the packages from `requirements.txt`, then complete a smoke test with your own bot token and a test group.

## Deployment notes

Set `BOT_TOKEN` and `OWNER_ID` in Render. Set `OWNER_GROUP_ID` only if you want anime availability and the private conversation library enabled in one designated group. Leave it blank to disable those owner-group features.

Render Free has ephemeral storage. SQLite files may be lost when the service is replaced, redeployed or spun down. For durable SQLite storage, use a Render service plan that supports a persistent disk and mount it at `/var/data`; set `DATABASE_PATH=/var/data/aniflix_group_management.db` and `DATA_DIR=/var/data`. UptimeRobot monitors availability; it does not make the local database persistent. Use `/backup` and keep downloaded backups in a separate safe location.

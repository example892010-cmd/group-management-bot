# ANIFLIX Group Management Bot — Verification Report

## Local checks performed

- Python syntax compilation: `python -m compileall -q .` — passed.
- Unit test suite: `pytest -q` — **24 passed**.
- SQLite multi-group isolation tests: passed for per-group settings, rules, notes, and keyword filters.
- Conversation library tests: additive import, duplicate handling, phrase matching, 100,000-entry import, export, and clear-confirmation storage behaviour — passed.
- Moderation tests: anti-flood and join-burst alert guard — passed.
- Root Render entry point: `main.py` imports `app.main.run` as a package entry point.

## Important verification limits

This environment had no network access and `aiogram` was not installed, so a dependency installation, Telegram API smoke test, and live Render deployment could not be performed here. The ZIP is unit-tested and syntax-checked, but it is **not claimed to be live-Telegram tested**. Install dependencies from `requirements.txt` before running it.

## Deployment configuration

Set `BOT_TOKEN`, `OWNER_ID`, and `OWNER_GROUP_ID` in Render. `OWNER_GROUP_ID` is the group where the owner's custom conversation library is allowed to reply. Leave it unset to disable group conversation replies. SQLite on Render Free uses ephemeral storage unless a persistent disk is attached; export important conversation data regularly.

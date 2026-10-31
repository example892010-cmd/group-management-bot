"""Trigger-specific replies loaded from editable TXT files on every message."""
from __future__ import annotations

import random
import re
from pathlib import Path
from collections import defaultdict

from .catalog import normalize_title

_last: dict[str, str] = {}


def _matches(message: str, trigger: str) -> bool:
    msg = normalize_title(message)
    key = normalize_title(trigger)
    if not msg or not key:
        return False
    # Short triggers such as "hi" must match as whole words, never inside another word.
    return re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", msg) is not None


def get_txt_reply(message: str, data_dir: Path) -> str | None:
    folder = data_dir / "conversation_replies"
    if not folder.exists():
        folder = Path(__file__).resolve().parent.parent / "conversation_replies"
    candidates: list[tuple[str, str]] = []
    if not folder.exists():
        return None
    for path in sorted(folder.glob("*.txt")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            trigger, reply = (part.strip() for part in line.split("=", 1))
            if trigger and reply and _matches(message, trigger):
                candidates.append((trigger.casefold(), reply))
    if not candidates:
        return None
    # Prefer the most specific trigger if several phrases match.
    longest = max(len(normalize_title(trigger)) for trigger, _ in candidates)
    candidates = [item for item in candidates if len(normalize_title(item[0])) == longest]
    trigger_key = candidates[0][0]
    replies = list(dict.fromkeys(reply for _, reply in candidates))
    choices = [reply for reply in replies if reply != _last.get(trigger_key)] or replies
    selected = random.choice(choices)
    _last[trigger_key] = selected
    return selected

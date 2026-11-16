"""Small in-memory anti-flood helper."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class FloodGuard:
    limit: int = 7
    window_seconds: float = 10.0
    recent: dict[tuple[int, int], deque[float]] = field(default_factory=lambda: defaultdict(deque))

    def is_flooding(self, chat_id: int, user_id: int, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        bucket = self.recent[(chat_id, user_id)]
        while bucket and current - bucket[0] > self.window_seconds:
            bucket.popleft()
        bucket.append(current)
        if len(bucket) > self.limit:
            bucket.clear()
            return True
        return False


@dataclass
class JoinBurstGuard:
    """Detect join bursts without CAPTCHA or automatic member removal."""
    limit: int = 6
    window_seconds: float = 15.0
    recent: dict[int, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    alerted: dict[int, float] = field(default_factory=dict)

    def is_raid(self, chat_id: int, count: int = 1, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        bucket = self.recent[chat_id]
        while bucket and current - bucket[0] > self.window_seconds:
            bucket.popleft()
        for _ in range(max(1, count)):
            bucket.append(current)
        if len(bucket) < self.limit:
            return False
        last_alert = self.alerted.get(chat_id)
        if last_alert is not None and current - last_alert < self.window_seconds:
            return False
        self.alerted[chat_id] = current
        bucket.clear()
        return True

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

from app.moderation import FloodGuard


def test_flood_guard_trips_after_limit_and_resets_after_window():
    guard = FloodGuard(limit=3, window_seconds=10)
    assert guard.is_flooding(1, 2, now=0) is False
    assert guard.is_flooding(1, 2, now=1) is False
    assert guard.is_flooding(1, 2, now=2) is False
    assert guard.is_flooding(1, 2, now=3) is True
    assert guard.is_flooding(1, 2, now=20) is False


def test_flood_guard_separates_users_and_groups():
    guard = FloodGuard(limit=1, window_seconds=10)
    assert guard.is_flooding(1, 2, now=0) is False
    assert guard.is_flooding(1, 3, now=0) is False
    assert guard.is_flooding(2, 2, now=0) is False
    assert guard.is_flooding(1, 2, now=1) is True

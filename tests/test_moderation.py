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

from app.moderation import JoinBurstGuard


def test_join_burst_guard_alerts_without_changing_member_access():
    guard = JoinBurstGuard(limit=3, window_seconds=10)
    assert guard.is_raid(-100, now=0) is False
    assert guard.is_raid(-100, now=1) is False
    assert guard.is_raid(-100, now=2) is True
    # Repeated bursts are rate-limited to avoid alert spam.
    assert guard.is_raid(-100, now=3) is False
    assert guard.is_raid(-100, now=20) is False
    assert guard.is_raid(-100, now=21) is False
    assert guard.is_raid(-100, now=22) is True

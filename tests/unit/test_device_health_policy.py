from datetime import datetime, timedelta, timezone

from services.dashboard_service.overview_repository import connectivity_status


def test_device_health_policy_online_stale_offline_unknown():
    now = datetime(2026, 10, 8, 5, 0, tzinfo=timezone.utc)
    assert connectivity_status(None, now=now) == "unknown"
    assert connectivity_status(now - timedelta(seconds=60), now=now) == "online"
    assert connectivity_status(now - timedelta(seconds=1200), now=now) == "stale"
    assert connectivity_status(now - timedelta(seconds=7200), now=now) == "offline"

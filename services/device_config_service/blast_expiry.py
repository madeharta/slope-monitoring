"""BC-01: conservative, server-time-only blast command expiry decision."""
from datetime import datetime, timedelta, timezone


def expired(started_at: datetime | None, timeout_minutes: object, now: datetime) -> bool:
    """Unknown/invalid timing is NOT permission to serve an active command."""
    if started_at is None or started_at.tzinfo is None or now.tzinfo is None:
        return True
    try:
        if isinstance(timeout_minutes, bool):
            return True
        minutes = int(timeout_minutes)
        if minutes <= 0 or str(timeout_minutes).strip() != str(minutes):
            return True
    except (TypeError, ValueError, OverflowError):
        return True
    return now.astimezone(timezone.utc) >= started_at.astimezone(timezone.utc) + timedelta(minutes=minutes)

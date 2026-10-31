"""RC-01: verify retention opt-out without connecting to a real database."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.api import main as api_main


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("flag", "expected_retention_calls"),
    [("false", 0), ("true", 1), (None, 1)],
)
async def test_lifespan_retention_flag(monkeypatch, flag, expected_retention_calls):
    """Default preserves legacy behavior; false makes no retention DB call."""
    if flag is None:
        monkeypatch.delenv("RETENTION_POLICY_MANAGEMENT_ENABLED", raising=False)
    else:
        monkeypatch.setenv("RETENTION_POLICY_MANAGEMENT_ENABLED", flag)
    monkeypatch.setenv("WEATHER_POLLING_ENABLED", "false")
    monkeypatch.setenv("MEASUREMENTS_RETENTION_DAYS", "730")

    conn = SimpleNamespace(execute=AsyncMock())
    pool = SimpleNamespace(acquire=lambda: FakeAcquire(conn), close=AsyncMock())
    create_pool = AsyncMock(return_value=pool)
    weather_poll = AsyncMock()
    monkeypatch.setattr(api_main.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(api_main.weather, "weather_poll_loop", weather_poll)
    monkeypatch.setattr(api_main, "ModelRegistry", lambda: object())
    monkeypatch.setattr(api_main, "RINEXCache", lambda path: object())
    monkeypatch.setattr(api_main, "RINEXNavigationAcquisition", lambda cache: object())

    app = SimpleNamespace(state=SimpleNamespace())
    async with api_main.lifespan(app):
        assert app.state.db_pool is pool

    assert conn.execute.await_count == expected_retention_calls
    if expected_retention_calls:
        sql, days = conn.execute.await_args.args
        assert "add_retention_policy" in sql
        assert days == 730
    weather_poll.assert_not_awaited()
    pool.close.assert_awaited_once()

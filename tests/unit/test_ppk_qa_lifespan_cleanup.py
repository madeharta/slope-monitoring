import pytest
from unittest.mock import AsyncMock

from fastapi import FastAPI
from apps.api import main as api_main


@pytest.mark.asyncio
async def test_main_pool_closes_when_qa_pool_creation_fails(monkeypatch):
    main_pool = AsyncMock()
    qa_error = ConnectionError("Simulated QA DB unavailable")

    create_pool = AsyncMock(
        side_effect=[main_pool, qa_error]
    )

    monkeypatch.setattr(
        api_main.asyncpg,
        "create_pool",
        create_pool,
    )

    settings = {
        "PPK_QA_DB_HOST": "qa-db",
        "PPK_QA_DB_PORT": "5432",
        "PPK_QA_DB_NAME": "ppk_qa_acceptance",
        "PPK_QA_DB_USER": "ppk_qa_reader",
        "PPK_QA_DB_PASSWORD": "test-only-not-real",
        "DB_USER": "slope",
        "WEATHER_POLLING_ENABLED": "false",
        "RETENTION_POLICY_MANAGEMENT_ENABLED": "false",
    }

    for key, value in settings.items():
        monkeypatch.setenv(key, value)

    app = FastAPI()

    with pytest.raises(ConnectionError, match="QA DB unavailable"):
        async with api_main.lifespan(app):
            pytest.fail("Startup must not succeed")

    assert create_pool.await_count == 2
    main_pool.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_pool_closes_on_incomplete_qa_config(monkeypatch):
    main_pool = AsyncMock()
    create_pool = AsyncMock(return_value=main_pool)

    monkeypatch.setattr(
        api_main.asyncpg,
        "create_pool",
        create_pool,
    )

    for key in (
        "PPK_QA_DB_HOST",
        "PPK_QA_DB_PORT",
        "PPK_QA_DB_NAME",
        "PPK_QA_DB_USER",
        "PPK_QA_DB_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("PPK_QA_DB_HOST", "qa-db")
    monkeypatch.setenv("WEATHER_POLLING_ENABLED", "false")
    monkeypatch.setenv(
        "RETENTION_POLICY_MANAGEMENT_ENABLED",
        "false",
    )

    app = FastAPI()

    with pytest.raises(
        RuntimeError,
        match="Incomplete PPK QA database configuration",
    ):
        async with api_main.lifespan(app):
            pytest.fail("Startup must not succeed")

    create_pool.assert_awaited_once()
    main_pool.close.assert_awaited_once()

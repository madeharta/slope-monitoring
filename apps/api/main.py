from __future__ import annotations
import asyncio
import contextlib
import json
import os
import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apps.api.middlewares.error_handler import register_error_handlers
from apps.api.routers.v1 import auth, blast, dashboard, device_config, devices_and_audit, ingest, model_ops, ppk, sensors, sites, uploads, users, weather, base_references, wu_weather
from ml.pipeline.preprocessing.ppk_engine import RTKLibPPKEngine
from services.rinex_service.acquisition import RINEXNavigationAcquisition
from services.rinex_service.cache import RINEXCache
from ml.registry.model_registry import ModelRegistry
load_dotenv()
async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog", format="text",
    )
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_pool = await asyncpg.create_pool(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "slope"),
        user=os.getenv("DB_USER", "slope"),
        password=os.getenv("DB_PASSWORD", "slope_dev"),
        min_size=1,
        max_size=10,
        init=_init_connection,
    )

    app.state.ppk_qa_db_pool = None
    weather_task = None
    try:

        qa_keys = (
            "PPK_QA_DB_HOST",
            "PPK_QA_DB_PORT",
            "PPK_QA_DB_NAME",
            "PPK_QA_DB_USER",
            "PPK_QA_DB_PASSWORD",
        )

        qa_configured = any(os.getenv(key) for key in qa_keys)

        if qa_configured:
            missing = [key for key in qa_keys if not os.getenv(key)]
            if missing:
                raise RuntimeError(
                    "Incomplete PPK QA database configuration: "
                    + ", ".join(missing)
                )

            if os.environ["PPK_QA_DB_USER"] == os.getenv("DB_USER"):
                raise RuntimeError(
                    "PPK QA database user must differ from operational DB user"
                )

            app.state.ppk_qa_db_pool = await asyncpg.create_pool(
                host=os.environ["PPK_QA_DB_HOST"],
                port=int(os.environ["PPK_QA_DB_PORT"]),
                database=os.environ["PPK_QA_DB_NAME"],
                user=os.environ["PPK_QA_DB_USER"],
                password=os.environ["PPK_QA_DB_PASSWORD"],
                min_size=1,
                max_size=3,
                init=_init_connection,
                server_settings={
                    "default_transaction_read_only": "on",
                },
            )

        app.state.model_registry = ModelRegistry()
        rinex_cache = RINEXCache(os.getenv("RINEX_CACHE_DIR", "/data/rinex-cache"))
        nav_acquisition = RINEXNavigationAcquisition(rinex_cache)
        app.state.ppk_engine_factory = lambda base_reference: RTKLibPPKEngine(
            base_reference_lat=base_reference.latitude,
            base_reference_lon=base_reference.longitude,
            base_reference_alt_m=base_reference.altitude_m,
            convbin_path=os.getenv("RTKLIB_CONVBIN_PATH", "convbin"),
            rnx2rtkp_path=os.getenv("RTKLIB_RNX2RTKP_PATH", "rnx2rtkp"),
            nav_file=os.getenv("RTKLIB_NAV_FILE") or None,
            navigation_acquisition=nav_acquisition,
            rtklib_config_file=os.getenv("RTKLIB_CONFIG_FILE", "config/rtklib_ppk.conf"),
        )
        if os.getenv("WEATHER_POLLING_ENABLED", "false").lower() == "true":
            weather_task = asyncio.create_task(weather.weather_poll_loop(app.state.db_pool))
        if os.getenv("RETENTION_POLICY_MANAGEMENT_ENABLED", "true").strip().lower() == "true":
            measurements_retention_days = int(os.getenv("MEASUREMENTS_RETENTION_DAYS", "730"))
            async with app.state.db_pool.acquire() as conn:
                await conn.execute(
                    "SELECT add_retention_policy('measurements', make_interval(days => $1), if_not_exists => TRUE)",
                    measurements_retention_days,
                )
        yield
    finally:
        if weather_task is not None:
            weather_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await weather_task
        try:
            if app.state.ppk_qa_db_pool is not None:
                await app.state.ppk_qa_db_pool.close()
        finally:
            await app.state.db_pool.close()

app = FastAPI(title="Slope & Blast Monitoring API", version="1.0.0", lifespan=lifespan)
_allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
_allowed_origins = [o.strip() for o in _allowed_origins]
for _origin in _allowed_origins:
    if not (_origin.startswith("http://") or _origin.startswith("https://")):
        raise RuntimeError(
            f"ALLOWED_ORIGINS entry '{_origin}' is missing http:// or https:// — "
            f"CORS will silently reject every request from it otherwise. Fix .env."
        )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
register_error_handlers(app)
app.include_router(ingest.router)
app.include_router(device_config.router)
app.include_router(device_config.compat_router)
app.include_router(blast.router)
app.include_router(auth.router)
app.include_router(model_ops.router)
app.include_router(weather.router)
app.include_router(wu_weather.router)
app.include_router(ppk.router)
app.include_router(base_references.router)
app.include_router(sensors.router)
app.include_router(dashboard.router)
app.include_router(sites.router)
app.include_router(devices_and_audit.router)
app.include_router(uploads.router)
app.include_router(users.router)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

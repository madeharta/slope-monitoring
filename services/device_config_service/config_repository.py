from __future__ import annotations
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from common.errors import NotFoundError
@dataclass(frozen=True)
class ConfigWrite:
    device_id: str
    config_key: str
    config_value: Any
    updated_by: str
_CONTRACT_KEYS = {
    "periodic_upload_s",
    "firmware_version",
    "threshold_g",
    "time_record_ms",
    "TriggerStart",
    "TimeOutTrigger",
}
_BATTERY_KEYS = {"battery_cal_m", "battery_cal_c"}
_GLOBAL_KEYS = {"TriggerStart", "TimeOutTrigger"}
def _default_config() -> dict[str, Any]:
    return {
        "periodic_upload_s": int(os.getenv("DEVICE_DEFAULT_PERIODIC_UPLOAD_S", "300")),
        "firmware_version": os.getenv("DEVICE_DEFAULT_FIRMWARE_VERSION", ""),
        "threshold_g": float(os.getenv("DEVICE_DEFAULT_THRESHOLD_G", "0.5")),
        "time_record_ms": int(os.getenv("DEVICE_DEFAULT_TIME_RECORD_MS", "2000")),
        "TriggerStart": int(os.getenv("DEVICE_DEFAULT_TRIGGER_START", "0")),
        "TimeOutTrigger": int(os.getenv("DEVICE_DEFAULT_TIMEOUT_TRIGGER", "300")),
    }
def compose_contract_config(
    requested: dict[str, Any],
    base: dict[str, Any],
    battery_cal: dict[str, dict[str, float | None]],
    requested_is_base: bool,
) -> dict[str, Any]:
    config = _default_config()
    config.update({k: v for k, v in base.items() if k in _CONTRACT_KEYS})
    config.update({k: v for k, v in requested.items() if k in _CONTRACT_KEYS and (requested_is_base or k not in _GLOBAL_KEYS)})
    trigger_value = config["TriggerStart"]
    if isinstance(trigger_value, str):
        trigger_value = trigger_value.strip().lower() in {"1", "true", "yes", "on"}
    config["TriggerStart"] = 1 if bool(trigger_value) else 0
    config["TimeOutTrigger"] = int(config["TimeOutTrigger"])
    config["periodic_upload_s"] = int(config["periodic_upload_s"])
    config["time_record_ms"] = int(config["time_record_ms"])
    config["threshold_g"] = float(config["threshold_g"])
    config["firmware_version"] = str(config["firmware_version"])
    config["battery_cal"] = battery_cal
    return config
class DeviceConfigRepository:
    def __init__(self, pool) -> None:
        self._pool = pool
    async def write_value(self, write: ConfigWrite) -> None:
        if write.config_key in _BATTERY_KEYS:
            await self._write_battery_value(write)
            return
        if write.config_key not in _CONTRACT_KEYS:
            raise ValueError(f"unsupported config key: {write.config_key}")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO device_config (device_id, config_key, config_value, updated_by, updated_at)
                    VALUES ($1, $2, $3, $4, now())
                    ON CONFLICT (device_id, config_key)
                    DO UPDATE SET config_value = EXCLUDED.config_value,
                                  updated_by = EXCLUDED.updated_by,
                                  updated_at = now()
                    """,
                    write.device_id, write.config_key, write.config_value, write.updated_by,
                )
                await conn.execute(
                    """
                    INSERT INTO device_config_pending (device_id, config_key, config_value, created_at)
                    VALUES ($1, $2, $3, now())
                    """,
                    write.device_id, write.config_key, write.config_value,
                )
    async def _write_battery_value(self, write: ConfigWrite) -> None:
        column = "battery_cal_m" if write.config_key == "battery_cal_m" else "battery_cal_c"
        value = float(write.config_value)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchval("SELECT 1 FROM devices WHERE device_id = $1", write.device_id)
                if exists is None:
                    raise NotFoundError("device", write.device_id)
                await conn.execute(
                    f"""
                    INSERT INTO device_battery_cal (device_id, {column}, updated_by, updated_at)
                    VALUES ($1, $2, $3, now())
                    ON CONFLICT (device_id)
                    DO UPDATE SET {column} = EXCLUDED.{column}, updated_by = EXCLUDED.updated_by, updated_at = now()
                    """,
                    write.device_id, value, write.updated_by,
                )
                await conn.execute(
                    """
                    INSERT INTO device_config_pending (device_id, config_key, config_value, created_at)
                    VALUES ($1, $2, $3, now())
                    """,
                    write.device_id, write.config_key, value,
                )
    async def get_current_config(self, device_id: str) -> dict[str, Any]:
        return await self.get_contract_config(device_id)
    async def get_contract_config(self, device_id: str) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            device = await conn.fetchrow(
                "SELECT device_id, device_type, site_id FROM devices WHERE device_id = $1",
                device_id,
            )
            if device is None:
                raise NotFoundError("device", device_id)
            base = await conn.fetchrow(
                """
                SELECT device_id FROM devices
                WHERE site_id = $1 AND (device_id = 'BASE-01' OR lower(device_type) = 'base')
                ORDER BY CASE WHEN device_id = 'BASE-01' THEN 0 ELSE 1 END, device_id
                LIMIT 1
                """,
                device["site_id"],
            )
            base_id = base["device_id"] if base is not None else device_id
            requested_rows = await conn.fetch(
                "SELECT config_key, config_value FROM device_config WHERE device_id = $1",
                device_id,
            )
            base_rows = requested_rows if base_id == device_id else await conn.fetch(
                "SELECT config_key, config_value FROM device_config WHERE device_id = $1",
                base_id,
            )
            battery_rows = await conn.fetch(
                """
                SELECT d.device_id, b.battery_cal_m, b.battery_cal_c
                FROM devices d
                LEFT JOIN device_battery_cal b ON b.device_id = d.device_id
                WHERE d.site_id = $1
                ORDER BY d.device_id
                """,
                device["site_id"],
            )
        requested = {r["config_key"]: r["config_value"] for r in requested_rows}
        base_config = {r["config_key"]: r["config_value"] for r in base_rows}
        battery_cal = {
            r["device_id"]: {"m": r["battery_cal_m"], "c": r["battery_cal_c"]}
            for r in battery_rows
        }
        return compose_contract_config(requested, base_config, battery_cal, base_id == device_id)
    async def set_site_trigger(
        self,
        base_id: str,
        trigger_start: int,
        timeout_minutes: int | None,
        updated_by: str,
    ) -> None:
        if trigger_start not in {0, 1}:
            raise ValueError("TriggerStart must be 0 or 1")
        async with self._pool.acquire() as conn:
            base = await conn.fetchrow("SELECT device_id FROM devices WHERE device_id = $1", base_id)
            if base is None:
                raise NotFoundError("device", base_id)
            async with conn.transaction():
                writes = [("TriggerStart", trigger_start)]
                if timeout_minutes is not None:
                    if timeout_minutes <= 0:
                        raise ValueError("TimeOutTrigger must be greater than 0 minutes")
                    writes.append(("TimeOutTrigger", timeout_minutes))
                for key, value in writes:
                    await conn.execute(
                        """
                        INSERT INTO device_config (device_id, config_key, config_value, updated_by, updated_at)
                        VALUES ($1, $2, $3, $4, now())
                        ON CONFLICT (device_id, config_key)
                        DO UPDATE SET config_value = EXCLUDED.config_value,
                                      updated_by = EXCLUDED.updated_by,
                                      updated_at = now()
                        """,
                        base_id, key, value, updated_by,
                    )
                    await conn.execute(
                        """
                        INSERT INTO device_config_pending (device_id, config_key, config_value, created_at)
                        VALUES ($1, $2, $3, now())
                        """,
                        base_id, key, value,
                    )
    async def ack_pending(self, device_id: str, config_key: str, acked_at: datetime) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE device_config_pending SET acked_at = $3
                WHERE id = (
                    SELECT id FROM device_config_pending
                    WHERE device_id = $1 AND config_key = $2 AND acked_at IS NULL
                    ORDER BY created_at ASC LIMIT 1
                )
                """,
                device_id, config_key, acked_at,
            )

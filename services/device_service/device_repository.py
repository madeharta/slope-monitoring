from __future__ import annotations
from dataclasses import dataclass
from common.errors import AppError, ErrorCode, NotFoundError
@dataclass(frozen=True)
class NewDevice:
    device_id: str
    device_type: str
    site_id: str
    label: str | None = None
class DeviceRepository:
    def __init__(self, pool) -> None:
        self._pool = pool
    async def create(self, device: NewDevice) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO devices (device_id, device_type, site_id, label) VALUES ($1, $2, $3, $4)",
                device.device_id, device.device_type, device.site_id, device.label,
            )
    @staticmethod
    def _build_update_clause(
        device_type: str | None, site_id: str | None, label: str | None = None, label_given: bool = False,
    ) -> tuple[list[str], list]:
        fields, args = [], []
        if device_type is not None:
            args.append(device_type)
            fields.append(f"device_type = ${len(args)}")
        if site_id is not None:
            args.append(site_id)
            fields.append(f"site_id = ${len(args)}")
        if label_given:
            args.append(label if label else None)
            fields.append(f"label = ${len(args)}")
        return fields, args
    async def update(
        self, device_id: str, device_type: str | None, site_id: str | None,
        label: str | None = None, label_given: bool = False,
    ) -> None:
        fields, args = self._build_update_clause(device_type, site_id, label, label_given)
        if not fields:
            return
        args.append(device_id)
        import asyncpg
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    f"UPDATE devices SET {', '.join(fields)} WHERE device_id = ${len(args)}", *args,
                )
        except asyncpg.exceptions.RaiseError as exc:
            raise AppError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
        if result == "UPDATE 0":
            raise NotFoundError("device", device_id)
    async def has_measurement_history(self, device_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchval("SELECT 1 FROM measurements WHERE device_id = $1 LIMIT 1", device_id)
        return row is not None
    async def delete(self, device_id: str) -> None:
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM devices WHERE device_id = $1", device_id)
        if result == "DELETE 0":
            raise NotFoundError("device", device_id)

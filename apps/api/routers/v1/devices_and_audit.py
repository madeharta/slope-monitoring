from __future__ import annotations
from datetime import datetime
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from apps.api.dependencies import get_db_pool, require_role
from common.audit import AuditLog
from common.errors import AppError, ErrorCode, NotFoundError
from common.security import TokenPayload
from services.device_service.device_repository import DeviceRepository, NewDevice
router = APIRouter(prefix="/api/v1", tags=["devices_and_audit"])
_ONLINE_WINDOW_SECONDS = 900
@router.get("/devices")
async def list_devices(request: Request, user: TokenPayload = Depends(require_role("viewer"))) -> dict:
    pool = get_db_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT device_id, device_type, site_id, label, first_seen, last_seen,
                   (last_seen IS NOT NULL AND last_seen > now() - make_interval(secs => $1)) AS online
            FROM devices
            ORDER BY site_id, device_id
            """,
            _ONLINE_WINDOW_SECONDS,
        )
    return {
        "ok": True,
        "devices": [
            {
                "device_id": r["device_id"], "device_type": r["device_type"], "site_id": r["site_id"],
                "label": r["label"],
                "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
                "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
                "online": r["online"],
            }
            for r in rows
        ],
    }
class CreateDeviceRequest(BaseModel):
    device_id: str
    device_type: str
    site_id: str
    label: str | None = None
@router.post("/devices")
async def create_device(
    body: CreateDeviceRequest, request: Request, user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    pool = get_db_pool(request)
    await DeviceRepository(pool).create(
        NewDevice(device_id=body.device_id, device_type=body.device_type, site_id=body.site_id, label=body.label)
    )
    await AuditLog(pool).record(
        actor_user_id=user.sub, action="device.create", target_type="device", target_id=body.device_id,
        new_value={"device_type": body.device_type, "site_id": body.site_id, "label": body.label},
    )
    return {"ok": True, "device_id": body.device_id}
class UpdateDeviceRequest(BaseModel):
    device_type: str | None = None
    site_id: str | None = None
    label: str | None = None
    label_given: bool = False
@router.put("/devices/{device_id}")
async def update_device(
    device_id: str, body: UpdateDeviceRequest, request: Request, user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    pool = get_db_pool(request)
    await DeviceRepository(pool).update(device_id, body.device_type, body.site_id, body.label, body.label_given)
    await AuditLog(pool).record(
        actor_user_id=user.sub, action="device.update", target_type="device", target_id=device_id,
        new_value={"device_type": body.device_type, "site_id": body.site_id, "label": body.label if body.label_given else "(tidak diubah)"},
    )
    return {"ok": True, "device_id": device_id}
@router.delete("/devices/{device_id}")
async def delete_device(
    device_id: str, request: Request, force: bool = Query(default=False), purge: bool = Query(default=False),
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    pool = get_db_pool(request)
    repo = DeviceRepository(pool)
    has_history = await repo.has_measurement_history(device_id)
    if not force and has_history:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"device '{device_id}' punya riwayat data di tabel measurements — data itu TIDAK IKUT terhapus "
            f"kecuali purge=true juga dikirim, kirim ulang dengan force=true kalau tetap mau lanjut",
        )
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO audit_log (actor_user_id, action, target_type, target_id, new_value) VALUES ($1, $2, $3, $4, $5)",
                int(user.sub), "device.delete", "device", device_id,
                {"purged_measurements": purge and has_history},
            )
            purged_count = 0
            if purge:
                purged_result = await conn.execute("DELETE FROM measurements WHERE device_id = $1", device_id)
                purged_count = int(purged_result.split()[-1]) if purged_result.startswith("DELETE") else 0
            result = await conn.execute("DELETE FROM devices WHERE device_id = $1", device_id)
    if result == "DELETE 0":
        raise NotFoundError("device", device_id)
    return {"ok": True, "purged_measurements": purged_count}
@router.get("/measurements")
async def list_measurements(
    request: Request,
    user: TokenPayload = Depends(require_role("viewer")),
    site_id: str | None = Query(default=None),
    device_id: str | None = Query(default=None),
    quantity: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    validation_status: str | None = Query(default=None),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    sort_by: str = Query(default="time"),
    sort_dir: str = Query(default="desc"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    pool = get_db_pool(request)
    where: list[str] = []
    args: list = []
    def add(value, clause: str):
        if value is not None and value != "":
            args.append(value)
            where.append(clause.format(n=len(args)))
    add(site_id, "site_id = ${n}")
    add(device_id, "device_id = ${n}")
    add(quantity, "quantity = ${n}")
    add(source_kind, "source_kind = ${n}")
    add(validation_status, "validation_status = ${n}")
    add(from_time, "time >= ${n}")
    add(to_time, "time <= ${n}")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    allowed_sorts = {
        "time": "time",
        "received_at": "received_at",
    }
    order_column = allowed_sorts.get(sort_by)
    if order_column is None:
        raise ValueError("sort_by must be one of: time, received_at")
    direction = sort_dir.lower()
    if direction not in {"asc", "desc"}:
        raise ValueError("sort_dir must be asc or desc")
    order_sql = f"{order_column} {direction.upper()}, time DESC, received_at DESC"
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT count(*) FROM measurements {where_sql}", *args)
        paged_args = [*args, limit, offset]
        rows = await conn.fetch(
            f"""
            SELECT time, device_id, site_id, quantity, value, unit, depth_cm,
                   quality_flag, received_at, latency_ms,
                   source_kind, source_file, validation_status
            FROM measurements
            {where_sql}
            ORDER BY {order_sql}
            LIMIT ${len(args)+1} OFFSET ${len(args)+2}
            """,
            *paged_args,
        )
    return {
        "ok": True, "total": total, "limit": limit, "offset": offset,
        "sort_by": sort_by, "sort_dir": direction,
        "rows": [
            {
                "time": r["time"].isoformat(), "device_id": r["device_id"],
                "site_id": r["site_id"], "quantity": r["quantity"],
                "value": r["value"], "unit": r["unit"], "depth_cm": r["depth_cm"],
                "quality_flag": r["quality_flag"],
                "received_at": r["received_at"].isoformat(),
                "latency_ms": r["latency_ms"],
                "source_kind": r["source_kind"],
                "source_file": r["source_file"],
                "validation_status": r["validation_status"],
            }
            for r in rows
        ],
    }
@router.get("/audit-log")
async def list_audit_log(
    request: Request, user: TokenPayload = Depends(require_role("viewer")),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None),
    actor_email: str | None = Query(default=None),
) -> dict:
    pool = get_db_pool(request)
    where_clauses = []
    args: list = []
    if action:
        args.append(f"%{action}%")
        where_clauses.append(f"a.action ILIKE ${len(args)}")
    if actor_email:
        args.append(f"%{actor_email}%")
        where_clauses.append(f"u.email ILIKE ${len(args)}")
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"""
            SELECT count(*) FROM audit_log a LEFT JOIN users u ON u.user_id = a.actor_user_id {where_sql}
            """,
            *args,
        )
        args_paged = [*args, limit, offset]
        rows = await conn.fetch(
            f"""
            SELECT a.id, a.action, a.target_type, a.target_id, a.old_value, a.new_value,
                   a.occurred_at, u.email AS actor_email
            FROM audit_log a
            LEFT JOIN users u ON u.user_id = a.actor_user_id
            {where_sql}
            ORDER BY a.occurred_at DESC
            LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}
            """,
            *args_paged,
        )
    return {
        "ok": True,
        "total": total,
        "limit": limit,
        "offset": offset,
        "entries": [
            {
                "id": r["id"], "action": r["action"], "target_type": r["target_type"], "target_id": r["target_id"],
                "actor_email": r["actor_email"], "occurred_at": r["occurred_at"].isoformat(),
                "old_value": r["old_value"], "new_value": r["new_value"],
            }
            for r in rows
        ],
    }

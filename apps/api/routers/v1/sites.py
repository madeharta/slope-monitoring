from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from apps.api.dependencies import get_db_pool, require_role
from common.audit import AuditLog
from common.errors import AppError, ErrorCode, NotFoundError
from common.security import TokenPayload
from services.site_service.site_repository import NewSite, SiteRepository
router = APIRouter(prefix="/api/v1/sites", tags=["sites"])
class CreateSiteRequest(BaseModel):
    site_id: str
    name: str
    lat: float
    lon: float
    force: bool = False
@router.post("")
async def create_site(
    body: CreateSiteRequest, request: Request, user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    pool = get_db_pool(request)
    repo = SiteRepository(pool)
    await repo.create(NewSite(site_id=body.site_id, name=body.name, lat=body.lat, lon=body.lon), force=body.force)
    await AuditLog(pool).record(
        actor_user_id=user.sub, action="site.create", target_type="site", target_id=body.site_id,
        new_value={"name": body.name, "lat": body.lat, "lon": body.lon},
    )
    return {"ok": True, "site_id": body.site_id}
@router.get("/nearby")
async def check_nearby(
    lat: float, lon: float, request: Request, user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    repo = SiteRepository(get_db_pool(request))
    nearby = await repo.find_nearby(lat, lon)
    return {"ok": True, "nearby": nearby}
class UpdateSiteRequest(BaseModel):
    name: str
    lat: float
    lon: float
@router.put("/{site_id}")
async def update_site(
    site_id: str, body: UpdateSiteRequest, request: Request, user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    pool = get_db_pool(request)
    await SiteRepository(pool).update(site_id, body.name, body.lat, body.lon)
    await AuditLog(pool).record(
        actor_user_id=user.sub, action="site.update", target_type="site", target_id=site_id,
        new_value={"name": body.name, "lat": body.lat, "lon": body.lon},
    )
    return {"ok": True, "site_id": site_id}
@router.delete("/{site_id}")
async def delete_site(
    site_id: str, request: Request, user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    pool = get_db_pool(request)
    device_count = await pool.fetchval("SELECT count(*) FROM devices WHERE site_id = $1", site_id)
    if device_count > 0:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"site '{site_id}' masih punya {device_count} device terdaftar — "
            f"pindahkan atau hapus device-nya dulu sebelum menghapus site ini",
        )
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO audit_log (actor_user_id, action, target_type, target_id) VALUES ($1, $2, $3, $4)",
                int(user.sub), "site.delete", "site", site_id,
            )
            result = await conn.execute("DELETE FROM sites WHERE site_id = $1", site_id)
    if result == "DELETE 0":
        raise NotFoundError("site", site_id)
    return {"ok": True}

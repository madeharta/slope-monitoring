"""Read-only operational GNSS marker endpoints. No effect on PPK references."""
from fastapi import APIRouter, Depends, Request
from apps.api.dependencies import get_db_pool, require_role
from common.security import TokenPayload

router = APIRouter(prefix='/api/v1/gnss-locations', tags=['gnss-locations'])

@router.get('')
async def list_locations(request: Request, user: TokenPayload = Depends(require_role('viewer'))):
    rows = await get_db_pool(request).fetch('''
       SELECT l.device_id, d.site_id, l.latitude, l.longitude,
              l.ellipsoidal_height_m, l.observed_at, l.calculated_at,
              l.position_source, l.quality_code, l.quality_status,
              l.accepted_solutions, l.max_spread_m, l.reference_epoch
       FROM public.gnss_device_operational_locations AS l
       JOIN public.devices AS d USING (device_id)
       ORDER BY l.device_id
    ''')
    return {'ok': True, 'locations': [dict(r) for r in rows]}

"""Versioned BASE coordinate submissions: read-only history, operator/admin append-only writes.
No activation or PPK worker binding in this phase.
"""
from __future__ import annotations
import math
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from apps.api.dependencies import get_db_pool, require_role
from common.security import TokenPayload

router = APIRouter(prefix="/api/v1/base-references", tags=["base_references"])

class SubmitReference(BaseModel):
    site_id: str = Field(min_length=1, max_length=120)
    base_device_id: str = Field(min_length=1, max_length=120)
    latitude_deg: float = Field(ge=-90, le=90)
    longitude_deg: float = Field(ge=-180, le=180)
    ellipsoidal_height_m: float
    evidence_type: Literal['PROVISIONAL_SPP', 'SURVEYED']
    effective_from: datetime
    note: str = Field(default='', max_length=2000)

    @field_validator('latitude_deg','longitude_deg','ellipsoidal_height_m')
    @classmethod
    def finite(cls,v):
        if not math.isfinite(v):
            raise ValueError('Coordinate must be finite')
        return v

    @field_validator('effective_from')
    @classmethod
    def aware(cls,v):
        if not v.tzinfo or v.utcoffset() is None:
            raise ValueError('effective_from must include UTC offset')
        return v

@router.get('/versions')
async def list_versions(request: Request, site_id: str = Query(...), base_device_id: str = Query(...), user: TokenPayload=Depends(require_role('viewer'))):
    async with get_db_pool(request).acquire() as conn:
        rows = await conn.fetch('''SELECT id,site_id,base_device_id,version_no,latitude_deg,longitude_deg,
          ellipsoidal_height_m,vertical_datum,evidence_type,validation_state,effective_from,note,created_by,created_at
          FROM public.base_reference_versions WHERE site_id=$1 AND base_device_id=$2
          ORDER BY version_no DESC LIMIT 200''',site_id,base_device_id)
    return {'ok':True,'operational_displacement_approved':False,'versions':[dict(r) for r in rows]}

@router.post('/versions', status_code=201)
async def submit_version(request: Request, body: SubmitReference, user: TokenPayload=Depends(require_role('operator'))):
    pool=get_db_pool(request)
    async with pool.acquire() as conn:
        async with conn.transaction():
            valid=await conn.fetchval('''SELECT 1 FROM public.devices WHERE device_id=$1 AND site_id=$2
               AND (UPPER(device_type) LIKE '%BASE%' OR UPPER(device_id) LIKE 'BASE%')''',body.base_device_id,body.site_id)
            if not valid:
                raise HTTPException(status_code=422,detail='BASE device/site association not found')
            await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',body.site_id+'|'+body.base_device_id)
            version_no=await conn.fetchval('''SELECT COALESCE(MAX(version_no),0)+1
               FROM public.base_reference_versions WHERE site_id=$1 AND base_device_id=$2''',body.site_id,body.base_device_id)
            row=await conn.fetchrow('''INSERT INTO public.base_reference_versions
                (site_id,base_device_id,version_no,latitude_deg,longitude_deg,ellipsoidal_height_m,
                 evidence_type,effective_from,note,created_by)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                RETURNING id,version_no,validation_state,created_at''',body.site_id,body.base_device_id,version_no,
                body.latitude_deg,body.longitude_deg,body.ellipsoidal_height_m,
                body.evidence_type,body.effective_from,body.note,user.sub)
    return {'ok':True,'id':row['id'],'version_no':row['version_no'],
      'validation_state':row['validation_state'],'operational_displacement_approved':False}

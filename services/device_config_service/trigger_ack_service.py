"""TriggerStart ACK persistence, bounded site-level correlation and rejection audit.

ACK indicates a device report, NOT proof of physical blast execution.
The wire protocol has no command identifier: same-value replay cannot be proven absent.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


def _json_integer(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    return value if type(value) is int else None


async def acknowledge_trigger_start(
    pool, *, device_id: str, trigger_start: int, device_role: str = "",
    iccid: str = "", device_version: str = "",
    device_timestamp_utc: datetime | None = None,
) -> bool:
    if type(trigger_start) is not int or trigger_start not in (0, 1):
        return False

    async with pool.acquire() as conn:
        async with conn.transaction():
            sender = await conn.fetchrow(
                "SELECT device_id, device_type, site_id FROM public.devices WHERE device_id=$1",
                device_id,
            )
            site_id = sender['site_id'] if sender else None
            reason = None
            base_id = None
            if not sender:
                reason = 'UNKNOWN_DEVICE'
            elif str(sender['device_type']).lower() not in ('base', 'rover', 'gnss_base', 'gnss_rover'):
                reason = 'INVALID_DEVICE_TYPE'
            elif str(device_role).lower() not in (
                str(sender['device_type']).lower(),
                str(sender['device_type']).lower().removeprefix('gnss_'),
            ):
                reason = 'ROLE_MISMATCH'
            else:
                # Fail closed on multiple BASE rows instead of arbitrarily assigning command ownership.
                bases = await conn.fetch("""
                    SELECT device_id FROM public.devices
                    WHERE site_id=$1 AND lower(device_type) IN ('base', 'gnss_base')
                    ORDER BY device_id
                    LIMIT 2
                """, site_id)
                if len(bases) != 1:
                    reason = 'BASE_NOT_UNIQUE' if bases else 'BASE_NOT_FOUND'
                else:
                    base_id = bases[0]['device_id']
                    if str(sender['device_type']).lower() in ('base', 'gnss_base') and device_id != base_id:
                        reason = 'NON_AUTHORITATIVE_BASE'

            active = None
            latest = None
            if reason is None:
                active = await conn.fetchrow("""
                    SELECT config_value, updated_at FROM public.device_config
                    WHERE device_id=$1 AND config_key='TriggerStart' FOR UPDATE
                """, base_id)
                if active is None or _json_integer(active['config_value']) != trigger_start:
                    reason = 'COMMAND_STATE_MISMATCH'
                else:
                    latest = await conn.fetchrow("""
                        SELECT id, config_value, created_at, acked_at
                        FROM public.device_config_pending
                        WHERE device_id=$1 AND config_key='TriggerStart'
                        ORDER BY created_at DESC, id DESC LIMIT 1 FOR UPDATE
                    """, base_id)
                    if latest is None or _json_integer(latest['config_value']) != trigger_start:
                        reason = 'NO_MATCHING_PENDING'
                    elif (active['updated_at'] is not None and
                          latest['created_at'] < active['updated_at']):
                        reason = 'STALE_PENDING'

            now = datetime.now(timezone.utc)
            if reason:
                # Rejection is an audit event, never ACK success. No FK for unknown senders.
                await conn.execute("""
                    INSERT INTO public.blast_trigger_ack_rejections
                      (device_id, site_id, base_id, trigger_start, reason_code,
                       device_timestamp_utc, server_received_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                """, device_id, site_id, base_id, trigger_start, reason,
                     device_timestamp_utc, now)
                return False

            # Only authoritative BASE ACK may mark base pending configuration delivered.
            if device_id == base_id and latest['acked_at'] is None:
                await conn.execute("""
                    UPDATE public.device_config_pending SET acked_at=$2
                    WHERE id=$1 AND acked_at IS NULL
                """, latest['id'], now)

            # Preserve existing accepted retry behavior for audit; group by device in UI.
            await conn.execute("""
                INSERT INTO public.blast_trigger_acks
                  (device_id, pending_config_id, trigger_start, received,
                   device_timestamp_utc, server_received_at, device_role, iccid, device_version)
                VALUES ($1,$2,$3,TRUE,$4,$5,$6,$7,$8)
            """, device_id, latest['id'], trigger_start, device_timestamp_utc,
                 now, device_role, iccid, device_version)
            return True

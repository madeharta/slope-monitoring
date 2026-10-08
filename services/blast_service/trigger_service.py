from __future__ import annotations
async def get_pending_command_header(pool, base_id: str) -> dict[str, str]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT command_id FROM blast_trigger_commands
            WHERE base_id = $1 AND status = 'pending'
            ORDER BY created_at ASC LIMIT 1
            """,
            base_id,
        )
    if row is None:
        return {}
    return {"X-Pending-Blast-Command-Id": str(row["command_id"])}
async def ack_command_if_present(pool, base_id: str, raw_headers: dict[str, str]) -> None:
    raw_command_id = raw_headers.get("X-Acked-Blast-Command-Id")
    if not raw_command_id:
        return
    try:
        command_id = int(raw_command_id)
    except ValueError:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE blast_trigger_commands SET status = 'executed', executed_at = now()
            WHERE command_id = $1 AND base_id = $2 AND status = 'pending'
            """,
            command_id, base_id,
        )

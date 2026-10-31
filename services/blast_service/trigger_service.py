"""Blast trigger delivery — REVISED per ITB confirmation (Lampiran A poin 1,
jawaban diterima). Original design polled a dedicated
`GET /pending-command` endpoint; ITB confirmed base does NOT need an extra
call — the command rides as a response HEADER on the periodic upload POST
that base already makes every `periodic_upload_s` (300s default).

Delivery direction: server -> base
    Base POSTs any upload (gnss.csv/position.csv, X-Device-Role: base).
    If a pending command exists for that base_id, the response carries
    `X-Pending-Blast-Command-Id: <command_id>`. Absent header = nothing
    pending. Base firmware reads this header and, if present, executes the
    physical LoRa trigger to rovers itself.

Ack direction: base -> server
    On its NEXT upload (any type), base includes request header
    `X-Acked-Blast-Command-Id: <command_id>` for the command it already
    executed. Chosen over a separate ack endpoint for the same reason as
    the trigger delivery itself — reuse the call base already makes.

Symmetry note: this makes item 8 (blast trigger) and item 9 (device config
push) use the EXACT same transport pattern — piggyback on the periodic
upload round-trip, never a bespoke device-facing endpoint. That symmetry
was not planned going in; it fell out of ITB's answer and is worth keeping
in mind if a similar "how does server tell base X" question comes up again.

Out of scope here (flagged, not designed yet): ITB also mentioned a
possible future need for triggering "via device langsung (remote
control)" — a hardware trigger path independent of the web/software flow
entirely. That is a NEW open item, not a variant of this mechanism; it
would bypass the server round-trip altogether. Not designed until ITB
scopes it further.
"""

from __future__ import annotations


async def get_pending_command_header(pool, base_id: str) -> dict[str, str]:
    """Returns {} or {"X-Pending-Blast-Command-Id": "<id>"} — merge directly
    into the response headers of any upload endpoint's success path."""
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
    """Reads X-Acked-Blast-Command-Id from an incoming upload request's
    headers, if present, and marks that command executed. Silently no-ops
    if the header is absent or the command doesn't match a pending row for
    this base — an ack for an already-executed/unknown command is not an
    error (base may retry the header on a subsequent upload before its own
    state catches up)."""
    raw_command_id = raw_headers.get("X-Acked-Blast-Command-Id")
    if not raw_command_id:
        return
    try:
        command_id = int(raw_command_id)
    except ValueError:
        return  # malformed header — ignored, not fatal to the upload itself

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE blast_trigger_commands SET status = 'executed', executed_at = now()
            WHERE command_id = $1 AND base_id = $2 AND status = 'pending'
            """,
            command_id, base_id,
        )

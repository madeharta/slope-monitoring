"""Single place where AppError becomes an HTTP response. Routers/services
never call HTTPException directly (see common/errors.py docstring) — this
is the only file that imports both AppError and FastAPI's response types.

REVISED 2026-09-19 (item 11 — reliability cleanup): earlier revisions
registered SEPARATE `@app.exception_handler(SomeType)` handlers for
asyncpg's ForeignKeyViolationError/NotNullViolationError and for
starlette's HTTPException. One of these (ModelNotImplementedError, since
replaced — see ml/registry/model_registry.py) was PROVEN via a real
server traceback to never actually get dispatched by Starlette in the
user's environment, for reasons never fully diagnosed. The ONE handler
proven reliable throughout this whole session, every time, is the
`Exception` catch-all below (its log line was the one that actually fired
in that incident). Policy going forward: anything outside the AppError
hierarchy is special-cased with a plain `isinstance()` check INSIDE this
one handler, not via a separate type registration — this does not depend
on whatever made per-type dispatch unreliable, since only ONE handler
type (`Exception`) is ever registered for non-AppError cases.
"""

from __future__ import annotations

import logging

import asyncpg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from common.errors import AppError, ErrorCode

logger = logging.getLogger("slope_monitoring.errors")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        # 5xx gets logged with a stack trace; 4xx is expected client/device
        # behaviour (bad CSV, expired token) and only logged at INFO to
        # avoid flooding logs with e.g. a device retrying a stale file.
        if exc.status_code >= 500:
            logger.exception("unhandled 5xx on %s %s", request.method, request.url.path)
        else:
            logger.info("%s on %s %s: %s", exc.code.value, request.method, request.url.path, exc.detail)
        return JSONResponse(status_code=exc.status_code, content=exc.to_envelope())

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        """Catches EVERYTHING not already an AppError — proven to reliably
        fire for arbitrary exception types (see module docstring). Checks
        the specific cases we want a nicer response for, in order, before
        falling through to the generic 500."""

        # Case 1: FastAPI's built-in HTTPBearer raises this when the
        # Authorization header is missing entirely (dependencies.py) —
        # different from an invalid/expired token (those are already
        # AppError subclasses: TokenInvalidError/TokenExpiredError).
        if isinstance(exc, HTTPException):
            logger.info("HTTPException on %s %s: %s", request.method, request.url.path, exc.detail)
            code = ErrorCode.UNAUTHENTICATED if exc.status_code in (401, 403) else ErrorCode.VALIDATION_ERROR
            return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": code.value, "detail": str(exc.detail)})

        # Case 2: FK violation — TWO genuinely different situations that
        # Postgres reports with the SAME exception class, distinguished
        # only by the wording of exc.detail (confirmed via asyncpg docs +
        # real Postgres behavior, 2026-09-21 — this was a REAL bug: a
        # single generic message was used for both, and case (b) below
        # produced a misleading message when a user tried to delete
        # BASE-01, which is still referenced by device_reference_position):
        #   (a) INSERT/UPDATE referencing something that doesn't exist —
        #       detail says "...is not present in table X." — almost
        #       always an unseeded device/site/user (Panduan Instalasi §2.3)
        #   (b) DELETE blocked because a CHILD row still references this
        #       row — detail says "...is still referenced from table X."
        #       — the row itself exists fine, it just can't be removed
        #       while dependents exist. Telling the user "it doesn't
        #       exist, check it was seeded" here is actively wrong.
        if isinstance(exc, asyncpg.exceptions.ForeignKeyViolationError):
            logger.info("FK violation on %s %s: %s", request.method, request.url.path, exc)
            detail_text = getattr(exc, "detail", "") or str(exc)
            if "is still referenced from table" in detail_text:
                blocking_table = getattr(exc, "table_name", None) or "tabel lain"
                return JSONResponse(
                    status_code=409,
                    content={
                        "ok": False, "error": "VALIDATION_ERROR",
                        "detail": f"tidak bisa dihapus — masih dirujuk oleh data di tabel '{blocking_table}'. "
                                  f"Hapus/pindahkan data terkait dulu sebelum menghapus baris ini.",
                    },
                )
            return JSONResponse(
                status_code=404,
                content={
                    "ok": False, "error": "NOT_FOUND",
                    "detail": "referenced device/site/user does not exist in the database — "
                              "check it was seeded (Panduan Instalasi & Pemakaian §2.3)",
                },
            )

        # Case 3: a NOT NULL column the code should have populated — ALWAYS
        # a server-side bug (unlike case 2), stays 500, but names the exact
        # column/table so the next report is self-diagnosing.
        if isinstance(exc, asyncpg.exceptions.NotNullViolationError):
            column = getattr(exc, "column_name", "?")
            table = getattr(exc, "table_name", "?")
            logger.exception("NOT NULL violation on %s %s (table=%s, column=%s)", request.method, request.url.path, table, column)
            return JSONResponse(
                status_code=500,
                content={
                    "ok": False, "error": ErrorCode.INTERNAL_ERROR.value,
                    "detail": f"server bug: required column left NULL (table='{table}', column='{column}') — please report this",
                },
            )

        # Last-resort catch-all: an unhandled exception must still return
        # the standard envelope, not FastAPI's default HTML/plaintext 500 —
        # a device firmware parsing every response as {"ok": ...} JSON
        # should never receive something it cannot parse.
        logger.exception("unexpected exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": ErrorCode.INTERNAL_ERROR.value, "detail": "internal server error"},
        )

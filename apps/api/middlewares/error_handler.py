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
        if exc.status_code >= 500:
            logger.exception("unhandled 5xx on %s %s", request.method, request.url.path)
        else:
            logger.info("%s on %s %s: %s", exc.code.value, request.method, request.url.path, exc.detail)
        return JSONResponse(status_code=exc.status_code, content=exc.to_envelope())
    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            logger.info("HTTPException on %s %s: %s", request.method, request.url.path, exc.detail)
            code = ErrorCode.UNAUTHENTICATED if exc.status_code in (401, 403) else ErrorCode.VALIDATION_ERROR
            return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": code.value, "detail": str(exc.detail)})
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
        logger.exception("unexpected exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": ErrorCode.INTERNAL_ERROR.value, "detail": "internal server error"},
        )

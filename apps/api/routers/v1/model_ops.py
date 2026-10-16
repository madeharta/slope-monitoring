"""Admin-only model lifecycle endpoints — blueprint §3.4 + §8.3."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from apps.api.dependencies import get_db_pool, get_model_registry, require_role
from common.audit import AuditLog
from common.errors import AppError, ErrorCode
from common.security import TokenPayload
from ml.registry.model_factory import ModelNotImplementedError, UnknownModelTypeError
from ml.registry.model_registry import ModelRegistry
from services.model_ops_service.model_version_repository import ModelVersionRepository

router = APIRouter(prefix="/api/v1/model", tags=["model_ops"])

# Matches the GCN baseline's input_contract() today; becomes per-request
# once multiple architectures with different feature counts are activated
# side by side — tracked as a follow-up, not blocking this scaffold.
_EXPECTED_N_FEATURES = 15


class ActivateRequest(BaseModel):
    version_id: str


class SwitchArchitectureRequest(BaseModel):
    model_type: str
    version_id: str


class RegisterRequest(BaseModel):
    model_type: str
    version_id: str
    artifact_path: str


def _activate_or_raise(registry: ModelRegistry, version_id: str) -> None:
    """BUG FIX (2026-09-18): `registry.activate()` can raise
    `ModelNotImplementedError`/`UnknownModelTypeError` (ml/registry/model_factory.py)
    for a registered-but-unimplemented or unknown model_type. These were
    previously left for the global `app.exception_handler(...)` registrations
    in error_handler.py to catch — confirmed via a real traceback that this
    does NOT reliably happen in this environment (leaked as a generic 500
    instead). Catching here and converting to AppError uses the ONE error
    path that has been repeatedly confirmed to work correctly throughout
    this project's testing (every AppError so far has produced the right
    envelope+status), rather than trusting framework-level dispatch for an
    arbitrary custom exception class."""
    try:
        registry.activate(version_id, expected_n_features=_EXPECTED_N_FEATURES)
    except (ModelNotImplementedError, UnknownModelTypeError) as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc


@router.post("/register")
async def register_version(
    body: RegisterRequest, request: Request, registry: ModelRegistry = Depends(get_model_registry),
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    registry.register_version(body.model_type, body.version_id, body.artifact_path)
    # BUG FIX (2026-09-19): previously only the in-memory registry was
    # updated — `model_versions` (DB table since migration 004) stayed
    # empty forever. Found while adding audit_log target validation
    # (migration 008), which would otherwise reject every model-related
    # audit entry since target_id (version_id) never existed in this table.
    await ModelVersionRepository(get_db_pool(request)).upsert_registered(
        body.model_type, body.version_id, body.artifact_path,
    )
    return {"ok": True}


@router.post("/activate")
async def activate_version(
    body: ActivateRequest, request: Request, registry: ModelRegistry = Depends(get_model_registry),
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    _activate_or_raise(registry, body.version_id)
    pool = get_db_pool(request)
    await ModelVersionRepository(pool).mark_active(body.version_id)
    await AuditLog(pool).record(
        actor_user_id=user.sub, action="model.activate", target_type="model_version", target_id=body.version_id,
    )
    return {"ok": True, "active": registry.active_summary()}


@router.post("/switch-architecture")
async def switch_architecture(
    body: SwitchArchitectureRequest, request: Request, registry: ModelRegistry = Depends(get_model_registry),
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    # §3.4 — superset of /activate: registers-then-activates a (type, version)
    # pair the caller has not necessarily registered yet.
    registry.register_version(body.model_type, body.version_id, artifact_path="")
    _activate_or_raise(registry, body.version_id)
    pool = get_db_pool(request)
    await ModelVersionRepository(pool).upsert_registered(body.model_type, body.version_id, "")
    await ModelVersionRepository(pool).mark_active(body.version_id)
    await AuditLog(pool).record(
        actor_user_id=user.sub, action="model.switch_architecture", target_type="model_version", target_id=body.version_id,
    )
    return {"ok": True, "active": registry.active_summary()}


@router.post("/rollback")
async def rollback(
    request: Request, registry: ModelRegistry = Depends(get_model_registry),
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    previous = registry.rollback()
    pool = get_db_pool(request)
    await ModelVersionRepository(pool).mark_active(previous.version_id)
    await AuditLog(pool).record(
        actor_user_id=user.sub, action="model.rollback", target_type="model_version", target_id=previous.version_id,
    )
    return {"ok": True, "active": registry.active_summary()}


@router.get("/active")
async def get_active(registry: ModelRegistry = Depends(get_model_registry)) -> dict:
    return {"ok": True, "active": registry.active_summary()}

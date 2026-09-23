from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from dingofs_platform.auth.dependencies import current_user
from .collection import begin_collection, finish_collection, abandon
from .hardware import collect
from .host_trust import trust_key
from .ssh_transport import execute, CollectionError, ERRORS

router = APIRouter(prefix="/api/v1/machines", tags=["machine-hardware"])


class RefreshInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision: int = Field(strict=True, ge=1)


@router.post("/{id}/refresh-hardware")
def refresh(
    id: str, payload: RefreshInput, request: Request, user=Depends(current_user)
):
    token, config = begin_collection(request, id, payload.base_revision)
    try:
        try:
            transport = getattr(request.app.state, "hardware_transport", execute)
            result = collect(
                config,
                transport=transport,
                timeout_s=request.app.state.settings.collection_timeout_seconds,
            )
            if result["status"] == "failed":
                result["error"] = "未能采集有效硬件信息，请检查远端工具和权限"
        except CollectionError as exc:
            result = {"status": "failed", "error": ERRORS[exc.code]}
            if exc.code in ("host_key_unknown", "host_key_changed") and exc.host_key:
                result.update(status="needs_trust", host_key=exc.host_key)
        except Exception:
            # Never return raw remote errors, configuration, or credentials.
            result = {"status": "failed", "error": "采集失败，请检查机器配置或重试"}
        return finish_collection(request, id, token, payload.base_revision, result)
    except Exception:
        abandon(request, id, token)
        raise


class TrustInput(RefreshInput):
    challenge_id: str = Field(min_length=1, max_length=80)


@router.post("/{id}/trust-host-key")
def confirm_host(
    id: str, payload: TrustInput, request: Request, user=Depends(current_user)
):
    return trust_key(request, id, payload.base_revision, payload.challenge_id)

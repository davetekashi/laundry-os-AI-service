import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.schemas.context import ContextRole, ContextSnapshot
from app.schemas.scope import ScopeIdentifiers
from app.services.context_cache import (
    get_context,
    restore_context,
    snapshot_scope_key,
)
from app.services.conversation_cache import get_conversation, restore_conversation


router = APIRouter(prefix="/_cloudflare/runtime-state", include_in_schema=False)


class RuntimeScopeRequest(ScopeIdentifiers):
    role: ContextRole


class ConversationRequest(BaseModel):
    conversation_id: str


class ConversationStatePayload(BaseModel):
    conversation_id: str
    scope_key: str
    role: ContextRole
    messages: list[dict[str, str]]


def _authorize(x_runtime_state_token: str | None) -> None:
    expected = os.environ.get("RUNTIME_STATE_TOKEN")
    if not expected or x_runtime_state_token != expected:
        raise HTTPException(status_code=404, detail="Not found.")


@router.post("/context/has")
def has_context(
    payload: RuntimeScopeRequest,
    x_runtime_state_token: str | None = Header(default=None),
) -> dict[str, bool]:
    _authorize(x_runtime_state_token)
    return {
        "exists": get_context(
            payload.laundry_id,
            payload.role,
            payload.business_id,
        )
        is not None
    }


@router.post("/context/export")
def export_context(
    payload: RuntimeScopeRequest,
    x_runtime_state_token: str | None = Header(default=None),
) -> dict:
    _authorize(x_runtime_state_token)
    snapshot = get_context(
        payload.laundry_id,
        payload.role,
        payload.business_id,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Prepared context not found.")
    return {
        "scope_key": snapshot_scope_key(snapshot),
        "snapshot": snapshot.model_dump(mode="json"),
    }


@router.post("/context/import")
def import_context(
    payload: ContextSnapshot,
    x_runtime_state_token: str | None = Header(default=None),
) -> dict[str, bool]:
    _authorize(x_runtime_state_token)
    restore_context(payload.model_dump(mode="json"))
    return {"success": True}


@router.post("/conversation/has")
def has_conversation(
    payload: ConversationRequest,
    x_runtime_state_token: str | None = Header(default=None),
) -> dict[str, bool]:
    _authorize(x_runtime_state_token)
    return {"exists": get_conversation(payload.conversation_id) is not None}


@router.post("/conversation/export")
def export_conversation(
    payload: ConversationRequest,
    x_runtime_state_token: str | None = Header(default=None),
) -> ConversationStatePayload:
    _authorize(x_runtime_state_token)
    state = get_conversation(payload.conversation_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return ConversationStatePayload(
        conversation_id=state.conversation_id,
        scope_key=state.scope_key,
        role=state.role,
        messages=state.messages,
    )


@router.post("/conversation/import")
def import_conversation(
    payload: ConversationStatePayload,
    x_runtime_state_token: str | None = Header(default=None),
) -> dict[str, bool]:
    _authorize(x_runtime_state_token)
    try:
        restore_conversation(payload.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True}

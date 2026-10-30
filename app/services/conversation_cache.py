from dataclasses import dataclass, field
from threading import RLock
from uuid import uuid4

from app.schemas.context import ContextRole


MAX_HISTORY_MESSAGES = 40


@dataclass
class ConversationState:
    conversation_id: str
    scope_key: str
    role: ContextRole
    messages: list[dict[str, str]] = field(default_factory=list)


_CONVERSATION_CACHE: dict[str, ConversationState] = {}
_CONVERSATION_LOCK = RLock()


def load_conversation(
    conversation_id: str | None,
    scope_key: str,
    role: ContextRole,
) -> tuple[str, list[dict[str, str]]]:
    resolved_id = conversation_id or str(uuid4())
    with _CONVERSATION_LOCK:
        state = _CONVERSATION_CACHE.get(resolved_id)
        if state is None:
            state = ConversationState(
                conversation_id=resolved_id,
                scope_key=scope_key,
                role=role,
            )
            _CONVERSATION_CACHE[resolved_id] = state
        elif state.scope_key != scope_key or state.role != role:
            raise ValueError(
                "conversation_id belongs to a different business scope or role."
            )
        return resolved_id, [dict(message) for message in state.messages]


def append_exchange(
    conversation_id: str,
    user_message: str,
    assistant_message: str,
) -> None:
    with _CONVERSATION_LOCK:
        state = _CONVERSATION_CACHE.get(conversation_id)
        if state is None:
            raise ValueError("Conversation was not initialized.")
        state.messages.extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ]
        )
        if len(state.messages) > MAX_HISTORY_MESSAGES:
            state.messages = state.messages[-MAX_HISTORY_MESSAGES:]


def clear_scope_conversations(scope_key: str, role: ContextRole) -> None:
    with _CONVERSATION_LOCK:
        stale_ids = [
            conversation_id
            for conversation_id, state in _CONVERSATION_CACHE.items()
            if state.scope_key == scope_key and state.role == role
        ]
        for conversation_id in stale_ids:
            del _CONVERSATION_CACHE[conversation_id]


def get_conversation(conversation_id: str) -> ConversationState | None:
    with _CONVERSATION_LOCK:
        state = _CONVERSATION_CACHE.get(conversation_id)
        if state is None:
            return None
        return ConversationState(
            conversation_id=state.conversation_id,
            scope_key=state.scope_key,
            role=state.role,
            messages=[dict(message) for message in state.messages],
        )


def restore_conversation(state_data: dict) -> ConversationState:
    state = ConversationState(
        conversation_id=str(state_data["conversation_id"]),
        scope_key=str(state_data["scope_key"]),
        role=ContextRole(state_data["role"]),
        messages=[dict(message) for message in state_data.get("messages", [])],
    )
    if len(state.messages) > MAX_HISTORY_MESSAGES:
        state.messages = state.messages[-MAX_HISTORY_MESSAGES:]
    with _CONVERSATION_LOCK:
        existing = _CONVERSATION_CACHE.get(state.conversation_id)
        if existing is not None and (
            existing.scope_key != state.scope_key or existing.role != state.role
        ):
            raise ValueError(
                "conversation_id belongs to a different business scope or role."
            )
        _CONVERSATION_CACHE[state.conversation_id] = state
    return state

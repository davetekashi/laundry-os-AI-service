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

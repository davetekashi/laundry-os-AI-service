from app.schemas.context import ContextRole, ContextSnapshot


_CONTEXT_CACHE: dict[tuple[str, ContextRole], ContextSnapshot] = {}


def set_context(snapshot: ContextSnapshot) -> None:
    _CONTEXT_CACHE[(snapshot.laundry_id, snapshot.role)] = snapshot


def get_context(laundry_id: str, role: ContextRole) -> ContextSnapshot | None:
    return _CONTEXT_CACHE.get((laundry_id, role))

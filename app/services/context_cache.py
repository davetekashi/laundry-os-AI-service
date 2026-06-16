from app.schemas.context import ContextSnapshot


_CONTEXT_CACHE: dict[str, ContextSnapshot] = {}


def set_context(snapshot: ContextSnapshot) -> None:
    _CONTEXT_CACHE[snapshot.laundry_id] = snapshot


def get_context(laundry_id: str) -> ContextSnapshot | None:
    return _CONTEXT_CACHE.get(laundry_id)

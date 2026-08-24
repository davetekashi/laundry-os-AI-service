from app.schemas.context import ContextRole, ContextSnapshot


_CONTEXT_CACHE: dict[tuple[str, ContextRole], ContextSnapshot] = {}


def _laundry_key(laundry_id: str) -> str:
    return f"laundry:{laundry_id}"


def _business_key(business_id: str) -> str:
    return f"business:{business_id}"


def set_context(snapshot: ContextSnapshot) -> None:
    _CONTEXT_CACHE[(_laundry_key(snapshot.laundry_id), snapshot.role)] = snapshot
    if snapshot.business_id and not snapshot.branch_id:
        _CONTEXT_CACHE[(_business_key(snapshot.business_id), snapshot.role)] = snapshot
    if snapshot.cache_key:
        _CONTEXT_CACHE[(snapshot.cache_key, snapshot.role)] = snapshot


def get_context(
    laundry_id: str | None,
    role: ContextRole,
    business_id: str | None = None,
) -> ContextSnapshot | None:
    snapshots: list[ContextSnapshot] = []
    if laundry_id:
        snapshot = _CONTEXT_CACHE.get((_laundry_key(laundry_id), role))
        if snapshot:
            snapshots.append(snapshot)
    if business_id:
        snapshot = _CONTEXT_CACHE.get((_business_key(business_id), role))
        if snapshot:
            snapshots.append(snapshot)
    if not snapshots:
        return None
    first = snapshots[0]
    if any(snapshot is not first for snapshot in snapshots[1:]):
        return None
    if laundry_id and first.laundry_id != laundry_id:
        return None
    if business_id and first.business_id != business_id:
        return None
    return first

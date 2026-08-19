from dataclasses import dataclass

from bson import ObjectId


@dataclass(frozen=True)
class ResolvedScope:
    laundry_id: ObjectId
    business_id: ObjectId | None
    branch_ids: tuple[ObjectId, ...]
    laundry: dict
    business: dict | None

    @property
    def mode(self) -> str:
        return "migrated" if self.business_id else "legacy"

    @property
    def cache_key(self) -> str:
        if self.business_id:
            return f"business:{self.business_id}"
        return f"laundry:{self.laundry_id}"


def _object_id(value: str | None, field_name: str) -> ObjectId | None:
    if value is None:
        return None
    try:
        return ObjectId(value)
    except Exception as exc:
        raise ValueError(f"Invalid {field_name} format.") from exc


def resolve_scope(
    db,
    laundry_id: str | None,
    business_id: str | None,
) -> ResolvedScope:
    if not laundry_id and not business_id:
        raise ValueError("At least one of laundry_id or business_id is required.")

    laundry_object_id = _object_id(laundry_id, "laundry_id")
    business_object_id = _object_id(business_id, "business_id")
    laundry = (
        db.laundries.find_one({"_id": laundry_object_id})
        if laundry_object_id
        else None
    )
    business = (
        db.laundrybusinesses.find_one({"_id": business_object_id})
        if business_object_id
        else None
    )

    if laundry_object_id and not laundry:
        raise ValueError("Laundry not found.")
    if business_object_id and not business:
        raise ValueError("Business not found.")

    if business:
        linked_laundry_id = business.get("legacyLaundryId")
        if not isinstance(linked_laundry_id, ObjectId):
            raise ValueError("Business is not linked to a legacy laundry.")
        if laundry_object_id and linked_laundry_id != laundry_object_id:
            raise ValueError("laundry_id and business_id do not belong together.")
        laundry_object_id = linked_laundry_id
        if laundry is None:
            laundry = db.laundries.find_one({"_id": laundry_object_id})
            if not laundry:
                raise ValueError("The business's linked legacy laundry was not found.")
    elif laundry_object_id:
        business = db.laundrybusinesses.find_one(
            {"legacyLaundryId": laundry_object_id}
        )
        if business:
            business_object_id = business["_id"]

    branch_ids: tuple[ObjectId, ...] = ()
    if business_object_id:
        branch_ids = tuple(
            document["_id"]
            for document in db.branches.find(
                {"businessId": business_object_id},
                {"_id": 1},
            )
        )

    return ResolvedScope(
        laundry_id=laundry_object_id,
        business_id=business_object_id,
        branch_ids=branch_ids,
        laundry=laundry,
        business=business,
    )

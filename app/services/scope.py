from dataclasses import dataclass

from bson import ObjectId


@dataclass(frozen=True)
class ResolvedScope:
    laundry_id: ObjectId
    business_id: ObjectId | None
    laundry: dict
    business: dict | None
    branch_id: ObjectId | None = None
    branch_ids: tuple[ObjectId, ...] = ()
    legacy_laundry_ids: tuple[ObjectId, ...] = ()
    branches: tuple[dict, ...] = ()

    @property
    def mode(self) -> str:
        return "migrated" if self.business_id else "legacy"

    @property
    def is_branch_scoped(self) -> bool:
        return self.branch_id is not None

    @property
    def is_business_wide(self) -> bool:
        return self.business_id is not None and self.branch_id is None

    @property
    def cache_key(self) -> str:
        if self.branch_id:
            return f"branch:{self.branch_id}"
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


def scope_order_query(scope: ResolvedScope, extra: dict | None = None) -> dict:
    if scope.business_id and scope.branch_id:
        identity_query: dict = {
            "$or": [
                {"businessId": scope.business_id, "branchId": scope.branch_id},
                {"laundryId": scope.laundry_id},
            ]
        }
    elif scope.business_id:
        identities = list(scope.legacy_laundry_ids) or [scope.laundry_id]
        identity_query = {
            "$or": [
                {"businessId": scope.business_id},
                {"laundryId": {"$in": identities}},
            ]
        }
    else:
        identity_query = {"laundryId": scope.laundry_id}

    if extra:
        return {"$and": [identity_query, extra]}
    return identity_query


def scope_legacy_query(scope: ResolvedScope) -> dict:
    if scope.is_business_wide:
        laundry_ids = list(scope.legacy_laundry_ids) or [scope.laundry_id]
        return {"laundryId": {"$in": laundry_ids}}
    return {"laundryId": scope.laundry_id}


def resolve_scope(db, laundry_id: str | None, business_id: str | None) -> ResolvedScope:
    if not laundry_id and not business_id:
        raise ValueError("At least one of laundry_id or business_id is required.")

    requested_laundry_id = _object_id(laundry_id, "laundry_id")
    branch_requested = requested_laundry_id is not None
    business_object_id = _object_id(business_id, "business_id")
    laundry = (
        db.laundries.find_one({"_id": requested_laundry_id})
        if requested_laundry_id
        else None
    )
    business = (
        db.laundrybusinesses.find_one({"_id": business_object_id})
        if business_object_id
        else None
    )

    if requested_laundry_id and not laundry:
        raise ValueError("Laundry not found.")
    if business_object_id and not business:
        raise ValueError("Business not found.")

    branch = None
    if business:
        primary_laundry_id = business.get("legacyLaundryId")
        if requested_laundry_id:
            branch = db.branches.find_one(
                {
                    "businessId": business_object_id,
                    "legacyLaundryId": requested_laundry_id,
                }
            )
            if requested_laundry_id != primary_laundry_id and not branch:
                raise ValueError("laundry_id and business_id do not belong together.")
        else:
            if not isinstance(primary_laundry_id, ObjectId):
                raise ValueError("Business is not linked to a legacy laundry.")
            requested_laundry_id = primary_laundry_id
            laundry = db.laundries.find_one({"_id": requested_laundry_id})
            if not laundry:
                raise ValueError("The business's linked legacy laundry was not found.")
    elif requested_laundry_id:
        business = db.laundrybusinesses.find_one(
            {"legacyLaundryId": requested_laundry_id}
        )
        if business:
            business_object_id = business["_id"]
            branch = db.branches.find_one(
                {
                    "businessId": business_object_id,
                    "legacyLaundryId": requested_laundry_id,
                }
            )
        else:
            branch = db.branches.find_one({"legacyLaundryId": requested_laundry_id})
            if branch:
                business_object_id = branch.get("businessId")
                business = db.laundrybusinesses.find_one({"_id": business_object_id})
                if not business:
                    raise ValueError("The branch's business was not found.")

    branch_documents: list[dict] = []
    if business_object_id:
        branch_documents = list(
            db.branches.find(
                {"businessId": business_object_id},
                {
                    "_id": 1,
                    "legacyLaundryId": 1,
                    "name": 1,
                    "branchName": 1,
                    "code": 1,
                    "status": 1,
                    "isActive": 1,
                    "isPrimary": 1,
                    "createdAt": 1,
                },
            )
        )
        if branch_requested and requested_laundry_id and branch is None:
            branch = next(
                (
                    document
                    for document in branch_documents
                    if document.get("legacyLaundryId") == requested_laundry_id
                ),
                None,
            )

    branch_ids = tuple(
        document["_id"]
        for document in branch_documents
        if isinstance(document.get("_id"), ObjectId)
    )
    legacy_laundry_ids = tuple(
        dict.fromkeys(
            value
            for value in (
                business.get("legacyLaundryId") if business else None,
                *(document.get("legacyLaundryId") for document in branch_documents),
            )
            if isinstance(value, ObjectId)
        )
    )

    return ResolvedScope(
        laundry_id=requested_laundry_id,
        business_id=business_object_id,
        laundry=laundry,
        business=business,
        branch_id=branch.get("_id") if branch else None,
        branch_ids=branch_ids,
        legacy_laundry_ids=legacy_laundry_ids,
        branches=tuple(branch_documents),
    )

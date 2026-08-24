from fastapi import APIRouter, HTTPException

from app.schemas.context import PrepareContextRequest, PrepareContextResponse
from app.services.context_preparation import (
    ContextPreparationError,
    prepare_laundry_context,
)


router = APIRouter(tags=["context"])


@router.post(
    "/context/prepare",
    response_model=PrepareContextResponse,
    summary="Prepare and cache sanitized AI context for a laundry",
    description=(
        "Builds sanitized, role-scoped AI-ready business context and stores it in memory. "
        "This endpoint is intended to be triggered by the backend when a laundry user logs in so that "
        "subsequent chat calls can be faster.\n\n"
        "Identity: send `laundry_id`, `business_id`, or both. At least one is required. For a migrated "
        "business, a branch's `laundry_id` resolves its branch. If both ids are supplied, any branch belonging to "
        "that business is accepted; unrelated ids are rejected. Sending only `business_id` creates business-wide "
        "context. An older laundry with no business record continues in `legacy` mode.\n\n"
        "Send `role` as `owner`, `business_manager`, or `staff`. The backend must derive this value from the authenticated "
        "user and must not accept a user-selected role. Owner and business-manager context includes operational, collection, debt, "
        "wallet, expense, settlement and reconciliation information. Staff context contains only operational "
        "laundry, customer, member, order, logistics and catalog information. Staff payment visibility is limited "
        "to the order-level payment status already present on orders; order payment events and amounts are not fetched.\n\n"
        "Snapshots are cached separately by branch and role. `/chat` should send the same identifiers and role used "
        "for preparation; this prevents one branch from reading another branch's prepared context.\n\n"
        "Important: prepared context is stored in memory only and is cleared whenever this service restarts."
    ),
    responses={
        400: {
            "description": "Invalid scope id, unknown business/laundry, or mismatched ids.",
            "content": {
                "application/json": {
                    "example": {"detail": "Laundry not found."}
                }
            },
        },
        500: {
            "description": "Unexpected server-side failure while building context.",
            "content": {
                "application/json": {
                    "example": {"detail": "Failed to prepare context."}
                }
            },
        },
    },
)
def prepare_context_endpoint(payload: PrepareContextRequest) -> PrepareContextResponse:
    try:
        return prepare_laundry_context(
            payload.laundry_id,
            payload.role,
            payload.business_id,
        )
    except ContextPreparationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to prepare context.") from exc

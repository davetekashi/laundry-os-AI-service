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
        "Builds sanitized, role-scoped AI-ready business context for a specific laundry and stores it in memory. "
        "This endpoint is intended to be triggered by the backend when a laundry user logs in so that "
        "subsequent chat calls can be faster.\n\n"
        "Send `role` as either `owner` or `staff`. The backend must derive this value from the authenticated "
        "user and must not accept a user-selected role. Owner context includes operational, collection, debt, "
        "wallet, expense, settlement and reconciliation information. Staff context contains only operational "
        "laundry, customer, member, order, logistics and catalog information. Staff payment visibility is limited "
        "to the order-level payment status already present on orders; order payment events and amounts are not fetched.\n\n"
        "Owner and staff snapshots are cached separately using the laundry id and role. The subsequent `/chat` "
        "request must provide the same role.\n\n"
        "Important: prepared context is stored in memory only and is cleared whenever this service restarts."
    ),
    responses={
        400: {
            "description": "Invalid laundry id or laundry not found.",
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
        return prepare_laundry_context(payload.laundry_id, payload.role)
    except ContextPreparationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to prepare context.") from exc

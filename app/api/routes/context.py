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
        "Builds sanitized, AI-ready business context for a specific laundry and stores it in memory. "
        "This endpoint is intended to be triggered by the backend when a laundry user logs in so that "
        "subsequent chat calls can be faster.\n\n"
        "The prepared context includes summarized data derived from laundries, bank accounts, wallets, "
        "customers, debts, members, customer payments, orders, and logistics job records.\n\n"
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
        return prepare_laundry_context(payload.laundry_id)
    except ContextPreparationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to prepare context.") from exc

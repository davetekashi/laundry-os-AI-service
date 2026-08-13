from fastapi import APIRouter, HTTPException

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat import ChatServiceError, answer_laundry_question


router = APIRouter(tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Chat with Anne using prepared laundry context and general management knowledge",
    description=(
        "Answers a natural-language message as Anne, the Seanosis AI Manager. Facts about the specific "
        "laundry are grounded in the matching laundry-and-role context previously prepared via "
        "`POST /api/v1/context/prepare`. Anne may also use general knowledge for conversation, explanations, "
        "brainstorming, and laundry-management guidance, but does not present that guidance as known facts "
        "about the laundry.\n\n"
        "This endpoint does not build context on demand. If no prepared context exists in memory for the "
        "provided `laundry_id` and `role`, the request will fail and the backend should call `/context/prepare` "
        "first. The backend must send the authenticated role, not a role selected by the frontend. Staff answers "
        "cannot access owner-only financial information because it is absent from the staff snapshot."
    ),
    responses={
        400: {
            "description": "Prepared context missing or request-level chat failure.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Context for this laundry and role 'staff' has not been prepared."
                    }
                }
            },
        },
        500: {
            "description": "Unexpected server-side failure while answering the chat request.",
            "content": {
                "application/json": {
                    "example": {"detail": "Failed to answer chat message."}
                }
            },
        },
    },
)
def chat_endpoint(payload: ChatRequest) -> ChatResponse:
    try:
        return answer_laundry_question(payload.laundry_id, payload.role, payload.message)
    except ChatServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to answer chat message.") from exc

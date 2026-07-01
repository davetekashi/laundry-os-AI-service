from fastapi import APIRouter, HTTPException

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat import ChatServiceError, answer_laundry_question


router = APIRouter(tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Answer a laundry question using in-memory prepared contextual information about the laundry",
    description=(
        "Answers a natural-language question about a laundry business using only the laundry context "
        "previously prepared via `POST /api/v1/context/prepare`.\n\n"
        "This endpoint does not build context on demand. If no prepared context exists in memory for the "
        "provided `laundry_id`, the request will fail and the backend should call `/context/prepare` first."
    ),
    responses={
        400: {
            "description": "Prepared context missing or request-level chat failure.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Context for this laundry has not been prepared."
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
        return answer_laundry_question(payload.laundry_id, payload.message)
    except ChatServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to answer chat message.") from exc

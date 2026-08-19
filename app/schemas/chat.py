from pydantic import BaseModel, Field

from app.schemas.context import ContextRole
from app.schemas.scope import ScopeIdentifiers


class ChatRequest(ScopeIdentifiers):
    role: ContextRole = Field(
        description="Authenticated role used to retrieve the matching isolated context snapshot.",
        examples=["staff"],
    )
    message: str = Field(
        min_length=1,
        description=(
            "Natural-language message for Anne. Laundry-specific claims are grounded in prepared context; "
            "general conversation and management guidance may use Anne's broader knowledge."
        ),
        examples=["Give me a summary of my laundry business right now."],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "laundry_id": "6a54b1f08898ecb11ff0068f",
                "business_id": "6a8496025e553211a5ecc1dd",
                "role": "owner",
                "message": "Give me a summary of my laundry business right now."
            }
        }
    }


class ChatResponse(BaseModel):
    success: bool = Field(
        default=True,
        description="Whether the chat request completed successfully.",
    )
    laundry_id: str = Field(
        description="Laundry id whose prepared context was used to answer the question.",
        examples=["6a54b1f08898ecb11ff0068f"],
    )
    business_id: str | None = Field(
        default=None,
        description="Resolved migrated business id, or null for a legacy-only laundry.",
    )
    scope_mode: str = Field(
        description="Resolved data mode used by the prepared context.",
        examples=["migrated"],
    )
    role: ContextRole = Field(
        description="Role of the prepared context used for this answer.",
        examples=["staff"],
    )
    prepared_at: str = Field(
        description="UTC timestamp of the prepared context snapshot used for this chat answer.",
        examples=["2026-06-16T13:23:36.218984+00:00"],
    )
    answer: str = Field(
        description=(
            "Anne's answer. Laundry-specific facts are grounded in prepared context, while general advice "
            "and conversation may draw on broader knowledge without being represented as laundry facts."
        ),
        examples=["Your laundry currently has 7 orders, 15 payments, 3 customers, and 18 debt records."],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "laundry_id": "6a54b1f08898ecb11ff0068f",
                "business_id": "6a8496025e553211a5ecc1dd",
                "scope_mode": "migrated",
                "role": "owner",
                "prepared_at": "2026-06-16T13:23:36.218984+00:00",
                "answer": "Your laundry currently has 7 orders and 3 customers. Two orders are awaiting delivery."
            }
        }
    }

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    laundry_id: str = Field(
        min_length=1,
        description="MongoDB ObjectId string for a laundry whose context has already been prepared in memory.",
        examples=["6a18a4e625addd1b6e2406b7"],
    )
    message: str = Field(
        min_length=1,
        description="Natural-language business question to answer using prepared laundry context only.",
        examples=["Give me a summary of my laundry business right now."],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "laundry_id": "6a18a4e625addd1b6e2406b7",
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
        examples=["6a18a4e625addd1b6e2406b7"],
    )
    prepared_at: str = Field(
        description="UTC timestamp of the prepared context snapshot used for this chat answer.",
        examples=["2026-06-16T13:23:36.218984+00:00"],
    )
    answer: str = Field(
        description="Model-generated answer grounded only in the prepared laundry context.",
        examples=["Your laundry currently has 7 orders, 15 payments, 3 customers, and 18 debt records."],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "laundry_id": "6a18a4e625addd1b6e2406b7",
                "prepared_at": "2026-06-16T13:23:36.218984+00:00",
                "answer": "Your laundry currently has 7 orders, 15 payments, 3 customers, and 18 debt records."
            }
        }
    }

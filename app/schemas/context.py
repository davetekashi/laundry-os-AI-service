from pydantic import BaseModel, Field


class PrepareContextRequest(BaseModel):
    laundry_id: str = Field(
        min_length=1,
        description="MongoDB ObjectId string for the laundry whose business context should be prepared.",
        examples=["6a18a4e625addd1b6e2406b7"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "laundry_id": "6a18a4e625addd1b6e2406b7"
            }
        }
    }


class ContextSnapshot(BaseModel):
    laundry_id: str
    prepared_at: str
    context: dict


class PrepareContextResponse(BaseModel):
    success: bool = Field(
        default=True,
        description="Whether the context preparation completed successfully.",
    )
    laundry_id: str = Field(
        description="Laundry id whose context was prepared and cached in memory.",
        examples=["6a18a4e625addd1b6e2406b7"],
    )
    prepared_at: str = Field(
        description="UTC timestamp when the in-memory context snapshot was generated.",
        examples=["2026-06-16T13:23:36.218984+00:00"],
    )
    summary: dict = Field(
        description="Quick summary of the prepared context for backend confirmation and debugging.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "laundry_id": "6a18a4e625addd1b6e2406b7",
                "prepared_at": "2026-06-16T13:23:36.218984+00:00",
                "summary": {
                    "laundry_name": "Royalty",
                    "total_customers": 3,
                    "total_orders": 7,
                    "total_payments": 15,
                    "total_debt_records": 18,
                },
            }
        }
    }

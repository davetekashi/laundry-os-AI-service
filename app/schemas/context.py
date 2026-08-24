from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.scope import ScopeIdentifiers


class ContextRole(StrEnum):
    OWNER = "owner"
    BUSINESS_MANAGER = "business_manager"
    STAFF = "staff"

    @property
    def has_financial_access(self) -> bool:
        return self in {self.OWNER, self.BUSINESS_MANAGER}


class PrepareContextRequest(ScopeIdentifiers):
    role: ContextRole = Field(
        description="Authenticated laundry user's role. The backend must derive this value from the user's session.",
        examples=["owner"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "laundry_id": "6a54b1f08898ecb11ff0068f",
                "business_id": "6a8496025e553211a5ecc1dd",
                "role": "owner",
            }
        }
    }


class ContextSnapshot(BaseModel):
    laundry_id: str
    business_id: str | None = None
    branch_id: str | None = None
    scope_mode: str = "legacy"
    cache_key: str | None = None
    role: ContextRole
    prepared_at: str
    context: dict


class PrepareContextResponse(BaseModel):
    success: bool = Field(
        default=True,
        description="Whether the context preparation completed successfully.",
    )
    laundry_id: str = Field(
        description="Laundry id whose context was prepared and cached in memory.",
        examples=["6a54b1f08898ecb11ff0068f"],
    )
    business_id: str | None = Field(
        default=None,
        description="Resolved migrated business id, or null for a legacy-only laundry.",
    )
    branch_id: str | None = Field(
        default=None,
        description="Resolved branch id when a branch laundry_id was supplied.",
    )
    scope_mode: str = Field(
        description="Resolved data mode: `legacy` or `migrated`.",
        examples=["migrated"],
    )
    role: ContextRole = Field(
        description="Role whose isolated context was prepared.",
        examples=["owner"],
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
                "laundry_id": "6a54b1f08898ecb11ff0068f",
                "business_id": "6a8496025e553211a5ecc1dd",
                "scope_mode": "migrated",
                "role": "owner",
                "prepared_at": "2026-06-16T13:23:36.218984+00:00",
                "summary": {
                    "laundry_name": "Protek Premium",
                    "total_customers": 3,
                    "total_orders": 7,
                    "total_payment_events": 15,
                    "total_debt_records": 18,
                },
            }
        }
    }

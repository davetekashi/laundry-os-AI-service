from pydantic import BaseModel, Field, model_validator


class ScopeIdentifiers(BaseModel):
    laundry_id: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Legacy laundry MongoDB ObjectId. Required when business_id is omitted."
        ),
        examples=["6a18a4e625addd1b6e2406b7"],
    )
    business_id: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Migrated laundry-business MongoDB ObjectId. Required when laundry_id is omitted."
        ),
        examples=["6b18a4e625addd1b6e2406b8"],
    )

    @model_validator(mode="after")
    def validate_scope_identifiers(self):
        if not self.laundry_id and not self.business_id:
            raise ValueError("At least one of laundry_id or business_id is required.")
        return self

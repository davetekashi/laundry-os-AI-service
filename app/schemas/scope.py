from pydantic import BaseModel, Field, field_validator, model_validator


class ScopeIdentifiers(BaseModel):
    laundry_id: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Legacy laundry MongoDB ObjectId. For migrated multi-branch businesses, this identifies the specific branch."
        ),
        examples=["6a18a4e625addd1b6e2406b7"],
    )
    business_id: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Migrated laundry-business MongoDB ObjectId. When sent alone, the request is business-wide."
        ),
        examples=["6b18a4e625addd1b6e2406b8"],
    )

    @field_validator("laundry_id", "business_id", mode="before")
    @classmethod
    def normalize_optional_identifier(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and value.strip().casefold() in {
            "",
            "null",
            "none",
            "undefined",
        }:
            return None
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_scope_identifiers(self):
        if not self.laundry_id and not self.business_id:
            raise ValueError("At least one of laundry_id or business_id is required.")
        return self

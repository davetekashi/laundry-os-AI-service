from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class RetrievalDomain(StrEnum):
    CUSTOMERS = "customers"
    ORDERS = "orders"
    MEMBERS = "members"
    LOGISTICS = "logistics"
    PAYMENTS = "payments"
    EXPENSES = "expenses"
    DEBTS = "debts"
    SETTLEMENTS = "settlements"


class RetrievalOperation(StrEnum):
    LIST = "list"
    SEARCH = "search"
    PERIOD_ANALYSIS = "period_analysis"
    COMPARISON = "comparison"


class RetrievalQuery(BaseModel):
    domains: list[RetrievalDomain] = Field(min_length=1, max_length=8)
    operation: RetrievalOperation
    start_date: str | None = None
    end_date: str | None = None
    comparison_start_date: str | None = None
    comparison_end_date: str | None = None
    search_text: str | None = None
    statuses: list[str] = Field(default_factory=list, max_length=20)
    sort_by: str = "date"
    sort_order: str = "descending"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=250)

    @model_validator(mode="after")
    def validate_ranges(self):
        if bool(self.start_date) != bool(self.end_date):
            raise ValueError("start_date and end_date must be supplied together.")
        if bool(self.comparison_start_date) != bool(self.comparison_end_date):
            raise ValueError(
                "comparison_start_date and comparison_end_date must be supplied together."
            )
        if self.operation == RetrievalOperation.COMPARISON and not (
            self.start_date and self.comparison_start_date
        ):
            raise ValueError("Comparison queries require both date ranges.")
        return self

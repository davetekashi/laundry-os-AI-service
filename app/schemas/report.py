from datetime import datetime

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class WeeklySummaryReportRequest(BaseModel):
    laundry_id: str = Field(
        min_length=1,
        description="MongoDB ObjectId string for the laundry whose report should be generated.",
        examples=["6a18a4e625addd1b6e2406b7"],
    )
    start_date: datetime = Field(
        description="Inclusive report window start in ISO 8601 format.",
        examples=["2026-06-09T00:00:00Z"],
    )
    end_date: datetime = Field(
        description="Inclusive report window end in ISO 8601 format.",
        examples=["2026-06-16T23:59:59Z"],
    )

    @field_validator("end_date")
    @classmethod
    def validate_date_range(cls, value: datetime, info):
        start_date = info.data.get("start_date")
        if start_date and value <= start_date:
            raise ValueError("end_date must be greater than start_date.")
        return value

    model_config = {
        "json_schema_extra": {
            "example": {
                "laundry_id": "6a18a4e625addd1b6e2406b7",
                "start_date": "2026-06-09T00:00:00Z",
                "end_date": "2026-06-16T23:59:59Z",
            }
        }
    }


class WeeklySummaryReportResponse(BaseModel):
    success: bool = Field(
        default=True,
        description="Whether the weekly summary report was generated successfully.",
    )
    laundry_id: str = Field(
        description="Laundry id used for report generation.",
        examples=["6a18a4e625addd1b6e2406b7"],
    )
    start_date: str = Field(
        description="Inclusive ISO 8601 report window start used for the query.",
        examples=["2026-06-09T00:00:00+00:00"],
    )
    end_date: str = Field(
        description="Inclusive ISO 8601 report window end used for the query.",
        examples=["2026-06-16T23:59:59+00:00"],
    )
    summary: str = Field(
        description="Plain-text weekly business summary ready for insertion into a document on the backend.",
        examples=[
            "Royalty had an active week with 7 orders worth NGN 145,000 in total. Payments received during the period came to NGN 120,000, while 3 debt records remained outstanding with a combined balance of NGN 25,000."
        ],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "laundry_id": "6a18a4e625addd1b6e2406b7",
                "start_date": "2026-06-09T00:00:00+00:00",
                "end_date": "2026-06-16T23:59:59+00:00",
                "summary": "Royalty had an active week with 7 orders worth NGN 145,000 in total. Payments received during the period came to NGN 120,000, while 3 debt records remained outstanding with a combined balance of NGN 25,000.",
            }
        }
    }


class ReportTable(BaseModel):
    headers: list[str] = Field(
        description="Table column headers in display order.",
        examples=[["Customer", "Debt Owed", "Time Frame"]],
    )
    rows: list[list[str | int | float]] = Field(
        description="Table rows in display order.",
        examples=[[["John Doe", "NGN 25,000", "9 days outstanding"]]],
    )


class DebtRiskAnalysisRequest(BaseModel):
    laundry_id: str = Field(
        min_length=1,
        description="MongoDB ObjectId string for the laundry whose current debt-risk report should be generated.",
        examples=["6a18a4e625addd1b6e2406b7"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "laundry_id": "6a18a4e625addd1b6e2406b7"
            }
        }
    }


class DebtRiskAnalysisResponse(BaseModel):
    success: bool = Field(
        default=True,
        description="Whether the debt risk analysis report was generated successfully.",
    )
    laundry_id: str = Field(
        description="Laundry id used for debt-risk report generation.",
        examples=["6a18a4e625addd1b6e2406b7"],
    )
    generated_at: str = Field(
        description="UTC timestamp when the current debt-risk report was generated.",
        examples=["2026-06-17T14:30:00+00:00"],
    )
    summary: str = Field(
        description="Plain-text debt risk explanation and trend summary for the backend document flow.",
        examples=[
            "Debt exposure during this period is concentrated in a few customers, with the largest balances already aging past one week. The current outstanding amount remains manageable, but follow-up should focus first on the oldest and highest-value debts."
        ],
    )
    table: ReportTable = Field(
        description="Structured table of outstanding debt rows for frontend or document rendering.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "laundry_id": "6a18a4e625addd1b6e2406b7",
                "generated_at": "2026-06-17T14:30:00+00:00",
                "summary": "Debt exposure during this period is concentrated in a few customers, with the largest balances already aging past one week. The current outstanding amount remains manageable, but follow-up should focus first on the oldest and highest-value debts.",
                "table": {
                    "headers": ["Customer", "Debt Owed", "Time Frame"],
                    "rows": [
                        ["John Doe", "NGN 25,000", "9 days outstanding"],
                        ["Jane Smith", "NGN 12,500", "4 days outstanding"],
                    ],
                },
            }
        }
    }


class ReportEntity(StrEnum):
    LAUNDRY = "laundry"
    BANK_ACCOUNT = "bank_account"
    CUSTOMERS = "customers"
    DEBTS = "debts"
    MEMBERS = "members"
    WALLET = "wallet"
    LOGISTICS = "logistics"
    PAYMENTS = "payments"
    ORDERS = "orders"


class ReportFileFormat(StrEnum):
    PDF = "pdf"
    XLSX = "xlsx"


SNAPSHOT_REPORT_ENTITIES = {
    ReportEntity.LAUNDRY,
    ReportEntity.BANK_ACCOUNT,
    ReportEntity.WALLET,
}


class GenerateReportRequest(BaseModel):
    laundry_id: str = Field(
        min_length=1,
        description="MongoDB ObjectId of the laundry that owns the requested report data.",
        examples=["6a18a4e625addd1b6e2406b7"],
    )
    entity: ReportEntity = Field(
        description="Business entity to report on. Arbitrary MongoDB collection names are not accepted.",
        examples=["orders"],
    )
    start_date: datetime | None = Field(
        default=None,
        description="Inclusive ISO 8601 start. Required for historical entities and omitted for snapshots.",
        examples=["2026-07-01T00:00:00Z"],
    )
    end_date: datetime | None = Field(
        default=None,
        description="Inclusive ISO 8601 end. Required for historical entities and omitted for snapshots.",
        examples=["2026-07-23T23:59:59Z"],
    )
    format: ReportFileFormat = Field(
        description="Output file format.",
        examples=["pdf"],
    )

    @model_validator(mode="after")
    def validate_report_window(self):
        if self.entity not in SNAPSHOT_REPORT_ENTITIES:
            if self.start_date is None or self.end_date is None:
                raise ValueError(
                    "start_date and end_date are required for this report entity."
                )
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("start_date and end_date must be provided together.")
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValueError("end_date must be greater than start_date.")
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "laundry_id": "6a18a4e625addd1b6e2406b7",
                    "entity": "orders",
                    "start_date": "2026-07-01T00:00:00Z",
                    "end_date": "2026-07-23T23:59:59Z",
                    "format": "pdf",
                },
                {
                    "laundry_id": "6a18a4e625addd1b6e2406b7",
                    "entity": "wallet",
                    "format": "xlsx",
                },
            ]
        }
    }


class GenerateReportResponse(BaseModel):
    success: bool = True
    filename: str = Field(description="Human-readable generated filename.")
    object_key: str = Field(description="Cloudflare R2 object key used to store the report.")
    download_url: str = Field(
        description="Temporary presigned URL that the frontend can use to download the private report."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "filename": "royalty_orders_2026-07-01_to_2026-07-23.pdf",
                "object_key": "reports/6a18a4e625addd1b6e2406b7/orders/2026/07/uuid.pdf",
                "download_url": "https://example.r2.cloudflarestorage.com/...",
            }
        }
    }

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
    )


class ExtractOrdersRequest(BaseModel):
    file_url: HttpUrl | list[HttpUrl] = Field(
        description=(
            "One Cloudflare-accessible historical-order image, PDF, CSV, or XLSX URL, "
            "or an array containing any supported mix."
        ),
        examples=["https://files.example.com/historical-orders.xlsx"],
    )

    @model_validator(mode="after")
    def validate_urls(self):
        if isinstance(self.file_url, list) and not self.file_url:
            raise ValueError("file_url must contain at least one URL when an array is provided.")
        return self

    def resolved_file_urls(self) -> list[HttpUrl]:
        if isinstance(self.file_url, list):
            return self.file_url
        return [self.file_url]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"file_url": "https://files.example.com/invoice-0142.jpeg"},
                {
                    "file_url": [
                        "https://files.example.com/orders-january.xlsx",
                        "https://files.example.com/invoice-0142-page-2.jpeg",
                    ]
                },
            ]
        }
    }


class HistoricalPaymentStatus(str, Enum):
    PAID = "paid"
    PARTIAL = "partial"
    UNPAID = "unpaid"


class HistoricalOrderStatus(str, Enum):
    COMPLETED = "completed"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    READY_FOR_PICKUP = "ready_for_pickup"


class OrderSourceReference(CamelModel):
    file_url: HttpUrl
    page: int | None = Field(default=None, ge=1)
    sheet: str | None = None
    row_numbers: list[int] = Field(default_factory=list)


class HistoricalCustomerSnapshot(CamelModel):
    full_name: str | None = None
    phone_number: str | None = None
    email: str | None = None


class HistoricalOrderItem(CamelModel):
    item_name_snapshot: str = Field(min_length=1)
    service_name_snapshot: str | None = None
    piece_count: int | None = Field(default=None, ge=1)
    color: str | None = None
    description: str | None = None
    unit_price: int | None = Field(default=None, ge=0)
    subtotal: int | None = Field(default=None, ge=0)
    currency: str = Field(default="NGN", min_length=3, max_length=3)


class HistoricalOrderData(CamelModel):
    tag_code: str | None = None
    customer_snapshot: HistoricalCustomerSnapshot | None = None
    source_staff_name: str | None = None
    created_at: datetime | None = None
    estimated_completion_time: datetime | None = None
    order_note: str | None = None
    items: list[HistoricalOrderItem] = Field(default_factory=list)
    item_count: int | None = Field(default=None, ge=0)
    total_piece_count: int | None = Field(default=None, ge=0)
    items_subtotal: int | None = Field(default=None, ge=0)
    discount_total: int | None = Field(default=None, ge=0)
    service_total: int | None = Field(default=None, ge=0)
    logistics_total: int | None = Field(default=None, ge=0)
    tax_total: int | None = Field(default=None, ge=0)
    express_surcharge: int | None = Field(default=None, ge=0)
    total_payable: int | None = Field(default=None, ge=0)
    total_amount_paid: int | None = Field(default=None, ge=0)
    total_balance_due: int | None = Field(default=None, ge=0)
    payment_status: HistoricalPaymentStatus | None = None
    order_status: HistoricalOrderStatus | None = None
    currency: str = Field(default="NGN", min_length=3, max_length=3)
    source_reference: OrderSourceReference


class ExtractedHistoricalOrder(HistoricalOrderData):
    items: list[HistoricalOrderItem] = Field(min_length=1)


class ReviewRequiredOrder(CamelModel):
    extracted_data: HistoricalOrderData
    issues: list[str] = Field(min_length=1)


class RejectedOrderSource(CamelModel):
    file_url: HttpUrl
    reason: str = Field(min_length=1)


class HistoricalOrderExtractionResponse(BaseModel):
    success: bool = True
    source_file_urls: list[HttpUrl]
    orders: list[ExtractedHistoricalOrder]
    review_required: list[ReviewRequiredOrder]
    rejected_sources: list[RejectedOrderSource]
    raw_extraction_text: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "source_file_urls": [
                    "https://files.example.com/invoice-0142.jpeg"
                ],
                "orders": [
                    {
                        "tagCode": "0142",
                        "customerSnapshot": {"fullName": "Mr Freedom"},
                        "sourceStaffName": "Emilia",
                        "createdAt": "2026-08-25T00:00:00+01:00",
                        "estimatedCompletionTime": "2026-08-28T00:00:00+01:00",
                        "items": [
                            {
                                "itemNameSnapshot": "SENATOR WEAR",
                                "pieceCount": 1,
                                "color": "light blue",
                                "unitPrice": 5500,
                                "subtotal": 5500,
                                "currency": "NGN",
                            }
                        ],
                        "itemCount": 2,
                        "totalPieceCount": 2,
                        "itemsSubtotal": 11000,
                        "discountTotal": 0,
                        "totalPayable": 11000,
                        "totalAmountPaid": 11000,
                        "totalBalanceDue": 0,
                        "paymentStatus": "paid",
                        "currency": "NGN",
                        "sourceReference": {
                            "fileUrl": "https://files.example.com/invoice-0142.jpeg",
                            "rowNumbers": [],
                        },
                    }
                ],
                "review_required": [],
                "rejected_sources": [],
                "raw_extraction_text": "InvoiceNo 0142 ...",
            }
        },
    )


class OrderItemDraft(CamelModel):
    item_name_snapshot: str | None
    service_name_snapshot: str | None
    piece_count: int | None
    color: str | None
    description: str | None
    unit_price: int | None
    subtotal: int | None
    currency: str | None


class OrderExtractionDraft(CamelModel):
    tag_code: str | None
    customer_full_name: str | None
    customer_phone_number: str | None
    customer_email: str | None
    source_staff_name: str | None
    created_at: str | None
    estimated_completion_time: str | None
    order_note: str | None
    items: list[OrderItemDraft]
    item_count: int | None
    total_piece_count: int | None
    items_subtotal: int | None
    discount_total: int | None
    service_total: int | None
    logistics_total: int | None
    tax_total: int | None
    express_surcharge: int | None
    total_payable: int | None
    total_amount_paid: int | None
    total_balance_due: int | None
    payment_status: str | None
    order_status: str | None
    currency: str | None
    source_page: int | None
    source_sheet: str | None
    source_row_numbers: list[int]
    extraction_issues: list[str]


class OrderSourceExtraction(CamelModel):
    is_order_source: bool
    rejection_reason: str | None
    raw_extraction_text: str
    orders: list[OrderExtractionDraft]

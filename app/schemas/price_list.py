from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class NormalizePriceListRequest(BaseModel):
    file_url: HttpUrl | list[HttpUrl] = Field(
        description=(
            "Cloudflare-accessible image, CSV, or XLSX URL, or an array containing any supported mix, "
            "for the laundry price list to normalize."
        ),
        examples=["https://files.example.com/laundry-price-list.xlsx"],
    )
    services: list[str] = Field(
        min_length=1,
        description=(
            "Current service names configured by the laundry. Extracted items can only be assigned "
            "services from this list."
        ),
        examples=[["washing", "ironing", "premium dry cleaning"]],
    )

    @field_validator("services")
    @classmethod
    def validate_services(cls, services: list[str]) -> list[str]:
        cleaned_services: list[str] = []
        for service in services:
            cleaned_service = service.strip()
            if not cleaned_service:
                raise ValueError("services must contain only non-empty service names.")
            if cleaned_service not in cleaned_services:
                cleaned_services.append(cleaned_service)
        if not cleaned_services:
            raise ValueError("services must contain at least one service name.")
        return cleaned_services

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
            "example": {
                "file_url": [
                    "https://files.example.com/laundry-price-list.xlsx",
                    "https://imagedelivery.net/account-id/laundry-price-list-page-2/public"
                ],
                "services": ["washing", "ironing", "premium dry cleaning"]
            }
        }
    }


class ParsedPriceListRow(BaseModel):
    original_name: str = Field(
        min_length=1,
        description="Item label exactly or near-exactly as extracted from the laundry's source list.",
        examples=["GRADUATION GOWN"],
    )
    price: int = Field(
        ge=0,
        description="Price parsed from the laundry list in whole currency units.",
        examples=[2500],
    )


class ExtractedPriceListItem(BaseModel):
    item_name: str = Field(
        min_length=1,
        description="Item name preserved from the laundry owner's source price list.",
        examples=["WEDDING GOWN (BIG)"],
    )
    price: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Numeric price when the source contains one unambiguous amount; otherwise null."
        ),
        examples=[10000],
    )
    price_text: str = Field(
        min_length=1,
        description=(
            "Price exactly as represented in the source, including multiple values or non-numeric markers."
        ),
        examples=["800 / 700"],
    )
    services: list[str] = Field(
        default_factory=list,
        description=(
            "Applicable services inferred from the service names supplied in the request. Service names "
            "are returned exactly as supplied and no service outside that list is introduced."
        ),
        examples=[["washing", "ironing", "washing and ironing", "dry cleaning"]],
    )


class PriceListVisionItem(BaseModel):
    item_name: str
    price: int | None
    price_text: str
    service_eligibility: dict[str, bool]


class PriceListVisionExtraction(BaseModel):
    is_price_list: bool
    rejection_reason: str | None
    laundry_name: str | None
    raw_ocr_text: str = Field(min_length=1)
    items: list[PriceListVisionItem]


class PriceListImageExtraction(BaseModel):
    laundry_name: str | None
    raw_ocr_text: str = Field(min_length=1)
    items: list[ExtractedPriceListItem]


class MatchedPriceListRow(ParsedPriceListRow):
    matched_item_type: str = Field(
        min_length=1,
        description="Canonical internal item type chosen for the source laundry item.",
        examples=["graduation gown"],
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model confidence score for the item-type match, between 0 and 1.",
        examples=[0.99],
    )
    supported_services: list[str] = Field(
        description="Supported service types for the matched internal item type.",
        examples=[["dry cleaning"]],
    )


class UnmatchedPriceListRow(ParsedPriceListRow):
    reason: str = Field(
        min_length=1,
        description="Reason the item could not be confidently matched to an internal item type.",
        examples=["Could not confidently map item."],
    )


class MatchingResultRow(BaseModel):
    original_name: str
    price: int
    matched_item_type: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str | None = None


class MatchingResultPayload(BaseModel):
    laundry_name: str | None = None
    items: list[MatchingResultRow]


class NormalizedPriceListResponse(BaseModel):
    success: bool = Field(
        default=True,
        description="Whether the normalization request completed successfully.",
    )
    laundry_name: str | None = Field(
        default=None,
        description="Laundry/business name detected from the source file when available.",
        examples=["1124 Laundry/Dry Cleaners"],
    )
    currency: str = Field(
        description="Currency code used for the returned parsed prices.",
        examples=["NGN"],
    )
    source_file_urls: list[HttpUrl] = Field(
        description="Original Cloudflare image, CSV, or XLSX URLs used for the normalization request.",
    )
    items: list[ExtractedPriceListItem] = Field(
        description=(
            "Item names and prices faithfully extracted from the laundry owner's source list. "
            "Item names are not mapped to the Laundry OS canonical item taxonomy."
        ),
    )
    raw_ocr_text: str = Field(
        description=(
            "Raw OCR text for images or deterministic row text for CSV/XLSX files, returned for debugging and audit purposes."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "laundry_name": "1124 Laundry/Dry Cleaners",
                "currency": "NGN",
                "source_file_urls": [
                    "https://imagedelivery.net/account-id/laundry-price-list-1/public",
                    "https://imagedelivery.net/account-id/laundry-price-list-2/public"
                ],
                "items": [
                    {
                        "item_name": "SKIRT LONG / SHORT",
                        "price": None,
                        "price_text": "800 / 700",
                        "services": [
                            "washing",
                            "ironing",
                            "washing and ironing",
                            "dry cleaning",
                        ],
                    }
                ],
                "raw_ocr_text": "WEDDING GOWN (BIG) 10,000",
            }
        }
    }

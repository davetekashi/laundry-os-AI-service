from pydantic import BaseModel, Field, HttpUrl, model_validator


class NormalizePriceListRequest(BaseModel):
    file_url: HttpUrl | list[HttpUrl] = Field(
        description="Cloudflare-accessible image URL or array of image URLs for the laundry price list to normalize.",
        examples=["https://imagedelivery.net/account-id/laundry-price-list-1/public"],
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
            "example": {
                "file_url": [
                    "https://imagedelivery.net/account-id/laundry-price-list-1/public",
                    "https://imagedelivery.net/account-id/laundry-price-list-2/public"
                ]
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
    price: int = Field(
        ge=0,
        description="Price parsed from the laundry list in whole currency units.",
        examples=[10000],
    )


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
        description="Laundry/business name detected from the source image when available.",
        examples=["1124 Laundry/Dry Cleaners"],
    )
    currency: str = Field(
        description="Currency code used for the returned parsed prices.",
        examples=["NGN"],
    )
    source_file_urls: list[HttpUrl] = Field(
        description="Original Cloudflare image URLs used for the normalization request.",
    )
    items: list[ExtractedPriceListItem] = Field(
        description=(
            "Item names and prices faithfully extracted from the laundry owner's source list. "
            "Item names are not mapped to the Laundry OS canonical item taxonomy."
        ),
    )
    raw_ocr_text: str = Field(
        description="Raw OCR text returned from the vision extraction step for debugging and audit purposes.",
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
                        "item_name": "WEDDING GOWN (BIG)",
                        "price": 10000,
                    }
                ],
                "raw_ocr_text": "WEDDING GOWN (BIG) 10,000",
            }
        }
    }

from pydantic import BaseModel, Field, HttpUrl, model_validator


class ExtractCustomersRequest(BaseModel):
    file_url: HttpUrl | list[HttpUrl] = Field(
        description=(
            "Cloudflare-accessible customer-list image URL or array of image URLs. "
            "Use an array when the customer list spans multiple images."
        ),
        examples=["https://imagedelivery.net/account-id/customer-list-1/public"],
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
                {
                    "file_url": "https://imagedelivery.net/account-id/customer-list-1/public"
                },
                {
                    "file_url": [
                        "https://imagedelivery.net/account-id/customer-list-1/public",
                        "https://imagedelivery.net/account-id/customer-list-2/public",
                    ]
                },
            ]
        }
    }


class ExtractedCustomer(BaseModel):
    full_name: str = Field(
        min_length=1,
        description="Customer's full name as extracted from the source image.",
        examples=["John Doe"],
    )
    phone_number: str = Field(
        min_length=1,
        description=(
            "Customer's phone number preserved as text so leading zeroes and country prefixes are retained."
        ),
        examples=["08012345678"],
    )
    email: str | None = Field(
        default=None,
        description="Customer email address when present in the source image; otherwise null.",
        examples=["john@example.com"],
    )


class UnresolvedCustomerRecord(BaseModel):
    raw_value: str = Field(
        min_length=1,
        description="Source row or text fragment that could not be converted into a valid customer.",
    )
    full_name: str | None = None
    phone_number: str | None = None
    email: str | None = None
    reason: str = Field(
        min_length=1,
        description="Why the record requires manual review.",
    )


class CustomerExtractionResponse(BaseModel):
    success: bool = True
    source_file_urls: list[HttpUrl] = Field(
        description="Cloudflare image URLs processed by this request."
    )
    customers: list[ExtractedCustomer] = Field(
        description="Customer records containing both a full name and phone number."
    )
    unresolved_records: list[UnresolvedCustomerRecord] = Field(
        description="Incomplete or uncertain records that require manual review."
    )
    raw_ocr_text: str = Field(
        description="Combined raw OCR text for debugging and audit purposes."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "source_file_urls": [
                    "https://imagedelivery.net/account-id/customer-list-1/public"
                ],
                "customers": [
                    {
                        "full_name": "John Doe",
                        "phone_number": "08012345678",
                        "email": "john@example.com",
                    },
                    {
                        "full_name": "Mary James",
                        "phone_number": "07098765432",
                        "email": None,
                    },
                ],
                "unresolved_records": [],
                "raw_ocr_text": "FULL NAME | PHONE NUMBER | EMAIL\nJohn Doe | 08012345678 | john@example.com",
            }
        }
    }

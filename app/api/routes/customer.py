from fastapi import APIRouter, HTTPException

from app.schemas.customer import CustomerExtractionResponse, ExtractCustomersRequest
from app.services.customer_extractor import CustomerExtractionError, extract_customers


router = APIRouter(tags=["customers"])


@router.post(
    "/customers/extract",
    response_model=CustomerExtractionResponse,
    summary="Extract customer records from one or more customer-list images",
    description=(
        "Accepts one Cloudflare-hosted customer-list image URL or an array of URLs, performs OCR, "
        "and returns structured customer records. A valid customer requires a full name and phone "
        "number; email is optional and is returned as null when absent. Overlapping records across "
        "multiple images are deduplicated by phone number. Incomplete, uncertain, or conflicting "
        "records are returned in `unresolved_records` for manual review. This endpoint extracts data "
        "only and does not insert customers into MongoDB."
    ),
    responses={
        400: {
            "description": "The image could not be downloaded, read, or converted into customer records.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "No customer records could be extracted from the uploaded image(s)."
                    }
                }
            },
        },
        500: {
            "description": "Unexpected server-side failure.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Failed to extract customers: unexpected internal error"
                    }
                }
            },
        },
    },
)
async def extract_customers_endpoint(
    payload: ExtractCustomersRequest,
) -> CustomerExtractionResponse:
    try:
        return await extract_customers(
            [str(file_url) for file_url in payload.resolved_file_urls()]
        )
    except CustomerExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract customers: {str(exc)}",
        ) from exc

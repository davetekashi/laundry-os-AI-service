from fastapi import APIRouter, HTTPException

from app.schemas.price_list import NormalizePriceListRequest, NormalizedPriceListResponse
from app.services.price_list_normalizer import PriceListNormalizationError, normalize_price_list


router = APIRouter(tags=["price-lists"])


@router.post(
    "/price-lists/normalize",
    response_model=NormalizedPriceListResponse,
    summary="Digitize item names and prices from a laundry price list",
    description=(
        "Accepts one Cloudflare-hosted image, CSV, or XLSX URL, or an array containing any supported mix. "
        "Images are read with vision OCR; CSV and XLSX rows are read deterministically. "
        "and returns the item names and prices found in the source list. The request must also include the "
        "laundry's currently configured `services`; the AI assigns each item only applicable names from that "
        "list and never falls back to a predefined service catalogue. Item names are preserved as supplied "
        "by the laundry owner and are not mapped to predefined Laundry OS item types. Each item includes the "
        "original `price_text`; `price` is null when the source contains multiple or non-numeric values.\n\n"
        "Use this endpoint to digitize a laundry owner's existing paper, image, CSV, or Excel price list."
    ),
    responses={
        400: {
            "description": "Client-side processing error such as download, file reading, OCR, or row-parsing failure.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "No price list rows could be extracted from the uploaded files."
                    }
                }
            },
        },
        500: {
            "description": "Unexpected server-side failure.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Failed to normalize price list: unexpected internal error"
                    }
                }
            },
        },
    },
)
async def normalize_price_list_endpoint(
    payload: NormalizePriceListRequest,
) -> NormalizedPriceListResponse:
    try:
        return await normalize_price_list(
            [str(file_url) for file_url in payload.resolved_file_urls()],
            payload.services,
        )
    except PriceListNormalizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to normalize price list: {str(exc)}",
        ) from exc

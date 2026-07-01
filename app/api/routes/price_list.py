from fastapi import APIRouter, HTTPException

from app.schemas.price_list import NormalizePriceListRequest, NormalizedPriceListResponse
from app.services.price_list_normalizer import PriceListNormalizationError, normalize_price_list


router = APIRouter(tags=["price-lists"])


@router.post(
    "/price-lists/normalize",
    response_model=NormalizedPriceListResponse,
    summary="Normalize a laundry price list image into internal item types",
    description=(
        "Accepts one or more Cloudflare-hosted image URLs for a laundry price list, performs OCR on each image, "
        "extracts item/price rows, maps each source item label to an internal canonical item type, "
        "and returns supported services for each matched item.\n\n"
        "Use this endpoint when a laundry uploads its own custom price list and the platform needs to "
        "normalize it into the shared Laundry OS item taxonomy."
    ),
    responses={
        400: {
            "description": "Client-side normalization error such as download, OCR, parsing, or matching failure.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "No price list rows could be extracted from the uploaded image."
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
            [str(file_url) for file_url in payload.resolved_file_urls()]
        )
    except PriceListNormalizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to normalize price list: {str(exc)}",
        ) from exc

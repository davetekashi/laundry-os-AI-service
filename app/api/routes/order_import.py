from typing import Annotated

from fastapi import APIRouter, Body, HTTPException

from app.schemas.order_import import (
    ExtractOrdersRequest,
    HistoricalOrderExtractionResponse,
)
from app.services.order_import_service import (
    HistoricalOrderExtractionError,
    extract_historical_orders,
)


router = APIRouter(tags=["order-migration"])


@router.post(
    "/orders/extract",
    response_model=HistoricalOrderExtractionResponse,
    response_model_exclude_none=True,
    summary="Extract historical laundry orders for bulk migration",
    description=(
        "Accepts one Cloudflare-accessible image, PDF, CSV, or XLSX URL, or an array containing any "
        "supported mix. The AI interprets arbitrary historical invoice, receipt, and spreadsheet layouts "
        "and returns populated order migration JSON; it does not insert anything into MongoDB.\n\n"
        "`orders` contains internally coherent candidates ready for backend resolution. `review_required` "
        "preserves useful candidates with ambiguous dates, conflicting arithmetic, duplicate invoice codes, "
        "or other issues. `rejected_sources` identifies files that contain no usable order data or cannot be "
        "read. Unknown optional fields are omitted from the HTTP response.\n\n"
        "Invoice, receipt, voucher, ticket, docket, or job numbers map to `tagCode` and remain strings so "
        "leading zeroes are preserved. Source staff names are returned as `sourceStaffName`; the backend may "
        "resolve them to a member ID. The backend remains responsible for authenticated business/branch scope, "
        "customer and catalogue resolution, internal identifiers, fees, commissions, defaults, duplicate checks "
        "against existing data, user approval, and persistence."
    ),
    responses={
        400: {
            "description": "A technical download, document-reading, or AI extraction step failed.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Order extraction failed for 'https://files.example.com/orders.pdf': OpenAI order extraction returned an empty response."
                    }
                }
            },
        },
        500: {
            "description": "Unexpected server-side failure.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Failed to extract historical orders: unexpected internal error"
                    }
                }
            },
        },
    },
)
async def extract_historical_orders_endpoint(
    payload: Annotated[
        ExtractOrdersRequest,
        Body(
            openapi_examples={
                "single_receipt": {
                    "summary": "One photographed historical receipt",
                    "value": {
                        "file_url": "https://files.example.com/invoice-0142.jpeg"
                    },
                },
                "bulk_spreadsheet": {
                    "summary": "One historical-order workbook",
                    "value": {
                        "file_url": "https://files.example.com/orders-2025.xlsx"
                    },
                },
                "mixed_sources": {
                    "summary": "Multiple files in different supported formats",
                    "value": {
                        "file_url": [
                            "https://files.example.com/orders-january.csv",
                            "https://files.example.com/invoice-0142.pdf",
                            "https://files.example.com/invoice-0143.jpeg",
                        ]
                    },
                },
            }
        ),
    ],
) -> HistoricalOrderExtractionResponse:
    try:
        return await extract_historical_orders(
            [str(file_url) for file_url in payload.resolved_file_urls()]
        )
    except HistoricalOrderExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract historical orders: {str(exc)}",
        ) from exc

from app.api.routes.chat import router as chat_router
from app.api.routes.context import router as context_router
from app.api.routes.customer import router as customer_router
from app.api.routes.report import router as report_router
from fastapi import FastAPI

from app.api.routes.price_list import router as price_list_router


app = FastAPI(
    title="Laundry OS AI Service",
    version="0.1.0",
    description=(
        "AI-powered endpoints for Laundry OS.\n\n"
        "This service currently supports:\n"
        "- Laundry price list normalization from Cloudflare-hosted image URLs.\n"
        "- Customer record extraction from one or more Cloudflare-hosted images.\n"
        "- Context preparation for a specific laundry using MongoDB-backed business data.\n"
        "- Chat responses grounded only in previously prepared in-memory laundry context.\n\n"
        "Integration flow for backend teams:\n"
        "1. Call `POST /api/v1/context/prepare` when a laundry user logs in.\n"
        "2. Call `POST /api/v1/chat` for subsequent AI chat requests using the same `laundry_id`.\n"
        "3. Call `POST /api/v1/price-lists/normalize` whenever a laundry submits an item-price image for normalization.\n\n"
        "4. Call `POST /api/v1/customers/extract` to extract customer records from customer-list images.\n\n"
        "Important notes:\n"
        "- `/api/v1/chat` does not build context on demand. Context must already be prepared.\n"
        "- Prepared context is stored in memory only and is lost on service restart.\n"
        "- The price-list endpoint expects a Cloudflare-accessible image URL, not a file upload."
    ),
    openapi_tags=[
        {
            "name": "price-lists",
            "description": (
                "Endpoints for extracting OCR text from laundry price-list images, "
                "mapping laundry-specific item labels to internal canonical item types, "
                "and attaching the supported services for each matched internal item."
            ),
        },
        {
            "name": "context",
            "description": (
                "Endpoints for building and caching sanitized in-memory AI context "
                "for a specific laundry using MongoDB-backed operational data."
            ),
        },
        {
            "name": "customers",
            "description": (
                "Endpoints for extracting structured customer names, phone numbers, and optional email "
                "addresses from one or more Cloudflare-hosted customer-list images."
            ),
        },
        {
            "name": "chat",
            "description": (
                "Endpoints for answering laundry business questions using only previously "
                "prepared in-memory context. These endpoints are optimized for low-latency "
                "responses after login-triggered context preparation."
            ),
        },
        {
            "name": "reports",
            "description": (
                "Endpoints for generating date-range business reports from MongoDB-backed laundry data. "
                "These compute factual metrics in code, then optionally use AI only for narrative formatting."
            ),
        },
    ],
)

app.include_router(price_list_router, prefix="/api/v1")
app.include_router(customer_router, prefix="/api/v1")
app.include_router(context_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(report_router, prefix="/api/v1")


@app.get(
    "/health",
    tags=["health"],
    summary="Health check",
    description="Simple service health check for deployment verification and uptime monitoring.",
)
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}

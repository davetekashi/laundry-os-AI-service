from app.api.routes.chat import router as chat_router
from app.api.routes.context import router as context_router
from app.api.routes.customer import router as customer_router
from app.api.routes.order_import import router as order_import_router
from app.api.routes.report import router as report_router
from fastapi import FastAPI

from app.api.routes.price_list import router as price_list_router


app = FastAPI(
    title="Laundry OS AI Service",
    version="0.1.0",
    description=(
        "AI-powered endpoints for Laundry OS.\n\n"
        "This service currently supports:\n"
        "- Laundry price list digitization from Cloudflare-hosted image, CSV, or XLSX URLs.\n"
        "- Customer record extraction from one or more Cloudflare-hosted image, CSV, or XLSX files.\n"
        "- Historical order extraction from Cloudflare-hosted images, PDFs, CSV, or XLSX files for backend-controlled migration.\n"
        "- Branch- and role-scoped context preparation for owner, business-manager, and staff users using MongoDB-backed business data.\n"
        "- Chat responses grounded in a compact overview plus exact role-scoped retrieval from prepared records.\n\n"
        "- Entity-specific PDF and Excel reports uploaded securely to Cloudflare R2.\n\n"
        "- Weekly Excel business summaries with reconciled collections, expenses, customer balances, and profit/cash results.\n\n"
        "Integration flow for backend teams:\n"
        "1. Call `POST /api/v1/context/prepare` with only `business_id` for business-wide owner context, or with a branch `laundry_id` for branch context; always include the authenticated `role`.\n"
        "2. Call `POST /api/v1/chat` using the same scope identifiers and authenticated `role`; retain the returned `conversation_id` and send it with subsequent messages in that conversation.\n"
        "3. Call `POST /api/v1/price-lists/normalize` whenever a laundry submits an item-price image for normalization.\n\n"
        "4. Call `POST /api/v1/customers/extract` to extract customer records from customer-list images.\n\n"
        "5. Call `POST /api/v1/orders/extract` to convert historical order files into migration-ready JSON without writing to MongoDB.\n\n"
        "6. Call `POST /api/v1/reports/generate` to generate an entity report and receive a temporary download URL.\n\n"
        "7. Call `POST /api/v1/reports/weekly-summary` to generate a weekly Excel workbook and receive a temporary download URL.\n\n"
        "Important notes:\n"
        "- `/api/v1/chat` does not build context on demand. Matching business-scope-and-role context must already be prepared.\n"
        "- Prepared context stores normalized searchable records in memory only and is lost on service restart.\n"
        "- File-processing endpoints expect Cloudflare-accessible URLs, not multipart file uploads."
    ),
    openapi_tags=[
        {
            "name": "price-lists",
            "description": (
                "Endpoints for faithfully extracting laundry-specific item names and prices "
                "from one or more Cloudflare-hosted price-list images."
            ),
        },
        {
            "name": "context",
            "description": (
                "Endpoints for building and caching sanitized, searchable in-memory AI context "
                "for a branch or whole business using MongoDB-backed operational data."
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
            "name": "order-migration",
            "description": (
                "Endpoints for interpreting historical laundry receipts, invoices, PDFs, CSV files, and Excel workbooks "
                "as populated order migration JSON. Extraction never persists orders or generates internal IDs."
            ),
        },
        {
            "name": "chat",
            "description": (
                "Endpoints for answering laundry business questions from previously prepared "
                "overview and record data. Anne retrieves only the evidence needed for detailed "
                "questions while ordinary conversation remains lightweight."
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
app.include_router(order_import_router, prefix="/api/v1")
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

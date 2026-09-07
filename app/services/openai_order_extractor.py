import base64
import json

from openai import OpenAI

from app.core.config import get_settings
from app.schemas.order_import import OrderSourceExtraction


ORDER_EXTRACTION_PROMPT = """
Interpret this source as historical laundry-order data and return every genuine order in source order.

The source may be a receipt, invoice, photographed notebook, exported report, CSV, or spreadsheet using any layout or terminology. Understand the document semantically rather than expecting fixed headers.

Mapping principles:
- An invoice, receipt, ticket, voucher, docket, or job number maps to tagCode. Preserve it as text, including leading zeroes.
- Customer details map to customerFullName, customerPhoneNumber, and customerEmail.
- The order, voucher, invoice, or received date maps to createdAt. A promised, collection, completion, or due date maps to estimatedCompletionTime.
- A visible staff, attendant, cashier, or received-by name maps to sourceStaffName.
- Product, garment, article, or item rows map to items. Preserve source item and service names rather than converting them to Seanosis catalogue IDs.
- Quantity maps to pieceCount, rate or unit amount maps to unitPrice, and line amount maps to subtotal.
- Gross/subtotal, discount, service, delivery/logistics, tax, express surcharge, grand total, amount paid, and balance map to their corresponding fields.
- Infer paymentStatus only when explicit payment wording or the stated total, paid amount, and balance make it unambiguous.
- Set orderStatus only when the source explicitly communicates a compatible lifecycle status. Age or a past date alone does not mean completed.

Integrity principles:
- Extract only facts supported by the source. Use null when a scalar is absent, illegible, or uncertain.
- Do not invent MongoDB IDs, internal order codes, item IDs, service IDs, customer IDs, platform fees, commissions, receipt URLs, verification data, or lifecycle events.
- Preserve distinct orders and distinct item rows. Group rows into one order when the source shows they share the same invoice or order.
- For spreadsheets, ROW markers are provenance labels rather than source values. Return the contributing numbers in sourceRowNumbers and never include ROW text in business fields.
- Monetary values are whole currency units without symbols or separators. Do not force an ambiguous or decimal value into an integer.
- When the source does not print a currency, use the configured default currency supplied with the request context; this is expected migration context and is not an extraction issue.
- Use ISO 8601 for dates when they can be interpreted. A date without a source timezone may be returned as YYYY-MM-DD.
- extractionIssues should briefly identify genuine ambiguity or conflict, not ordinary missing optional fields.
- rawExtractionText is a faithful transcription or compact row-preserving representation, without analysis or hidden reasoning.
- Set isOrderSource false only when the source contains no genuine historical laundry orders.
""".strip()


def _nullable(value_type: str) -> dict:
    return {"type": [value_type, "null"]}


def build_order_response_format() -> dict:
    item_properties = {
        "itemNameSnapshot": _nullable("string"),
        "serviceNameSnapshot": _nullable("string"),
        "pieceCount": _nullable("integer"),
        "color": _nullable("string"),
        "description": _nullable("string"),
        "unitPrice": _nullable("integer"),
        "subtotal": _nullable("integer"),
        "currency": _nullable("string"),
    }
    order_properties = {
        "tagCode": _nullable("string"),
        "customerFullName": _nullable("string"),
        "customerPhoneNumber": _nullable("string"),
        "customerEmail": _nullable("string"),
        "sourceStaffName": _nullable("string"),
        "createdAt": _nullable("string"),
        "estimatedCompletionTime": _nullable("string"),
        "orderNote": _nullable("string"),
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": item_properties,
                "required": list(item_properties),
                "additionalProperties": False,
            },
        },
        "itemCount": _nullable("integer"),
        "totalPieceCount": _nullable("integer"),
        "itemsSubtotal": _nullable("integer"),
        "discountTotal": _nullable("integer"),
        "serviceTotal": _nullable("integer"),
        "logisticsTotal": _nullable("integer"),
        "taxTotal": _nullable("integer"),
        "expressSurcharge": _nullable("integer"),
        "totalPayable": _nullable("integer"),
        "totalAmountPaid": _nullable("integer"),
        "totalBalanceDue": _nullable("integer"),
        "paymentStatus": {
            "type": ["string", "null"],
            "enum": ["paid", "partial", "unpaid", None],
        },
        "orderStatus": {
            "type": ["string", "null"],
            "enum": [
                "completed",
                "confirmed",
                "in_progress",
                "ready_for_pickup",
                None,
            ],
        },
        "currency": _nullable("string"),
        "sourcePage": _nullable("integer"),
        "sourceSheet": _nullable("string"),
        "sourceRowNumbers": {"type": "array", "items": {"type": "integer"}},
        "extractionIssues": {"type": "array", "items": {"type": "string"}},
    }
    schema_properties = {
        "isOrderSource": {"type": "boolean"},
        "rejectionReason": _nullable("string"),
        "rawExtractionText": {"type": "string"},
        "orders": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": order_properties,
                "required": list(order_properties),
                "additionalProperties": False,
            },
        },
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "historical_laundry_order_extraction",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": schema_properties,
                "required": list(schema_properties),
                "additionalProperties": False,
            },
        },
    }


def _parse_completion(response) -> OrderSourceExtraction:
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("OpenAI order extraction returned an empty response.")
    return OrderSourceExtraction.model_validate_json(content)


def extract_orders_from_image(
    image_content: bytes,
    media_type: str,
    *,
    page_number: int | None = None,
    embedded_text: str | None = None,
) -> OrderSourceExtraction:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    source_context = {
        "page_number": page_number,
        "embedded_pdf_text": embedded_text or None,
        "configured_default_currency": settings.default_currency.upper(),
    }
    response = client.chat.completions.create(
        model=settings.openai_vision_model,
        response_format=build_order_response_format(),
        max_completion_tokens=32768,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise historical laundry-order migration interpreter. "
                    "Return only data grounded in the supplied source."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"{ORDER_EXTRACTION_PROMPT}\n\n"
                            "SOURCE CONTEXT:\n"
                            f"{json.dumps(source_context, ensure_ascii=True)}"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": (
                                f"data:{media_type};base64,"
                                f"{base64.b64encode(image_content).decode('ascii')}"
                            ),
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
    )
    return _parse_completion(response)


def extract_orders_from_tabular_text(
    source_text: str,
    *,
    sheet: str | None,
    row_numbers: list[int],
) -> OrderSourceExtraction:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_matching_model,
        response_format=build_order_response_format(),
        max_completion_tokens=32768,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise historical laundry-order spreadsheet migration interpreter. "
                    "Return only data grounded in the supplied rows."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{ORDER_EXTRACTION_PROMPT}\n\n"
                    f"CONFIGURED DEFAULT CURRENCY: {settings.default_currency.upper()}\n"
                    f"SOURCE SHEET: {sheet or 'CSV'}\n"
                    f"AVAILABLE SOURCE ROWS: {json.dumps(row_numbers)}\n\n"
                    "SOURCE ROWS:\n"
                    f"{source_text}"
                ),
            },
        ],
    )
    return _parse_completion(response)

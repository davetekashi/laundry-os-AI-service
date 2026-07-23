import base64
import json
import mimetypes
from pathlib import Path

from openai import OpenAI

from app.core.config import get_settings
from app.schemas.price_list import (
    ExtractedPriceListItem,
    PriceListImageExtraction,
    PriceListVisionExtraction,
)
from app.services.catalog import load_item_services
from app.services.parser import (
    clean_item_name,
    clean_ocr_text,
    is_valid_item_name,
    parse_single_numeric_price,
)


PRICE_LIST_EXTRACTION_PROMPT = """
Digitize this laundry price-list image into structured data.

Requirements:
- Read the image directly and extract every genuine item/service and its corresponding price.
- Handle ordinary, side-by-side, and multi-column tables. Associate each price only with the item in the same column.
- Preserve each item_name exactly as printed, apart from obvious OCR spacing.
- item_name must contain only the actual item/service value. Never add Row 1, Line 2, Item 3, bullet numbers, column labels, explanations, or commentary.
- Preserve the visible price expression in price_text, including commas, slashes, currency symbols, asterisks, and other visible markers.
- Set price to an integer only when price_text contains exactly one unambiguous numeric amount.
- Set price to null for multiple values such as 800 / 700 or 3000/4000/5000, and for non-numeric values such as ******.
- Keep separately printed duplicate records, including similar records in male and female columns.
- Ignore headings, addresses, phone numbers, emails, slogans, and table labels as item records.
- Do not invent, rename, categorize, normalize, combine, or match items.
- For each record, choose service_reference_item only from the supplied internal service mapping.
- service_reference_item is used only for service lookup; it must never alter item_name.
- Choose the closest reference only when the item type is clear, including Nigerian native-wear wording and obvious size, gender, starch, fold, complete/set, or service modifiers.
- Examples: COMPLETE AGBADA refers to agbada; WOKO COMPLETE refers to woko; TIE DRYCLEANING refers to tie; SHIRT (LIGHT STARCH) & FOLD refers to a shirt.
- Return service_reference_item as null when the item is unfamiliar or cannot be classified confidently. Never guess a reference merely to avoid null.
- raw_ocr_text must be a faithful transcription only. Do not include analysis, reasoning, row numbers, line labels, markdown commentary, or <think> content.
- Return the laundry/business name only when it is visibly identifiable; otherwise return null.
""".strip()


def build_response_format(canonical_items: list[str]) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "laundry_price_list_extraction",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "laundry_name": {"type": ["string", "null"]},
                    "raw_ocr_text": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item_name": {"type": "string"},
                                "price": {"type": ["integer", "null"]},
                                "price_text": {"type": "string"},
                                "service_reference_item": {
                                    "type": ["string", "null"],
                                    "enum": [*canonical_items, None],
                                },
                            },
                            "required": [
                                "item_name",
                                "price",
                                "price_text",
                                "service_reference_item",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["laundry_name", "raw_ocr_text", "items"],
                "additionalProperties": False,
            },
        },
    }


def encode_image(file_path: str) -> str:
    return base64.b64encode(Path(file_path).read_bytes()).decode("utf-8")


def extract_price_list_image(file_path: str) -> PriceListImageExtraction:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    media_type = mimetypes.guess_type(file_path)[0] or "image/jpeg"
    item_services = load_item_services()
    service_mapping = json.dumps(item_services, ensure_ascii=True, separators=(",", ":"))
    prompt = (
        f"{PRICE_LIST_EXTRACTION_PROMPT}\n\n"
        "INTERNAL SERVICE MAPPING (reference item -> supported services):\n"
        f"{service_mapping}"
    )

    response = client.chat.completions.create(
        model=settings.openai_vision_model,
        response_format=build_response_format(list(item_services)),
        max_completion_tokens=16384,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise document digitization system. Return only data supported by the image."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{encode_image(file_path)}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("OpenAI price-list extraction returned an empty response.")

    payload = PriceListVisionExtraction.model_validate_json(content)
    cleaned_items: list[ExtractedPriceListItem] = []

    for item in payload.items:
        item_name = clean_item_name(item.item_name)
        price_text = item.price_text.strip()
        if not is_valid_item_name(item_name) or not price_text:
            continue

        cleaned_items.append(
            ExtractedPriceListItem(
                item_name=item_name,
                price=parse_single_numeric_price(price_text),
                price_text=price_text,
                services=item_services.get(item.service_reference_item or "", []),
            )
        )

    raw_ocr_text = clean_ocr_text(payload.raw_ocr_text)
    if not raw_ocr_text:
        raise RuntimeError("OpenAI price-list extraction returned no transcription.")
    if not cleaned_items:
        raise RuntimeError("OpenAI price-list extraction returned no valid item rows.")

    laundry_name = payload.laundry_name.strip() if payload.laundry_name else None
    return PriceListImageExtraction(
        laundry_name=laundry_name or None,
        raw_ocr_text=raw_ocr_text,
        items=cleaned_items,
    )

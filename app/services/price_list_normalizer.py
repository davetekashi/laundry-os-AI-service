import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.schemas.price_list import (
    MatchedPriceListRow,
    NormalizedPriceListResponse,
    ParsedPriceListRow,
    UnmatchedPriceListRow,
)
from app.services.catalog import load_item_services
from app.services.matcher import match_price_list_rows
from app.services.ocr import extract_image_text
from app.services.parser import (
    parse_laundry_name,
    parse_price_list_rows,
    parse_price_list_rows_with_llm,
)


class PriceListNormalizationError(Exception):
    pass


async def download_source_file(file_url: str) -> tuple[bytes, str]:
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(file_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise PriceListNormalizationError(f"Failed to download source file: {str(exc)}") from exc

    content_type = response.headers.get("content-type", "").lower()
    if not content_type.startswith("image/"):
        raise PriceListNormalizationError(
            f"Source URL must point to an image. Received content-type '{content_type or 'unknown'}'."
        )

    file_bytes = response.content
    if not file_bytes:
        raise PriceListNormalizationError("Downloaded source file is empty.")

    parsed_url = urlparse(file_url)
    suffix = Path(parsed_url.path).suffix or ".jpg"
    return file_bytes, suffix


def deduplicate_rows(rows: list[ParsedPriceListRow]) -> list[ParsedPriceListRow]:
    seen: set[tuple[str, int]] = set()
    deduplicated: list[ParsedPriceListRow] = []

    for row in rows:
        row_key = (row.original_name.lower(), row.price)
        if row_key in seen:
            continue
        seen.add(row_key)
        deduplicated.append(row)

    return deduplicated


async def normalize_price_list(file_urls: list[str]) -> NormalizedPriceListResponse:
    if not file_urls:
        raise PriceListNormalizationError("At least one file URL is required.")

    all_raw_ocr_texts: list[str] = []
    all_parsed_rows: list[ParsedPriceListRow] = []
    detected_laundry_name: str | None = None

    for file_url in file_urls:
        file_bytes, suffix = await download_source_file(file_url)

        with tempfile.NamedTemporaryFile(delete=True, suffix=suffix) as temp_file:
            temp_file.write(file_bytes)
            temp_file.flush()

            try:
                raw_ocr_text = extract_image_text(temp_file.name)
            except Exception as exc:
                raise PriceListNormalizationError(
                    f"OCR step failed for '{file_url}': {str(exc)}"
                ) from exc

        all_raw_ocr_texts.append(raw_ocr_text)

        parsed_rows = parse_price_list_rows(raw_ocr_text)
        if not parsed_rows:
            try:
                parsed_rows = parse_price_list_rows_with_llm(raw_ocr_text)
            except Exception as exc:
                raise PriceListNormalizationError(
                    f"Could not parse price list rows from OCR text for '{file_url}'. "
                    f"LLM fallback failed: {str(exc)}"
                ) from exc

        if not parsed_rows:
            raise PriceListNormalizationError(
                f"No price list rows could be extracted from uploaded image '{file_url}'."
            )

        all_parsed_rows.extend(parsed_rows)

        page_laundry_name = parse_laundry_name(raw_ocr_text)
        if page_laundry_name and not detected_laundry_name:
            detected_laundry_name = page_laundry_name

    parsed_rows = deduplicate_rows(all_parsed_rows)

    if not parsed_rows:
        raise PriceListNormalizationError(
            "No price list rows could be extracted from the uploaded images."
        )

    raw_ocr_text = "\n\n--- NEXT IMAGE ---\n\n".join(all_raw_ocr_texts)

    try:
        matching_payload = match_price_list_rows(parsed_rows, detected_laundry_name)
    except Exception as exc:
        raise PriceListNormalizationError(f"Item matching step failed: {str(exc)}") from exc
    item_services = load_item_services()
    settings = get_settings()

    matched_items: list[MatchedPriceListRow] = []
    unmatched_items: list[UnmatchedPriceListRow] = []

    for item in matching_payload.items:
        if item.matched_item_type:
            services = item_services.get(item.matched_item_type)
            if services is None:
                raise PriceListNormalizationError(
                    f"Matched item type '{item.matched_item_type}' is missing service configuration."
                )

            matched_items.append(
                MatchedPriceListRow(
                    original_name=item.original_name,
                    price=item.price,
                    matched_item_type=item.matched_item_type,
                    confidence=item.confidence,
                    supported_services=services,
                )
            )
            continue

        unmatched_items.append(
            UnmatchedPriceListRow(
                original_name=item.original_name,
                price=item.price,
                reason=item.reason or "Could not confidently map item.",
            )
        )

    return NormalizedPriceListResponse(
        success=True,
        laundry_name=matching_payload.laundry_name or detected_laundry_name,
        currency=settings.default_currency,
        source_file_urls=file_urls,
        items=matched_items,
        unmatched_items=unmatched_items,
        raw_ocr_text=raw_ocr_text,
    )

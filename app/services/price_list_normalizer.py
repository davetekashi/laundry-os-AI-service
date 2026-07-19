import tempfile

from app.core.config import get_settings
from app.schemas.price_list import (
    ExtractedPriceListItem,
    NormalizedPriceListResponse,
    ParsedPriceListRow,
)
from app.services.ocr import extract_image_text
from app.services.parser import (
    parse_laundry_name,
    parse_price_list_rows,
    parse_price_list_rows_with_llm,
)
from app.services.source_image import SourceImageError, download_source_image


class PriceListNormalizationError(Exception):
    pass


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
        try:
            file_bytes, suffix = await download_source_image(file_url)
        except SourceImageError as exc:
            raise PriceListNormalizationError(str(exc)) from exc

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
    settings = get_settings()

    return NormalizedPriceListResponse(
        success=True,
        laundry_name=detected_laundry_name,
        currency=settings.default_currency,
        source_file_urls=file_urls,
        items=[
            ExtractedPriceListItem(item_name=row.original_name, price=row.price)
            for row in parsed_rows
        ],
        raw_ocr_text=raw_ocr_text,
    )

import tempfile

from app.core.config import get_settings
from app.schemas.price_list import (
    ExtractedPriceListItem,
    NormalizedPriceListResponse,
)
from app.services.openai_price_list_extractor import extract_price_list_image
from app.services.parser import (
    has_sufficient_extraction_coverage,
)
from app.services.source_image import SourceImageError, download_source_image


class PriceListNormalizationError(Exception):
    pass


def row_identity(row: ExtractedPriceListItem) -> tuple[str, str]:
    return row.item_name.casefold(), row.price_text.casefold()


async def normalize_price_list(file_urls: list[str]) -> NormalizedPriceListResponse:
    if not file_urls:
        raise PriceListNormalizationError("At least one file URL is required.")

    all_raw_ocr_texts: list[str] = []
    all_parsed_rows: list[ExtractedPriceListItem] = []
    previous_page_rows: set[tuple[str, str]] = set()
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
                extraction = extract_price_list_image(temp_file.name)
            except Exception as exc:
                raise PriceListNormalizationError(
                    f"OpenAI image extraction failed for '{file_url}': {str(exc)}"
                ) from exc

        raw_ocr_text = extraction.raw_ocr_text
        all_raw_ocr_texts.append(raw_ocr_text)
        parsed_rows = extraction.items

        if not has_sufficient_extraction_coverage(raw_ocr_text, parsed_rows):
            raise PriceListNormalizationError(
                f"Price list extraction was incomplete for '{file_url}'. "
                "The image contains substantially more price records than were structured; "
                "please retry with a clearer image."
            )

        # Preserve duplicate rows printed on one page, but remove overlap from later images.
        all_parsed_rows.extend(
            row for row in parsed_rows if row_identity(row) not in previous_page_rows
        )
        previous_page_rows.update(row_identity(row) for row in parsed_rows)

        page_laundry_name = extraction.laundry_name
        if page_laundry_name and not detected_laundry_name:
            detected_laundry_name = page_laundry_name

    if not all_parsed_rows:
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
            ExtractedPriceListItem(
                item_name=row.item_name,
                price=row.price,
                price_text=row.price_text,
            )
            for row in all_parsed_rows
        ],
        raw_ocr_text=raw_ocr_text,
    )

import tempfile

from app.core.config import get_settings
from app.schemas.price_list import (
    ExtractedPriceListItem,
    NormalizedPriceListResponse,
)
from app.services.openai_price_list_extractor import (
    PriceListDocumentRejectedError,
    extract_price_list_image,
    extract_price_list_text,
)
from app.services.parser import (
    has_sufficient_extraction_coverage,
)
from app.services.source_file import SourceFileError, download_source_file
from app.services.tabular_file import extract_tabular_text


class PriceListNormalizationError(Exception):
    pass


def row_identity(row: ExtractedPriceListItem) -> tuple[str, str]:
    return row.item_name.casefold(), row.price_text.casefold()


async def normalize_price_list(
    file_urls: list[str],
    available_services: list[str],
) -> NormalizedPriceListResponse:
    if not file_urls:
        raise PriceListNormalizationError("At least one file URL is required.")

    all_raw_ocr_texts: list[str] = []
    all_parsed_rows: list[ExtractedPriceListItem] = []
    previous_page_rows: set[tuple[str, str]] = set()
    detected_laundry_name: str | None = None

    for file_url in file_urls:
        try:
            source_file = await download_source_file(file_url)
        except SourceFileError as exc:
            raise PriceListNormalizationError(str(exc)) from exc

        if source_file.kind == "image":
            with tempfile.NamedTemporaryFile(
                delete=True, suffix=source_file.suffix
            ) as temp_file:
                temp_file.write(source_file.content)
                temp_file.flush()
                try:
                    extraction = extract_price_list_image(
                        temp_file.name,
                        available_services,
                    )
                except PriceListDocumentRejectedError as exc:
                    raise PriceListNormalizationError(str(exc)) from exc
                except Exception as exc:
                    raise PriceListNormalizationError(
                        f"OpenAI image extraction failed for '{file_url}': {str(exc)}"
                    ) from exc
        else:
            try:
                source_text = extract_tabular_text(
                    source_file.content,
                    source_file.kind,
                )
                extraction = extract_price_list_text(
                    source_text,
                    available_services,
                )
            except PriceListDocumentRejectedError as exc:
                raise PriceListNormalizationError(str(exc)) from exc
            except Exception as exc:
                raise PriceListNormalizationError(
                    f"Spreadsheet extraction failed for '{file_url}': {str(exc)}"
                ) from exc

        raw_ocr_text = extraction.raw_ocr_text
        all_raw_ocr_texts.append(raw_ocr_text)
        parsed_rows = extraction.items

        if not has_sufficient_extraction_coverage(raw_ocr_text, parsed_rows):
            raise PriceListNormalizationError(
                f"Price list extraction was incomplete for '{file_url}'. "
                "The source contains substantially more price records than were structured; "
                "please retry with a clearer or cleaner file."
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
            "No price list rows could be extracted from the uploaded files."
        )

    raw_ocr_text = "\n\n--- NEXT FILE ---\n\n".join(all_raw_ocr_texts)
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
                services=row.services,
            )
            for row in all_parsed_rows
        ],
        raw_ocr_text=raw_ocr_text,
    )

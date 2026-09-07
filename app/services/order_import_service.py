from app.schemas.order_import import (
    HistoricalOrderExtractionResponse,
    RejectedOrderSource,
)
from app.services.openai_order_extractor import (
    extract_orders_from_image,
    extract_orders_from_tabular_text,
)
from app.services.order_consolidator import (
    SourcedOrderDraft,
    consolidate_order_drafts,
)
from app.services.order_import_validator import classify_order_drafts
from app.services.pdf_file import render_pdf_pages
from app.services.source_file import SourceFileError, download_source_file
from app.services.tabular_file import extract_order_tabular_chunks


class HistoricalOrderExtractionError(Exception):
    pass


def _raw_section(file_url: str, label: str, text: str) -> str:
    return f"--- SOURCE: {file_url} | {label} ---\n{text.strip()}".strip()


def _append_extraction_drafts(
    destination: list[SourcedOrderDraft],
    extraction,
    *,
    file_url: str,
    page: int | None = None,
    sheet: str | None = None,
    row_numbers: list[int] | None = None,
) -> None:
    allowed_rows = set(row_numbers or [])
    for draft in extraction.orders:
        normalized_rows = (
            sorted(set(draft.source_row_numbers).intersection(allowed_rows))
            if allowed_rows
            else []
        )
        normalized = draft.model_copy(
            update={
                "source_page": page,
                "source_sheet": sheet,
                "source_row_numbers": normalized_rows,
            }
        )
        destination.append(
            SourcedOrderDraft(
                draft=normalized,
                file_url=file_url,
                page=page,
                sheet=sheet,
                row_numbers=normalized_rows,
            )
        )


async def extract_historical_orders(
    file_urls: list[str],
) -> HistoricalOrderExtractionResponse:
    if not file_urls:
        raise HistoricalOrderExtractionError("At least one file URL is required.")

    sourced_drafts: list[SourcedOrderDraft] = []
    rejected_sources: list[RejectedOrderSource] = []
    raw_sections: list[str] = []

    for file_url in file_urls:
        try:
            source_file = await download_source_file(file_url)
        except SourceFileError as exc:
            rejected_sources.append(
                RejectedOrderSource(file_url=file_url, reason=str(exc))
            )
            continue

        source_draft_count = len(sourced_drafts)
        source_rejection_reasons: list[str] = []

        try:
            if source_file.kind == "image":
                extraction = extract_orders_from_image(
                    source_file.content,
                    source_file.content_type.partition(";")[0] or "image/jpeg",
                )
                raw_sections.append(
                    _raw_section(file_url, "IMAGE", extraction.raw_extraction_text)
                )
                if extraction.is_order_source:
                    _append_extraction_drafts(
                        sourced_drafts,
                        extraction,
                        file_url=file_url,
                    )
                else:
                    source_rejection_reasons.append(
                        extraction.rejection_reason
                        or "The image does not contain historical laundry orders."
                    )

            elif source_file.kind == "pdf":
                pages = render_pdf_pages(source_file.content)
                for page in pages:
                    extraction = extract_orders_from_image(
                        page.image_content,
                        "image/png",
                        page_number=page.page_number,
                        embedded_text=page.extracted_text,
                    )
                    raw_text = extraction.raw_extraction_text or page.extracted_text
                    raw_sections.append(
                        _raw_section(file_url, f"PDF PAGE {page.page_number}", raw_text)
                    )
                    if extraction.is_order_source:
                        _append_extraction_drafts(
                            sourced_drafts,
                            extraction,
                            file_url=file_url,
                            page=page.page_number,
                        )
                    elif extraction.rejection_reason:
                        source_rejection_reasons.append(extraction.rejection_reason)

            elif source_file.kind in {"csv", "xlsx"}:
                chunks = extract_order_tabular_chunks(
                    source_file.content,
                    source_file.kind,
                )
                for chunk_index, chunk in enumerate(chunks, start=1):
                    extraction = extract_orders_from_tabular_text(
                        chunk.text,
                        sheet=chunk.sheet,
                        row_numbers=chunk.row_numbers,
                    )
                    label = (
                        f"SHEET {chunk.sheet} CHUNK {chunk_index}"
                        if chunk.sheet
                        else f"CSV CHUNK {chunk_index}"
                    )
                    raw_sections.append(_raw_section(file_url, label, chunk.text))
                    if extraction.is_order_source:
                        _append_extraction_drafts(
                            sourced_drafts,
                            extraction,
                            file_url=file_url,
                            sheet=chunk.sheet,
                            row_numbers=chunk.row_numbers,
                        )
                    elif extraction.rejection_reason:
                        source_rejection_reasons.append(extraction.rejection_reason)
            else:
                source_rejection_reasons.append(
                    f"Unsupported historical-order source kind '{source_file.kind}'."
                )
        except SourceFileError as exc:
            source_rejection_reasons.append(str(exc))
        except Exception as exc:
            raise HistoricalOrderExtractionError(
                f"Order extraction failed for '{file_url}': {str(exc)}"
            ) from exc

        if len(sourced_drafts) == source_draft_count:
            rejected_sources.append(
                RejectedOrderSource(
                    file_url=file_url,
                    reason=(
                        source_rejection_reasons[0]
                        if source_rejection_reasons
                        else "No genuine historical laundry orders were found in this source."
                    ),
                )
            )

    consolidated = consolidate_order_drafts(sourced_drafts)
    orders, review_required = classify_order_drafts(consolidated)
    return HistoricalOrderExtractionResponse(
        success=True,
        source_file_urls=file_urls,
        orders=orders,
        review_required=review_required,
        rejected_sources=rejected_sources,
        raw_extraction_text="\n\n".join(raw_sections),
    )

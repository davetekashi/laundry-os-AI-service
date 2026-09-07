from dataclasses import dataclass
import io

import pypdfium2 as pdfium

from app.services.source_file import SourceFileError


MAX_PDF_PAGES = 30
MAX_RENDERED_PDF_BYTES = 80 * 1024 * 1024


@dataclass(frozen=True)
class RenderedPdfPage:
    page_number: int
    image_content: bytes
    extracted_text: str


def render_pdf_pages(content: bytes) -> list[RenderedPdfPage]:
    try:
        document = pdfium.PdfDocument(content)
    except Exception as exc:
        raise SourceFileError(
            f"Failed to open PDF file. It may be corrupted or password-protected: {str(exc)}"
        ) from exc

    try:
        page_count = len(document)
        if page_count == 0:
            raise SourceFileError("The uploaded PDF contains no pages.")
        if page_count > MAX_PDF_PAGES:
            raise SourceFileError(
                f"PDF contains {page_count} pages; the limit is {MAX_PDF_PAGES}."
            )

        rendered_pages: list[RenderedPdfPage] = []
        rendered_size = 0
        for page_index in range(page_count):
            page = document.get_page(page_index)
            try:
                text_page = page.get_textpage()
                try:
                    extracted_text = text_page.get_text_bounded().strip()
                finally:
                    text_page.close()

                bitmap = page.render(scale=2)
                try:
                    image = bitmap.to_pil()
                    output = io.BytesIO()
                    image.save(output, format="PNG")
                    image_content = output.getvalue()
                finally:
                    bitmap.close()

                rendered_size += len(image_content)
                if rendered_size > MAX_RENDERED_PDF_BYTES:
                    raise SourceFileError(
                        "Rendered PDF pages exceed the 80 MB processing limit."
                    )
                rendered_pages.append(
                    RenderedPdfPage(
                        page_number=page_index + 1,
                        image_content=image_content,
                        extracted_text=extracted_text,
                    )
                )
            finally:
                page.close()
        return rendered_pages
    finally:
        document.close()

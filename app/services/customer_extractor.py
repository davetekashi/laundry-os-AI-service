import re
import tempfile

from app.schemas.customer import (
    CustomerExtractionResponse,
    ExtractedCustomer,
    UnresolvedCustomerRecord,
)
from app.services.customer_parser import parse_customers_with_llm
from app.services.ocr import extract_image_text
from app.services.source_image import SourceImageError, download_source_image


class CustomerExtractionError(Exception):
    pass


CUSTOMER_OCR_INSTRUCTION = (
    "Perform optical character recognition on this laundry customer-list image. "
    "Return all visible text as faithfully as possible, preserving customer rows, names, "
    "phone numbers, email addresses, column order, and line breaks. Do not summarize or infer missing values."
)


def _phone_identity(phone_number: str) -> str:
    return re.sub(r"\D", "", phone_number)


def deduplicate_customers(
    customers: list[ExtractedCustomer],
) -> tuple[list[ExtractedCustomer], list[UnresolvedCustomerRecord]]:
    deduplicated: list[ExtractedCustomer] = []
    indexes_by_phone: dict[str, int] = {}
    conflicts: list[UnresolvedCustomerRecord] = []

    for customer in customers:
        phone_key = _phone_identity(customer.phone_number)
        if not phone_key or phone_key not in indexes_by_phone:
            if phone_key:
                indexes_by_phone[phone_key] = len(deduplicated)
            deduplicated.append(customer)
            continue

        existing_index = indexes_by_phone[phone_key]
        existing = deduplicated[existing_index]
        same_name = existing.full_name.casefold() == customer.full_name.casefold()
        emails_compatible = (
            not existing.email
            or not customer.email
            or existing.email.casefold() == customer.email.casefold()
        )

        if same_name and emails_compatible:
            if existing.email is None and customer.email is not None:
                deduplicated[existing_index] = existing.model_copy(
                    update={"email": customer.email}
                )
            continue

        conflicts.append(
            UnresolvedCustomerRecord(
                raw_value=(
                    f"{customer.full_name} | {customer.phone_number}"
                    + (f" | {customer.email}" if customer.email else "")
                ),
                full_name=customer.full_name,
                phone_number=customer.phone_number,
                email=customer.email,
                reason="Conflicts with another extracted customer using the same phone number.",
            )
        )

    return deduplicated, conflicts


async def extract_customers(file_urls: list[str]) -> CustomerExtractionResponse:
    if not file_urls:
        raise CustomerExtractionError("At least one file URL is required.")

    raw_ocr_texts: list[str] = []

    for file_url in file_urls:
        try:
            file_bytes, suffix = await download_source_image(file_url)
        except SourceImageError as exc:
            raise CustomerExtractionError(f"{str(exc)} URL: '{file_url}'.") from exc

        with tempfile.NamedTemporaryFile(delete=True, suffix=suffix) as temp_file:
            temp_file.write(file_bytes)
            temp_file.flush()

            try:
                raw_ocr_text = extract_image_text(
                    temp_file.name,
                    extraction_instruction=CUSTOMER_OCR_INSTRUCTION,
                )
            except Exception as exc:
                raise CustomerExtractionError(
                    f"OCR step failed for '{file_url}': {str(exc)}"
                ) from exc

        raw_ocr_texts.append(raw_ocr_text)

    combined_ocr_text = "\n\n--- NEXT IMAGE ---\n\n".join(raw_ocr_texts)

    try:
        customers, unresolved_records = parse_customers_with_llm(combined_ocr_text)
    except Exception as exc:
        raise CustomerExtractionError(f"Customer parsing step failed: {str(exc)}") from exc

    customers, duplicate_conflicts = deduplicate_customers(customers)
    unresolved_records.extend(duplicate_conflicts)

    if not customers and not unresolved_records:
        raise CustomerExtractionError(
            "No customer records could be extracted from the uploaded image(s)."
        )

    return CustomerExtractionResponse(
        success=True,
        source_file_urls=file_urls,
        customers=customers,
        unresolved_records=unresolved_records,
        raw_ocr_text=combined_ocr_text,
    )

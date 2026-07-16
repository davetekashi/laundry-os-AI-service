import json

from openai import OpenAI

from app.core.config import get_settings
from app.schemas.customer import ExtractedCustomer, UnresolvedCustomerRecord


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned or None


def parse_customers_with_llm(
    raw_ocr_text: str,
) -> tuple[list[ExtractedCustomer], list[UnresolvedCustomerRecord]]:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    prompt = (
        "Extract customer records from the OCR text of one or more laundry customer-list images.\n"
        "Return strict JSON only with this shape:\n"
        '{"records": [{"raw_value": string, "full_name": string|null, '
        '"phone_number": string|null, "email": string|null, "reason": string|null}]}\n\n'
        "Rules:\n"
        "- Extract every genuine customer row in source order.\n"
        "- A customer may have no email; return null when email is absent.\n"
        "- Never invent a name, phone number, or email. Use null when a value is absent or illegible.\n"
        "- Preserve phone numbers as strings, including leading zeroes and explicit country prefixes.\n"
        "- Preserve names, phone numbers, and emails as faithfully as possible; only remove obvious OCR spacing.\n"
        "- raw_value must contain the source row or closest source text fragment for that record.\n"
        "- Set reason only when the name or phone number is missing or uncertain; otherwise return null.\n"
        "- Ignore headings, column labels, page numbers, and other non-customer text.\n"
        "- Text between NEXT IMAGE markers comes from separate images and may contain overlapping rows.\n\n"
        f"OCR text:\n{raw_ocr_text}"
    )

    response = client.chat.completions.create(
        model=settings.openai_matching_model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You accurately extract structured laundry customer records from OCR text and return JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("Customer parsing returned an empty response.")

    payload = json.loads(content)
    records = payload.get("records")
    if not isinstance(records, list):
        raise RuntimeError("Customer parsing response did not contain a records array.")

    customers: list[ExtractedCustomer] = []
    unresolved: list[UnresolvedCustomerRecord] = []

    for record in records:
        if not isinstance(record, dict):
            continue

        full_name = _optional_text(record.get("full_name"))
        phone_number = _optional_text(record.get("phone_number"))
        email = _optional_text(record.get("email"))
        raw_value = _optional_text(record.get("raw_value")) or "Unresolved OCR customer row"

        if full_name and phone_number:
            customers.append(
                ExtractedCustomer(
                    full_name=full_name,
                    phone_number=phone_number,
                    email=email,
                )
            )
            continue

        missing_fields: list[str] = []
        if not full_name:
            missing_fields.append("full name")
        if not phone_number:
            missing_fields.append("phone number")

        reason = _optional_text(record.get("reason"))
        if not reason:
            reason = f"Missing or unreadable {' and '.join(missing_fields)}."

        unresolved.append(
            UnresolvedCustomerRecord(
                raw_value=raw_value,
                full_name=full_name,
                phone_number=phone_number,
                email=email,
                reason=reason,
            )
        )

    return customers, unresolved

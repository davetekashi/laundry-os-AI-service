import json
import re

from openai import OpenAI

from app.core.config import get_settings
from app.schemas.price_list import ExtractedPriceListItem


PRICE_TEXT_PATTERN = re.compile(
    r"(?P<price_text>(?:(?:NGN|₦)\s*|(?<![A-Za-z])N\s+)?\d[\d,]*(?:\s*/\s*\d[\d,]*)*|\*+)\s*$",
    re.IGNORECASE,
)
SYNTHETIC_LABEL_PATTERN = re.compile(
    r"^(?:(?:row|line|item)\s*#?\s*\d+|\d+[.)])\s*[:.)-]?\s*",
    re.IGNORECASE,
)
THINK_BLOCK_PATTERN = re.compile(
    r"<think>.*?(?:</think>|$)",
    re.IGNORECASE | re.DOTALL,
)
NON_ITEM_LABELS = {
    "amount",
    "amount or prices",
    "description",
    "female description",
    "item",
    "items",
    "male description",
    "price",
    "prices",
}


def clean_item_name(value: str) -> str:
    value = value.strip(" -:\t")
    value = SYNTHETIC_LABEL_PATTERN.sub("", value)
    value = value.strip(" -*|:\t\"")
    value = re.sub(r"\s+", " ", value)
    return value


def clean_ocr_text(raw_ocr_text: str) -> str:
    return THINK_BLOCK_PATTERN.sub("", raw_ocr_text).strip()


def is_valid_item_name(item_name: str) -> bool:
    return bool(
        item_name
        and re.search(r"[A-Za-z]", item_name)
        and item_name.casefold() not in NON_ITEM_LABELS
    )


def estimate_price_record_count(raw_ocr_text: str) -> int:
    count = 0
    for raw_line in clean_ocr_text(raw_ocr_text).splitlines():
        line = raw_line.strip(" -|:\t\"")
        if not line:
            continue
        if PRICE_TEXT_PATTERN.fullmatch(line) or (
            re.search(r"[A-Za-z]", line) and PRICE_TEXT_PATTERN.search(line)
        ):
            count += 1
    return count


def has_sufficient_extraction_coverage(
    raw_ocr_text: str,
    rows: list[ExtractedPriceListItem],
) -> bool:
    estimated_count = estimate_price_record_count(raw_ocr_text)
    if estimated_count < 4:
        return bool(rows)
    return len(rows) >= max(2, int(estimated_count * 0.6))


def parse_single_numeric_price(price_text: str) -> int | None:
    normalized = re.sub(r"^(?:NGN|N|₦)\s*", "", price_text.strip(), flags=re.IGNORECASE)
    if not re.fullmatch(r"\d[\d,]*", normalized):
        return None
    return int(normalized.replace(",", ""))


def parse_laundry_name(raw_ocr_text: str) -> str | None:
    lines = [line.strip() for line in clean_ocr_text(raw_ocr_text).splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if "PRICE LIST" not in line.upper():
            continue
        if index > 0:
            return lines[index - 1]
        return None
    return None


def parse_price_list_rows(raw_ocr_text: str) -> list[ExtractedPriceListItem]:
    """Best-effort fallback for OCR that already has one complete row per line."""
    rows: list[ExtractedPriceListItem] = []

    for raw_line in clean_ocr_text(raw_ocr_text).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        upper_line = line.upper()
        if "PRICE LIST" in upper_line:
            continue
        if upper_line in {"ITEMS", "AMOUNT OR PRICES"}:
            continue
        if "ITEM" in upper_line and "AMOUNT" in upper_line:
            continue

        price_match = PRICE_TEXT_PATTERN.search(line)
        if not price_match:
            continue

        price_text = price_match.group("price_text").strip()
        name_text = clean_item_name(line[: price_match.start()])
        if not is_valid_item_name(name_text):
            continue

        rows.append(
            ExtractedPriceListItem(
                item_name=name_text,
                price=parse_single_numeric_price(price_text),
                price_text=price_text,
            )
        )

    return rows


def parse_price_list_rows_with_llm(raw_ocr_text: str) -> list[ExtractedPriceListItem]:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    estimated_count = estimate_price_record_count(raw_ocr_text)
    prompt = (
        "You are extracting structured rows from OCR text of a laundry price list.\n"
        "Return strict JSON only with this shape:\n"
        '{\n'
        '  "items": [\n'
        "    {\n"
        '      "item_name": string,\n'
        '      "price": integer|null,\n'
        '      "price_text": string\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Extract every genuine item/price record in source order.\n"
        "- Handle side-by-side and multi-column tables; associate each price with the item in its own column.\n"
        "- Preserve item_name exactly as printed, apart from obvious OCR spacing.\n"
        "- item_name must contain only the actual item or service name. Never add Row 1, Line 2, Item 3, "
        "bullet numbers, column names, commentary, or explanatory text.\n"
        "- Preserve the source price expression in price_text, including commas, slashes, currency symbols, "
        "asterisks, or other visible markers.\n"
        "- Set price to an integer only when price_text contains exactly one unambiguous numeric amount.\n"
        "- Set price to null for multiple values such as 800 / 700 or 3000/4000/5000, and for non-numeric "
        "values such as *******.\n"
        "- Keep separately printed duplicate rows; do not merge male and female columns.\n"
        "- Ignore headings, addresses, phone numbers, titles, table labels, OCR analysis, and transcription commentary.\n"
        "- Do not invent, rename, categorize, normalize, or match items.\n\n"
        f"The OCR appears to contain approximately {estimated_count} item-price records. "
        "Use that only as a completeness check; do not invent records to reach the estimate.\n\n"
        "OCR text:\n"
        f"{clean_ocr_text(raw_ocr_text)}"
    )

    response = client.chat.completions.create(
        model=settings.openai_matching_model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "You extract structured rows from OCR text and return valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("LLM parsing returned an empty response.")

    payload = json.loads(content)
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise RuntimeError("LLM parsing response did not contain an items array.")
    rows: list[ExtractedPriceListItem] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        item_name = clean_item_name(str(item.get("item_name") or ""))
        price_text = str(item.get("price_text") or "").strip()
        if not is_valid_item_name(item_name) or not price_text:
            continue

        rows.append(
            ExtractedPriceListItem(
                item_name=item_name,
                price=parse_single_numeric_price(price_text),
                price_text=price_text,
            )
        )

    return rows

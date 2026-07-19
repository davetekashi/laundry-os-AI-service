import json
import re

from openai import OpenAI

from app.core.config import get_settings
from app.schemas.price_list import ParsedPriceListRow


PRICE_PATTERN = re.compile(r"(?P<price>\d[\d,]*)\s*$")


def clean_item_name(value: str) -> str:
    value = value.strip(" -:\t")
    value = re.sub(r"\s+", " ", value)
    return value


def parse_laundry_name(raw_ocr_text: str) -> str | None:
    lines = [line.strip() for line in raw_ocr_text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if "PRICE LIST" not in line.upper():
            continue
        if index > 0:
            return lines[index - 1]
        return None
    return None


def parse_price_list_rows(raw_ocr_text: str) -> list[ParsedPriceListRow]:
    rows: list[ParsedPriceListRow] = []
    seen: set[tuple[str, int]] = set()

    for raw_line in raw_ocr_text.splitlines():
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

        price_match = PRICE_PATTERN.search(line)
        if not price_match:
            continue

        price_text = price_match.group("price")
        name_text = clean_item_name(line[: price_match.start()])
        if not name_text:
            continue

        price = int(price_text.replace(",", ""))
        row_key = (name_text.lower(), price)
        if row_key in seen:
            continue

        seen.add(row_key)
        rows.append(ParsedPriceListRow(original_name=name_text, price=price))

    return rows


def parse_price_list_rows_with_llm(raw_ocr_text: str) -> list[ParsedPriceListRow]:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    prompt = (
        "You are extracting structured rows from OCR text of a laundry price list.\n"
        "Return strict JSON only with this shape:\n"
        '{\n'
        '  "items": [\n'
        "    {\n"
        '      "original_name": string,\n'
        '      "price": integer\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Extract only real item rows that have a price.\n"
        "- Preserve the item wording as seen in the OCR text as much as possible.\n"
        "- Convert prices like 2,500 to 2500.\n"
        "- Ignore headers, titles, and table labels.\n"
        "- Do not invent rows.\n\n"
        "OCR text:\n"
        f"{raw_ocr_text}"
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
    rows: list[ParsedPriceListRow] = []
    seen: set[tuple[str, int]] = set()

    for item in items:
        row = ParsedPriceListRow.model_validate(item)
        row_key = (row.original_name.lower(), row.price)
        if row_key in seen:
            continue
        seen.add(row_key)
        rows.append(row)

    return rows

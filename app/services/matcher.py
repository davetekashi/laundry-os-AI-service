import json

from openai import OpenAI

from app.core.config import get_settings
from app.schemas.price_list import MatchingResultPayload, ParsedPriceListRow
from app.services.catalog import load_item_categories


def build_matching_prompt(rows: list[ParsedPriceListRow]) -> str:
    categories = load_item_categories()
    catalog_lines: list[str] = []
    for category in categories:
        catalog_lines.append(f"{category['name']}:")
        for item in category["items"]:
            catalog_lines.append(f"- {item}")

    rows_payload = [
        {"original_name": row.original_name, "price": row.price}
        for row in rows
    ]

    return (
        "You are matching laundry item labels from a price list to a fixed internal catalog.\n"
        "Choose exactly one best internal item type when the match is reasonably clear.\n"
        "If the label is too ambiguous to map safely, set matched_item_type to null and explain briefly in reason.\n"
        "Never invent item types outside the catalog.\n"
        "Return strict JSON only with this shape:\n"
        '{\n'
        '  "laundry_name": string | null,\n'
        '  "items": [\n'
        "    {\n"
        '      "original_name": string,\n'
        '      "price": integer,\n'
        '      "matched_item_type": string | null,\n'
        '      "confidence": number,\n'
        '      "reason": string | null\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Confidence must be between 0 and 1.\n"
        "Preserve original_name and price exactly as provided.\n\n"
        "Internal catalog:\n"
        f"{chr(10).join(catalog_lines)}\n\n"
        "Laundry rows to match:\n"
        f"{json.dumps(rows_payload, ensure_ascii=True, indent=2)}"
    )


def match_price_list_rows(
    rows: list[ParsedPriceListRow],
    laundry_name: str | None,
) -> MatchingResultPayload:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    prompt = build_matching_prompt(rows)
    if laundry_name:
        prompt = f"Detected laundry name: {laundry_name}\n\n{prompt}"

    response = client.chat.completions.create(
        model=settings.openai_matching_model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise data normalization assistant for a laundry operations platform. "
                    "You must respond with valid JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("OpenAI matching returned an empty response.")

    payload = MatchingResultPayload.model_validate_json(content)

    row_count_matches = len(payload.items) == len(rows)
    if not row_count_matches:
        raise RuntimeError("OpenAI matching returned a different number of rows than expected.")

    return payload


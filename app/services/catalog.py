import json
from functools import lru_cache
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
ITEM_TYPES_PATH = DATA_DIR / "internal_item_types.json"
ITEM_SERVICES_PATH = DATA_DIR / "item_services.json"


@lru_cache
def load_item_categories() -> list[dict]:
    with ITEM_TYPES_PATH.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return payload["categories"]


@lru_cache
def load_flat_item_types() -> list[str]:
    categories = load_item_categories()
    return [item for category in categories for item in category["items"]]


@lru_cache
def load_item_services() -> dict[str, list[str]]:
    with ITEM_SERVICES_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


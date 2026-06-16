import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    groq_api_key: str = Field(alias="GROQ_API_KEY")
    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    mongodb_uri: str = Field(alias="MONGODB_URI")
    groq_vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    openai_matching_model: str = "gpt-4.1"
    openai_chat_model: str = "gpt-4.1"
    default_currency: str = "NGN"


def load_dotenv_values() -> dict[str, str]:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    values: dict[str, str] = {}

    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    return values


@lru_cache
def get_settings() -> Settings:
    merged_values = load_dotenv_values()
    merged_values.update(os.environ)
    return Settings.model_validate(merged_values)

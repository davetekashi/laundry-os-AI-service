import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    mongodb_uri: str = Field(alias="MONGODB_URI")
    r2_access_key_id: str = Field(alias="R2_ACCESS_KEY_ID")
    r2_secret_access_key: str = Field(alias="R2_SECRET_ACCESS_KEY")
    r2_endpoint: str = Field(alias="R2_ENDPOINT")
    r2_bucket_name: str = Field(alias="R2_BUCKET_NAME")
    openai_vision_model: str = Field(
        default="gpt-4.1",
        alias="OPENAI_VISION_MODEL",
    )
    openai_matching_model: str = "gpt-4.1"
    openai_chat_model: str = "gpt-4.1"
    default_currency: str = "NGN"
    report_download_url_expiry_seconds: int = 3600


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

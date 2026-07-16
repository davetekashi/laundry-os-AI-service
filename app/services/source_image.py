from pathlib import Path
from urllib.parse import urlparse

import httpx


class SourceImageError(Exception):
    pass


async def download_source_image(file_url: str) -> tuple[bytes, str]:
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(file_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SourceImageError(f"Failed to download source image: {str(exc)}") from exc

    content_type = response.headers.get("content-type", "").lower()
    if not content_type.startswith("image/"):
        raise SourceImageError(
            f"Source URL must point to an image. Received content-type '{content_type or 'unknown'}'."
        )

    if not response.content:
        raise SourceImageError("Downloaded source image is empty.")

    parsed_url = urlparse(file_url)
    suffix = Path(parsed_url.path).suffix or ".jpg"
    return response.content, suffix

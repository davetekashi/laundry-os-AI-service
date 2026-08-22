from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx


MAX_SOURCE_FILE_BYTES = 20 * 1024 * 1024
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class SourceFileError(Exception):
    pass


@dataclass(frozen=True)
class DownloadedSourceFile:
    content: bytes
    suffix: str
    kind: str
    content_type: str


def _content_disposition_suffix(header: str) -> str:
    for part in header.split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key.lower() in {"filename", "filename*"}:
            filename = unquote(value.strip().strip('"').split("''")[-1])
            return Path(filename).suffix.lower()
    return ""


def detect_source_kind(
    file_url: str,
    content_type: str,
    content_disposition: str,
    content: bytes,
) -> tuple[str, str]:
    url_suffix = Path(unquote(urlparse(file_url).path)).suffix.lower()
    suffix = url_suffix or _content_disposition_suffix(content_disposition)
    normalized_type = content_type.partition(";")[0].strip().lower()
    image_signature = (
        content.startswith(b"\xff\xd8\xff")
        or content.startswith(b"\x89PNG\r\n\x1a\n")
        or content.startswith((b"GIF87a", b"GIF89a"))
        or (content.startswith(b"RIFF") and content[8:12] == b"WEBP")
    )

    if normalized_type.startswith("image/") or suffix in IMAGE_SUFFIXES or image_signature:
        return "image", suffix if suffix in IMAGE_SUFFIXES else ".jpg"
    if (
        normalized_type
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        or suffix == ".xlsx"
        or content.startswith(b"PK\x03\x04")
    ):
        return "xlsx", ".xlsx"
    if normalized_type in {"text/csv", "application/csv", "text/plain"} or suffix == ".csv":
        return "csv", ".csv"

    raise SourceFileError(
        "Source URL must point to a supported image, CSV, or XLSX file. "
        f"Received content-type '{content_type or 'unknown'}' and extension '{suffix or 'unknown'}'."
    )


async def download_source_file(file_url: str) -> DownloadedSourceFile:
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(file_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SourceFileError(f"Failed to download source file: {str(exc)}") from exc

    if not response.content:
        raise SourceFileError("Downloaded source file is empty.")
    if len(response.content) > MAX_SOURCE_FILE_BYTES:
        raise SourceFileError("Source file exceeds the 20 MB size limit.")

    content_type = response.headers.get("content-type", "").lower()
    kind, suffix = detect_source_kind(
        file_url,
        content_type,
        response.headers.get("content-disposition", ""),
        response.content,
    )
    return DownloadedSourceFile(
        content=response.content,
        suffix=suffix,
        kind=kind,
        content_type=content_type,
    )

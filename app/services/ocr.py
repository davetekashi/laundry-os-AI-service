import base64
import mimetypes
from pathlib import Path

from openai import OpenAI

from app.core.config import get_settings


def encode_image(file_path: str) -> str:
    return base64.b64encode(Path(file_path).read_bytes()).decode("utf-8")


def extract_image_text(file_path: str, extraction_instruction: str | None = None) -> str:
    """
    Extract text from an image using the configured OpenAI vision model.
    """

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    try:
        base64_image = encode_image(file_path)
        media_type = mimetypes.guess_type(file_path)[0] or "image/jpeg"
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": extraction_instruction
                            or (
                                "Transcribe only the visible text in this laundry price list image. "
                                "Preserve table headers, columns, row associations, item names, punctuation, "
                                "and price expressions exactly as shown. Do not analyze, explain, summarize, "
                                "number rows, add line labels, add commentary, or output thinking."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{base64_image}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            model=settings.openai_vision_model,
            max_completion_tokens=8192,
            temperature=0,
        )
        content = chat_completion.choices[0].message.content
        if not content:
            raise RuntimeError("OpenAI vision OCR returned an empty response.")
        return content
    except Exception as exc:
        raise RuntimeError(f"Image OCR failed: {str(exc)}") from exc

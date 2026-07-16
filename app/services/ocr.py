import base64
from pathlib import Path

from groq import Groq

from app.core.config import get_settings


def encode_image(file_path: str) -> str:
    return base64.b64encode(Path(file_path).read_bytes()).decode("utf-8")


def extract_image_text(file_path: str, extraction_instruction: str | None = None) -> str:
    """
    Extract text from an image using the configured Groq vision model.
    """

    settings = get_settings()
    client = Groq(api_key=settings.groq_api_key)

    try:
        base64_image = encode_image(file_path)
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": extraction_instruction
                            or (
                                "Perform optical character recognition on this laundry price list image. "
                                "Return the exact text content as faithfully as possible."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                            },
                        },
                    ],
                }
            ],
            model=settings.groq_vision_model,
        )
        content = chat_completion.choices[0].message.content
        if not content:
            raise RuntimeError("Groq OCR returned an empty response.")
        return content
    except Exception as exc:
        raise RuntimeError(f"Image OCR failed: {str(exc)}") from exc

import json

from openai import OpenAI

from app.core.config import get_settings
from app.schemas.chat import ChatResponse
from app.services.context_cache import get_context


class ChatServiceError(Exception):
    pass


def build_chat_prompt(context: dict, message: str) -> str:
    return (
        "You are the laundry managers best friend, you are a friendly assistant that helps them understand their business and relate with them in an empathetic way.\n"
        "Answer the their questions using only the contextual information about the laundry below\n"
        "Be concise, business-aware, and empathetic\n"
        "If the answer is not supported by the context, say clearly that the current prepared context does not contain enough information.\n\n"
        "Prepared laundry context:\n"
        f"{json.dumps(context, ensure_ascii=True, indent=2)}\n\n"
        f"User question: {message}"
    )


def answer_laundry_question(laundry_id: str, message: str) -> ChatResponse:
    snapshot = get_context(laundry_id)
    if not snapshot:
        raise ChatServiceError("Context for this laundry has not been prepared.")

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise assistant for laundry business operations. "
                    "Use only the provided context and do not invent missing facts."
                ),
            },
            {
                "role": "user",
                "content": build_chat_prompt(snapshot.context, message),
            },
        ],
    )

    answer = response.choices[0].message.content
    if not answer:
        raise ChatServiceError("OpenAI chat returned an empty response.")

    return ChatResponse(
        success=True,
        laundry_id=laundry_id,
        prepared_at=snapshot.prepared_at,
        answer=answer.strip(),
    )

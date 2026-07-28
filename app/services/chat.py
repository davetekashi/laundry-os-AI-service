import json

from openai import OpenAI

from app.core.config import get_settings
from app.schemas.context import ContextRole
from app.schemas.chat import ChatResponse
from app.services.context_cache import get_context


class ChatServiceError(Exception):
    pass


CHAT_SYSTEM_PROMPT = (
    "You are an embedded operating partner within this laundry business. "
    "You understand its activity, customers, and operations through the supplied business context, "
    "and you communicate as someone already familiar with the business rather than as an outside assistant receiving a task. "
    "Understand what the user is really trying to know, then offer the most useful perspective for that moment. "
    "Exercise judgment about what matters, what deserves attention, and how much detail is appropriate. "
    "Communicate naturally, calmly, and with genuine familiarity; let empathy come from understanding the business situation. "
    "Enter into the substance of the conversation instead of narrating the act of answering, and structure each response according to the question rather than a fixed format. "
    "Use only facts supported by the supplied context, be honest when it cannot support a conclusion, and enforce the user's access policy."
)


def build_chat_prompt(context: dict, role: ContextRole, message: str) -> str:
    role_instruction = (
        "The authenticated user is staff. Do not answer questions about revenue, collections, payment amounts, "
        "debts, bank accounts, wallets, expenses, profitability, settlements, commissions, or financial reconciliation. "
        "If asked, explain briefly that financial information is restricted to owners."
        if role == ContextRole.STAFF
        else "The authenticated user is the laundry owner and may receive all facts present in the prepared context."
    )
    return (
        f"Access policy: {role_instruction}\n\n"
        "Business context:\n"
        f"{json.dumps(context, ensure_ascii=True, indent=2)}\n\n"
        f"User message: {message}"
    )


def answer_laundry_question(
    laundry_id: str,
    role: ContextRole,
    message: str,
) -> ChatResponse:
    snapshot = get_context(laundry_id, role)
    if not snapshot:
        raise ChatServiceError(
            f"Context for this laundry and role '{role.value}' has not been prepared."
        )

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=[
            {
                "role": "system",
                "content": CHAT_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": build_chat_prompt(snapshot.context, role, message),
            },
        ],
    )

    answer = response.choices[0].message.content
    if not answer:
        raise ChatServiceError("OpenAI chat returned an empty response.")

    return ChatResponse(
        success=True,
        laundry_id=laundry_id,
        role=role,
        prepared_at=snapshot.prepared_at,
        answer=answer.strip(),
    )

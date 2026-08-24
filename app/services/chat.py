import json

from openai import OpenAI

from app.core.config import get_settings
from app.schemas.context import ContextRole
from app.schemas.chat import ChatResponse
from app.services.context_cache import get_context


class ChatServiceError(Exception):
    pass


CHAT_SYSTEM_PROMPT = (
    "You are Anne, the Seanosis AI Manager and an embedded operating partner within this laundry business. "
    "Anne is your identity, not a performance or a cue to introduce yourself repeatedly; let it show naturally through continuity, familiarity, and sound managerial judgment. "
    "You understand its activity, customers, and operations through the supplied business context, "
    "and you communicate as someone already familiar with the business rather than as an outside assistant receiving a task. "
    "Understand what the user is really trying to know, then offer the most useful perspective for that moment. "
    "Exercise judgment about what matters, what deserves attention, and how much detail is appropriate. "
    "Communicate naturally, calmly, and with genuine familiarity; let empathy come from understanding the business situation. "
    "When conversation_identity includes owner_first_name, understand that it identifies the owner you are speaking with; use only that first name when personal address feels natural, without forcing it into every response. "
    "The laundry_name identifies the business and must not be used as though it were the person's name. "
    "When access_scope.level is business, all aggregate domains represent the whole business and business_structure is authoritative for branch counts and comparisons; when it is branch, do not generalize branch figures to the whole business. "
    "Enter into the substance of the conversation instead of narrating the act of answering, and structure each response according to the question rather than a fixed format. "
    "Treat the supplied business context as the sole source of truth for claims about this specific laundry, including its customers, orders, operations, staff, and finances; never invent, estimate, or silently fill gaps in those facts. "
    "For general conversation, explanations, brainstorming, and laundry or business-management guidance, use your broader knowledge and judgment naturally without requiring the answer to appear in the business context. "
    "Keep that distinction clear: general guidance must not be presented as a known fact about this laundry, and when the user asks for a laundry-specific conclusion the context cannot support, say what is not known. "
    "Do not claim access to live external information such as current laws, prices, market conditions, or recent events when it has not been supplied. "
    "The user's access policy always takes precedence, including when a restricted question could otherwise be answered from general knowledge."
)


def build_chat_prompt(context: dict, role: ContextRole, message: str) -> str:
    if role == ContextRole.STAFF:
        role_instruction = (
            "The authenticated user is staff. Do not answer questions about revenue, collections, payment amounts, "
            "debts, bank accounts, wallets, expenses, profitability, settlements, commissions, or financial reconciliation. "
            "If asked, explain briefly that financial information is restricted to owners."
        )
    elif role == ContextRole.BUSINESS_MANAGER:
        role_instruction = (
            "The authenticated user is a business manager with owner-level information access and may receive all facts present in the prepared context."
        )
    else:
        role_instruction = (
            "The authenticated user is the business owner and may receive all facts present in the prepared context."
        )
    return (
        f"Access policy: {role_instruction}\n\n"
        "Business context:\n"
        f"{json.dumps(context, ensure_ascii=True, indent=2)}\n\n"
        f"User message: {message}"
    )


def answer_laundry_question(
    laundry_id: str | None,
    role: ContextRole,
    message: str,
    business_id: str | None = None,
) -> ChatResponse:
    snapshot = get_context(laundry_id, role, business_id)
    if not snapshot:
        raise ChatServiceError(
            f"Context for this business scope and role '{role.value}' has not been prepared."
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
        laundry_id=snapshot.laundry_id,
        business_id=snapshot.business_id,
        branch_id=snapshot.branch_id,
        scope_mode=snapshot.scope_mode,
        role=role,
        prepared_at=snapshot.prepared_at,
        answer=answer.strip(),
    )

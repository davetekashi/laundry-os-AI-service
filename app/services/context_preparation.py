from datetime import UTC, datetime

from app.schemas.context import ContextSnapshot, PrepareContextResponse
from app.services.context_builder import build_context_summary
from app.services.context_cache import set_context
from app.services.mongo import fetch_laundry_context_documents


class ContextPreparationError(Exception):
    pass


def prepare_laundry_context(laundry_id: str) -> PrepareContextResponse:
    try:
        raw_context = fetch_laundry_context_documents(laundry_id)
    except ValueError as exc:
        raise ContextPreparationError(str(exc)) from exc
    except Exception as exc:
        raise ContextPreparationError("Failed to load laundry context from MongoDB.") from exc

    prepared_at = datetime.now(UTC).isoformat()
    context = build_context_summary(raw_context)
    snapshot = ContextSnapshot(
        laundry_id=laundry_id,
        prepared_at=prepared_at,
        context=context,
    )
    set_context(snapshot)

    summary = {
        "laundry_name": context["laundry_profile"].get("laundry_name"),
        "total_customers": context["customers"].get("total_customers", 0),
        "total_orders": context["orders"].get("total_orders", 0),
        "total_payments": context["payments"].get("total_payments", 0),
        "total_debt_records": context["debts"].get("total_debt_records", 0),
    }

    return PrepareContextResponse(
        success=True,
        laundry_id=laundry_id,
        prepared_at=prepared_at,
        summary=summary,
    )

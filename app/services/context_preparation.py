from datetime import UTC, datetime

from app.schemas.context import ContextRole, ContextSnapshot, PrepareContextResponse
from app.services.context_builder import build_context_summary
from app.services.context_cache import set_context
from app.services.mongo import fetch_laundry_context_documents


class ContextPreparationError(Exception):
    pass


def prepare_laundry_context(
    laundry_id: str,
    role: ContextRole,
) -> PrepareContextResponse:
    try:
        raw_context = fetch_laundry_context_documents(laundry_id, role)
    except ValueError as exc:
        raise ContextPreparationError(str(exc)) from exc
    except Exception as exc:
        raise ContextPreparationError("Failed to load laundry context from MongoDB.") from exc

    prepared_at = datetime.now(UTC).isoformat()
    context = build_context_summary(raw_context, role)
    snapshot = ContextSnapshot(
        laundry_id=laundry_id,
        role=role,
        prepared_at=prepared_at,
        context=context,
    )
    set_context(snapshot)

    summary: dict = {
        "laundry_name": context["laundry_profile"].get("laundry_name"),
        "total_customers": context["customers"].get("total_customers", 0),
        "total_orders": context["orders"].get("total_orders", 0),
    }
    if role == ContextRole.OWNER:
        summary.update(
            {
                "total_payment_events": context["payments"].get(
                    "total_payment_events", 0
                ),
                "total_debt_records": context["debts"].get(
                    "total_debt_records", 0
                ),
            }
        )
    else:
        summary["total_logistics_jobs"] = context["logistics"].get(
            "total_logistics_jobs", 0
        )

    return PrepareContextResponse(
        success=True,
        laundry_id=laundry_id,
        role=role,
        prepared_at=prepared_at,
        summary=summary,
    )

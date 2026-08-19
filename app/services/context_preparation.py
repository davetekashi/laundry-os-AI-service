from datetime import UTC, datetime

from app.schemas.context import ContextRole, ContextSnapshot, PrepareContextResponse
from app.services.context_builder import build_context_summary
from app.services.context_cache import set_context
from app.services.mongo import fetch_laundry_context_documents


class ContextPreparationError(Exception):
    pass


def prepare_laundry_context(
    laundry_id: str | None,
    role: ContextRole,
    business_id: str | None = None,
) -> PrepareContextResponse:
    try:
        raw_context = fetch_laundry_context_documents(
            laundry_id,
            role,
            business_id,
        )
    except ValueError as exc:
        raise ContextPreparationError(str(exc)) from exc
    except Exception as exc:
        raise ContextPreparationError("Failed to load laundry context from MongoDB.") from exc

    prepared_at = datetime.now(UTC).isoformat()
    scope = raw_context.pop("_scope")
    context = build_context_summary(raw_context, role)
    snapshot = ContextSnapshot(
        laundry_id=str(scope.laundry_id),
        business_id=str(scope.business_id) if scope.business_id else None,
        scope_mode=scope.mode,
        cache_key=scope.cache_key,
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
        laundry_id=str(scope.laundry_id),
        business_id=str(scope.business_id) if scope.business_id else None,
        scope_mode=scope.mode,
        role=role,
        prepared_at=prepared_at,
        summary=summary,
    )

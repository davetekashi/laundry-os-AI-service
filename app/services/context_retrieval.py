import json
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any

from app.schemas.context import ContextRole, ContextSnapshot
from app.schemas.retrieval import (
    RetrievalDomain,
    RetrievalOperation,
    RetrievalQuery,
)


FINANCIAL_DOMAINS = {
    RetrievalDomain.PAYMENTS,
    RetrievalDomain.EXPENSES,
    RetrievalDomain.DEBTS,
    RetrievalDomain.SETTLEMENTS,
}
CONFIRMED_PAYMENT_STATUSES = {
    "confirmed",
    "completed",
    "paid",
    "success",
    "successful",
}


def retrieval_tool_definition(role: ContextRole) -> dict:
    available_domains = [domain.value for domain in RetrievalDomain]
    if not role.has_financial_access:
        available_domains = [
            domain
            for domain in available_domains
            if RetrievalDomain(domain) not in FINANCIAL_DOMAINS
        ]
    return {
        "type": "function",
        "function": {
            "name": "retrieve_business_data",
            "description": (
                "Retrieve exact prepared business records. Use this whenever the user asks for a complete or "
                "specific list, searches for a record, asks about a date range such as today/last week/last "
                "month, requests a comparison, or needs detail that is not present in the compact overview. "
                "Do not infer exact business facts from the overview when this tool can retrieve them. For a "
                "business-performance question retrieve orders for billed activity, payments for confirmed cash "
                "collections, expenses for recorded costs, and customers when customer activity is relevant."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domains": {
                        "type": "array",
                        "items": {"type": "string", "enum": available_domains},
                        "minItems": 1,
                        "maxItems": len(available_domains),
                        "description": (
                            "Business datasets needed: orders are billed activity, payments are cash collections, "
                            "expenses are costs, debts are outstanding balances, and customers are customer records."
                        ),
                    },
                    "operation": {
                        "type": "string",
                        "enum": [operation.value for operation in RetrievalOperation],
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Inclusive ISO date YYYY-MM-DD for the main period.",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Inclusive ISO date YYYY-MM-DD for the main period.",
                    },
                    "comparison_start_date": {
                        "type": "string",
                        "description": "Inclusive ISO date for the comparison period.",
                    },
                    "comparison_end_date": {
                        "type": "string",
                        "description": "Inclusive ISO date for the comparison period.",
                    },
                    "search_text": {
                        "type": "string",
                        "description": "Name, phone, email, order code, or other text to find.",
                    },
                    "statuses": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional statuses to include.",
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["date", "amount", "name"],
                    },
                    "sort_order": {
                        "type": "string",
                        "enum": ["ascending", "descending"],
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 250,
                        "description": (
                            "Maximum detailed records. Use 250 when the user explicitly asks for all records."
                        ),
                    },
                    "offset": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Number of matching records to skip for pagination.",
                    },
                },
                "required": ["domains", "operation"],
                "additionalProperties": False,
            },
        },
    }


def _iso_date(value: str | None, field_name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date in YYYY-MM-DD format.") from exc


def _record_date(record: dict) -> date | None:
    value = record.get("event_at")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _matches_status(record: dict, statuses: set[str]) -> bool:
    if not statuses:
        return True
    values = {
        str(record.get(field) or "").casefold()
        for field in ("status", "order_status", "payment_status")
    }
    return bool(values & statuses)


def _filter_records(
    records: list[dict],
    start_date: date | None,
    end_date: date | None,
    search_text: str | None,
    statuses: list[str],
) -> list[dict]:
    search = search_text.strip().casefold() if search_text else None
    normalized_statuses = {status.casefold() for status in statuses}
    selected: list[dict] = []
    for record in records:
        record_date = _record_date(record)
        if start_date and (record_date is None or record_date < start_date):
            continue
        if end_date and (record_date is None or record_date > end_date):
            continue
        if search and search not in json.dumps(record, ensure_ascii=True).casefold():
            continue
        if not _matches_status(record, normalized_statuses):
            continue
        selected.append(record)
    return selected


def _number(record: dict, field: str) -> float:
    try:
        return float(record.get(field, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _domain_metrics(domain: RetrievalDomain, records: list[dict]) -> dict[str, Any]:
    metrics: dict[str, Any] = {"record_count": len(records)}
    if domain == RetrievalDomain.CUSTOMERS:
        metrics.update(
            {
                "active_customers": sum(1 for row in records if row.get("is_active")),
                "inactive_customers": sum(
                    1 for row in records if not row.get("is_active")
                ),
            }
        )
    elif domain == RetrievalDomain.ORDERS:
        customer_order_counts = Counter(
            str(row.get("customer_id") or row.get("customer_name") or "unknown")
            for row in records
        )
        known_customer_counts = {
            customer: count
            for customer, count in customer_order_counts.items()
            if customer != "unknown"
        }
        metrics.update(
            {
                "order_value": sum(_number(row, "total_payable") for row in records),
                "amount_paid": sum(
                    _number(row, "total_amount_paid") for row in records
                ),
                "balance_due": sum(
                    _number(row, "total_balance_due") for row in records
                ),
                "item_lines": sum(int(_number(row, "item_count")) for row in records),
                "physical_pieces": sum(
                    int(_number(row, "total_piece_count")) for row in records
                ),
                "unique_customers": len(known_customer_counts),
                "repeat_customers": sum(
                    1 for count in known_customer_counts.values() if count > 1
                ),
                "order_statuses": dict(
                    Counter(str(row.get("order_status") or "unknown") for row in records)
                ),
                "payment_statuses": dict(
                    Counter(
                        str(row.get("payment_status") or "unknown") for row in records
                    )
                ),
            }
        )
    elif domain == RetrievalDomain.PAYMENTS:
        confirmed = [
            row
            for row in records
            if str(row.get("status") or "").casefold() in CONFIRMED_PAYMENT_STATUSES
        ]
        metrics.update(
            {
                "confirmed_payment_count": len(confirmed),
                "confirmed_collection_total": sum(
                    (-1 if str(row.get("transaction_type") or "").casefold() == "refund" else 1)
                    * _number(row, "amount")
                    for row in confirmed
                ),
                "refund_total": sum(
                    _number(row, "amount")
                    for row in confirmed
                    if str(row.get("transaction_type") or "").casefold() == "refund"
                ),
                "methods": dict(
                    Counter(str(row.get("method") or "unknown") for row in confirmed)
                ),
            }
        )
    elif domain == RetrievalDomain.EXPENSES:
        metrics.update(
            {
                "expense_total": sum(_number(row, "amount") for row in records),
                "categories": dict(
                    Counter(str(row.get("category") or "Uncategorized") for row in records)
                ),
                "category_totals": dict(
                    _sum_by(records, "category", "amount", "Uncategorized")
                ),
            }
        )
    elif domain == RetrievalDomain.DEBTS:
        metrics.update(
            {
                "total_amount": sum(_number(row, "total_amount") for row in records),
                "amount_paid": sum(_number(row, "amount_paid") for row in records),
                "balance_due": sum(_number(row, "balance_due") for row in records),
            }
        )
    elif domain == RetrievalDomain.SETTLEMENTS:
        metrics.update(
            {
                "settlement_total": sum(_number(row, "amount") for row in records),
                "statuses": dict(
                    Counter(str(row.get("status") or "unknown") for row in records)
                ),
            }
        )
    elif domain == RetrievalDomain.MEMBERS:
        metrics.update(
            {
                "active_members": sum(1 for row in records if row.get("is_active")),
                "roles": dict(
                    Counter(str(row.get("role") or "unknown") for row in records)
                ),
            }
        )
    elif domain == RetrievalDomain.LOGISTICS:
        metrics["statuses"] = dict(
            Counter(str(row.get("status") or "unknown") for row in records)
        )
    return metrics


def _sum_by(
    records: list[dict],
    key_field: str,
    value_field: str,
    default_key: str,
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for record in records:
        totals[str(record.get(key_field) or default_key)] += _number(
            record, value_field
        )
    return totals


def _period_breakdown(domain: RetrievalDomain, records: list[dict]) -> dict:
    monthly: dict[str, list[dict]] = defaultdict(list)
    daily: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        record_date = _record_date(record)
        if record_date is None:
            continue
        monthly[record_date.strftime("%Y-%m")].append(record)
        daily[record_date.isoformat()].append(record)
    return {
        "monthly": {
            key: _domain_metrics(domain, rows) for key, rows in sorted(monthly.items())
        },
        "daily": {
            key: _domain_metrics(domain, rows) for key, rows in sorted(daily.items())
        },
    }


def _sort_records(records: list[dict], sort_by: str, descending: bool) -> list[dict]:
    if sort_by == "amount":
        fields = ("total_payable", "amount", "balance_due", "total_amount")

        def key(record: dict):
            return next((_number(record, field) for field in fields if field in record), 0)

    elif sort_by == "name":

        def key(record: dict):
            return str(
                record.get("full_name")
                or record.get("customer_name")
                or record.get("order_code")
                or ""
            ).casefold()

    else:

        def key(record: dict):
            return record.get("event_at") or ""

    return sorted(records, key=key, reverse=descending)


def _period_result(
    domain: RetrievalDomain,
    all_records: list[dict],
    query: RetrievalQuery,
    start_date: date | None,
    end_date: date | None,
) -> dict:
    selected = _filter_records(
        all_records,
        start_date,
        end_date,
        query.search_text,
        query.statuses,
    )
    selected = _sort_records(
        selected,
        query.sort_by,
        query.sort_order == "descending",
    )
    detail_limit = query.limit
    if query.operation in {
        RetrievalOperation.PERIOD_ANALYSIS,
        RetrievalOperation.COMPARISON,
    }:
        detail_limit = min(detail_limit, 20)
    return {
        "available_record_count": len(all_records),
        "matched_record_count": len(selected),
        "offset": query.offset,
        "returned_record_count": max(
            min(len(selected) - query.offset, detail_limit), 0
        ),
        "has_more": len(selected) > query.offset + detail_limit,
        "metrics": _domain_metrics(domain, selected),
        "period_breakdown": _period_breakdown(domain, selected),
        "records": selected[query.offset : query.offset + detail_limit],
    }


def _change(current: float, previous: float) -> dict:
    if previous == 0:
        return {
            "current": current,
            "previous": previous,
            "percentage_change": None,
            "note": "Percentage change is undefined because the comparison value is zero.",
        }
    return {
        "current": current,
        "previous": previous,
        "percentage_change": round(((current - previous) / previous) * 100, 2),
    }


def _numeric_comparison(current: dict, previous: dict) -> dict:
    result: dict[str, dict] = {}
    for key in current.keys() & previous.keys():
        if isinstance(current[key], (int, float)) and isinstance(
            previous[key], (int, float)
        ):
            result[key] = _change(float(current[key]), float(previous[key]))
    return result


def execute_retrieval(snapshot: ContextSnapshot, query: RetrievalQuery) -> dict:
    if not snapshot.role.has_financial_access and any(
        domain in FINANCIAL_DOMAINS for domain in query.domains
    ):
        raise ValueError("The authenticated role cannot retrieve financial domains.")

    start_date = _iso_date(query.start_date, "start_date")
    end_date = _iso_date(query.end_date, "end_date")
    comparison_start = _iso_date(
        query.comparison_start_date, "comparison_start_date"
    )
    comparison_end = _iso_date(query.comparison_end_date, "comparison_end_date")
    result: dict[str, Any] = {
        "scope": {
            "level": "branch" if snapshot.branch_id else "business",
            "business_id": snapshot.business_id,
            "branch_id": snapshot.branch_id,
            "prepared_at": snapshot.prepared_at,
        },
        "requested_period": {
            "start_date": query.start_date,
            "end_date": query.end_date,
        },
        "domains": {},
    }

    for domain in query.domains:
        records = snapshot.retrieval_data.get(domain.value, [])
        current = _period_result(domain, records, query, start_date, end_date)
        if comparison_start and comparison_end:
            previous = _period_result(
                domain,
                records,
                query,
                comparison_start,
                comparison_end,
            )
            current["comparison_period"] = {
                "start_date": query.comparison_start_date,
                "end_date": query.comparison_end_date,
                **previous,
            }
            current["metric_changes"] = _numeric_comparison(
                current["metrics"], previous["metrics"]
            )
        result["domains"][domain.value] = current

    domain_results = result["domains"]
    if any(
        key in domain_results for key in ("orders", "payments", "expenses")
    ):
        order_metrics = domain_results.get("orders", {}).get("metrics", {})
        payment_metrics = domain_results.get("payments", {}).get("metrics", {})
        expense_metrics = domain_results.get("expenses", {}).get("metrics", {})
        result["cross_domain_metrics"] = {
            "billed_order_value": order_metrics.get("order_value"),
            "confirmed_collections": payment_metrics.get(
                "confirmed_collection_total"
            ),
            "recorded_expenses": expense_metrics.get("expense_total"),
            "billed_less_expenses": (
                order_metrics.get("order_value", 0)
                - expense_metrics.get("expense_total", 0)
                if "orders" in domain_results and "expenses" in domain_results
                else None
            ),
            "collections_less_expenses": (
                payment_metrics.get("confirmed_collection_total", 0)
                - expense_metrics.get("expense_total", 0)
                if "payments" in domain_results and "expenses" in domain_results
                else None
            ),
        }
    return result

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime

from openai import OpenAI

from app.core.config import get_settings
from app.schemas.report import DebtRiskAnalysisResponse, ReportTable, WeeklySummaryReportResponse
from app.services.context_builder import (
    build_bank_account_summary,
    build_laundry_summary,
    build_logistics_summary,
    build_member_summary,
    build_wallet_summary,
    isoformat_or_none,
    sum_numbers,
)
from app.services.mongo import fetch_laundry_report_documents


class WeeklySummaryReportError(Exception):
    pass


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_mongo_datetime(value: datetime | None) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return ensure_utc(value)


def format_ngn(value: float) -> str:
    return f"NGN {int(round(value)):,}"


def format_outstanding_days(opened_at: datetime | None, end_date: datetime) -> str:
    opened_at = normalize_mongo_datetime(opened_at)
    if opened_at is None:
        return "Unknown age"

    days_outstanding = max((end_date.date() - opened_at.date()).days, 0)
    day_label = "day" if days_outstanding == 1 else "days"
    return f"{days_outstanding} {day_label} outstanding"


def build_weekly_customer_summary(
    customers: list[dict],
    weekly_orders: list[dict],
    all_orders: list[dict],
    start_date: datetime,
) -> dict:
    customer_map = {str(customer.get("_id")): customer for customer in customers}
    weekly_customer_ids = {
        str(order.get("laundryCustomerId"))
        for order in weekly_orders
        if order.get("laundryCustomerId")
    }

    repeat_count = 0
    new_customer_count = 0
    customer_has_prior_order: dict[str, bool] = {}
    for order in all_orders:
        customer_id = order.get("laundryCustomerId")
        created_at = normalize_mongo_datetime(order.get("createdAt"))
        if not customer_id or created_at is None:
            continue
        customer_key = str(customer_id)
        if created_at < start_date:
            customer_has_prior_order[customer_key] = True

    for customer_id in weekly_customer_ids:
        customer_record = customer_map.get(customer_id)
        customer_created_at = normalize_mongo_datetime(
            customer_record.get("createdAt") if customer_record else None
        )
        if customer_has_prior_order.get(customer_id):
            repeat_count += 1
        elif customer_created_at is not None and customer_created_at >= start_date:
            new_customer_count += 1
        else:
            new_customer_count += 1

    repeat_rate = 0.0
    if weekly_customer_ids:
        repeat_rate = (repeat_count / len(weekly_customer_ids)) * 100

    return {
        "active_customers_in_period": len(weekly_customer_ids),
        "new_customers_in_period": new_customer_count,
        "repeat_customers_in_period": repeat_count,
        "repeat_customer_rate": round(repeat_rate, 1),
    }


def build_weekly_debt_summary(
    all_debts: list[dict],
    start_date: datetime,
    end_date: datetime,
) -> dict:
    opened_in_period = [
        debt
        for debt in all_debts
        if (
            normalize_mongo_datetime(debt.get("openedAt")) is not None
            and start_date <= normalize_mongo_datetime(debt.get("openedAt")) <= end_date
        )
    ]
    settled_in_period = [
        debt
        for debt in all_debts
        if (
            normalize_mongo_datetime(debt.get("settledAt")) is not None
            and start_date <= normalize_mongo_datetime(debt.get("settledAt")) <= end_date
        )
    ]
    outstanding = [debt for debt in all_debts if float(debt.get("balanceDue", 0) or 0) > 0]
    status_counts = Counter(debt.get("status", "unknown") for debt in all_debts)

    return {
        "opened_count": len(opened_in_period),
        "opened_total_amount": sum_numbers(opened_in_period, "totalAmount"),
        "settled_count": len(settled_in_period),
        "settled_total_amount": sum_numbers(settled_in_period, "amountPaid"),
        "current_outstanding_count": len(outstanding),
        "current_outstanding_balance": sum_numbers(outstanding, "balanceDue"),
        "status_counts": dict(status_counts),
    }


def build_weekly_payment_summary(payments: list[dict]) -> dict:
    status_counts = Counter(payment.get("status", "unknown") for payment in payments)
    method_counts = Counter(payment.get("method", "unknown") for payment in payments)
    channel_counts = Counter(payment.get("paymentChannel", "unknown") for payment in payments)

    top_payers: dict[str, float] = defaultdict(float)
    for payment in payments:
        payer_name = payment.get("payerSnapshot", {}).get("fullName") or "Unknown"
        top_payers[payer_name] += float(payment.get("totalAmount", 0) or 0)

    return {
        "payment_count": len(payments),
        "total_amount_received": sum_numbers(payments, "totalAmount"),
        "status_counts": dict(status_counts),
        "method_counts": dict(method_counts),
        "payment_channel_counts": dict(channel_counts),
        "top_payers": [
            {"customer_name": name, "total_paid": total}
            for name, total in sorted(top_payers.items(), key=lambda item: item[1], reverse=True)[:5]
        ],
    }


def build_weekly_order_summary(orders: list[dict]) -> dict:
    order_status_counts = Counter(order.get("orderStatus", "unknown") for order in orders)
    payment_status_counts = Counter(order.get("paymentStatus", "unknown") for order in orders)
    service_mode_counts = Counter(
        order.get("fulfillmentInfo", {}).get("serviceMode", "unknown")
        for order in orders
    )

    return {
        "order_count": len(orders),
        "total_order_value": sum_numbers(orders, "totalPayable"),
        "total_amount_paid": sum_numbers(orders, "totalAmountPaid"),
        "total_balance_due": sum_numbers(orders, "totalBalanceDue"),
        "service_total": sum_numbers(orders, "serviceTotal"),
        "logistics_total": sum_numbers(orders, "logisticsTotal"),
        "item_volume": int(sum(int(order.get("itemCount", 0) or 0) for order in orders)),
        "pickup_completed_count": sum(1 for order in orders if order.get("pickupCompleted")),
        "return_completed_count": sum(1 for order in orders if order.get("returnCompleted")),
        "order_status_counts": dict(order_status_counts),
        "payment_status_counts": dict(payment_status_counts),
        "service_mode_counts": dict(service_mode_counts),
        "top_orders": [
            {
                "order_code": order.get("orderCode"),
                "customer_name": order.get("customerSnapshot", {}).get("fullName"),
                "total_payable": order.get("totalPayable", 0),
                "order_status": order.get("orderStatus"),
                "payment_status": order.get("paymentStatus"),
                "created_at": isoformat_or_none(order.get("createdAt")),
            }
            for order in sorted(
                orders,
                key=lambda row: float(row.get("totalPayable", 0) or 0),
                reverse=True,
            )[:5]
        ],
    }


def build_report_facts(raw_documents: dict, start_date: datetime, end_date: datetime) -> dict:
    laundry = raw_documents["laundry"]
    bank_account = raw_documents["bank_account"]
    wallet = raw_documents["wallet"]
    customers = raw_documents["customers"]
    members = raw_documents["members"]
    payments = raw_documents["payments_in_range"]
    orders = raw_documents["orders_in_range"]
    all_orders = raw_documents["all_orders"]
    all_debts = raw_documents["all_debts"]
    logistics_jobs = raw_documents["logistics_jobs_in_range"]

    return {
        "report_window": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "laundry_profile": build_laundry_summary(laundry),
        "bank_account": build_bank_account_summary(bank_account),
        "wallet": build_wallet_summary(wallet),
        "members": build_member_summary(members),
        "orders": build_weekly_order_summary(orders),
        "payments": build_weekly_payment_summary(payments),
        "customers": build_weekly_customer_summary(customers, orders, all_orders, start_date),
        "debts": build_weekly_debt_summary(all_debts, start_date, end_date),
        "logistics": build_logistics_summary(logistics_jobs, orders),
    }


def build_debt_risk_table(all_debts: list[dict], as_of_date: datetime) -> ReportTable:
    outstanding_debts = [
        debt
        for debt in all_debts
        if float(debt.get("balanceDue", 0) or 0) > 0
    ]

    sorted_debts = sorted(
        outstanding_debts,
        key=lambda debt: (
            -float(debt.get("balanceDue", 0) or 0),
            -max(
                (as_of_date.date() - normalize_mongo_datetime(debt.get("openedAt")).date()).days,
                0,
            )
            if normalize_mongo_datetime(debt.get("openedAt")) is not None
            else 0,
        ),
    )

    rows: list[list[str | int | float]] = []
    for debt in sorted_debts:
        customer_name = debt.get("customerSnapshot", {}).get("fullName") or "Unknown"
        balance_due = float(debt.get("balanceDue", 0) or 0)
        timeframe = format_outstanding_days(debt.get("openedAt"), as_of_date)
        rows.append([customer_name, format_ngn(balance_due), timeframe])

    return ReportTable(
        headers=["Customer", "Debt Owed", "Time Frame"],
        rows=rows,
    )


def build_debt_risk_facts(raw_documents: dict, as_of_date: datetime) -> dict:
    laundry = raw_documents["laundry"]
    all_debts = raw_documents["all_debts"]
    outstanding_debts = [
        debt
        for debt in all_debts
        if float(debt.get("balanceDue", 0) or 0) > 0
    ]

    customer_totals: dict[str, float] = defaultdict(float)
    aged_over_7 = 0
    aged_over_14 = 0
    age_days: list[int] = []

    for debt in outstanding_debts:
        customer_name = debt.get("customerSnapshot", {}).get("fullName") or "Unknown"
        balance_due = float(debt.get("balanceDue", 0) or 0)
        customer_totals[customer_name] += balance_due

        opened_at = normalize_mongo_datetime(debt.get("openedAt"))
        if opened_at is None:
            continue
        days_outstanding = max((as_of_date.date() - opened_at.date()).days, 0)
        age_days.append(days_outstanding)
        if days_outstanding > 7:
            aged_over_7 += 1
        if days_outstanding > 14:
            aged_over_14 += 1

    total_outstanding = float(sum(customer_totals.values()))
    top_debtors = sorted(
        customer_totals.items(),
        key=lambda row: row[1],
        reverse=True,
    )[:5]

    top_customer_share = 0.0
    if total_outstanding > 0 and top_debtors:
        top_customer_share = (top_debtors[0][1] / total_outstanding) * 100

    return {
        "report_generated_at": as_of_date.isoformat(),
        "debt_position_as_of": {
            "as_of": as_of_date.isoformat(),
        },
        "laundry_profile": build_laundry_summary(laundry),
        "debt_risk": {
            "outstanding_debt_count": len(outstanding_debts),
            "unique_indebted_customers": len(customer_totals),
            "total_outstanding_balance": total_outstanding,
            "average_debt_age_days": round(sum(age_days) / len(age_days), 1) if age_days else 0,
            "oldest_debt_age_days": max(age_days) if age_days else 0,
            "debts_older_than_7_days": aged_over_7,
            "debts_older_than_14_days": aged_over_14,
            "largest_customer_debt_share_percent": round(top_customer_share, 1),
            "top_debtors": [
                {"customer_name": customer_name, "balance_due": balance_due}
                for customer_name, balance_due in top_debtors
            ],
        },
    }


def build_weekly_summary_prompt(facts: dict) -> str:
    return (
        "You are preparing a weekly business summary report for a laundry operations platform.\n"
        "Write a concise but informative plain-text report using only the computed facts provided.\n"
        "Focus on what happened during the reporting window: orders, payments, customer activity, debt position, wallet posture, and operational signals.\n"
        "Do not invent facts. If a section has little activity, say so naturally.\n"
        "Keep the tone professional and useful for a business owner.\n"
        "Return plain text only, no markdown bullets.\n\n"
        "Computed report facts:\n"
        f"{json.dumps(facts, ensure_ascii=True, indent=2)}"
    )


def build_debt_risk_summary_prompt(facts: dict, table: ReportTable) -> str:
    return (
        "You are preparing a debt risk analysis report for a laundry operations platform.\n"
        "Write a concise plain-text analysis using only the computed facts and outstanding debt table provided.\n"
        "Explain the debt exposure, concentration risk, aging pattern, and any clear follow-up priorities.\n"
        "Do not invent facts. Return plain text only, no markdown bullets.\n\n"
        "Computed debt risk facts:\n"
        f"{json.dumps(facts, ensure_ascii=True, indent=2)}\n\n"
        "Outstanding debt table:\n"
        f"{json.dumps(table.model_dump(), ensure_ascii=True, indent=2)}"
    )


def generate_weekly_summary_text(facts: dict) -> str:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    response = client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You write clear weekly business summary reports for laundry operators. "
                    "Use only provided facts and return plain text only."
                ),
            },
            {
                "role": "user",
                "content": build_weekly_summary_prompt(facts),
            },
        ],
    )

    content = response.choices[0].message.content
    if not content:
        raise WeeklySummaryReportError("OpenAI weekly summary generation returned an empty response.")
    return content.strip()


def generate_debt_risk_summary_text(facts: dict, table: ReportTable) -> str:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    response = client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You write clear debt-risk analysis reports for laundry operators. "
                    "Use only provided facts and return plain text only."
                ),
            },
            {
                "role": "user",
                "content": build_debt_risk_summary_prompt(facts, table),
            },
        ],
    )

    content = response.choices[0].message.content
    if not content:
        raise WeeklySummaryReportError("OpenAI debt-risk summary generation returned an empty response.")
    return content.strip()


def generate_weekly_summary_report(
    laundry_id: str,
    start_date: datetime,
    end_date: datetime,
) -> WeeklySummaryReportResponse:
    start_date = ensure_utc(start_date)
    end_date = ensure_utc(end_date)

    try:
        raw_documents = fetch_laundry_report_documents(laundry_id, start_date, end_date)
    except ValueError as exc:
        raise WeeklySummaryReportError(str(exc)) from exc
    except Exception as exc:
        raise WeeklySummaryReportError("Failed to load report data from MongoDB.") from exc

    facts = build_report_facts(raw_documents, start_date, end_date)

    try:
        summary_text = generate_weekly_summary_text(facts)
    except WeeklySummaryReportError:
        raise
    except Exception as exc:
        raise WeeklySummaryReportError(
            f"Failed to generate weekly summary text: {str(exc)}"
        ) from exc

    return WeeklySummaryReportResponse(
        success=True,
        laundry_id=laundry_id,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        summary=summary_text,
    )


def generate_debt_risk_analysis_report(
    laundry_id: str,
) -> DebtRiskAnalysisResponse:
    as_of_date = datetime.now(UTC)

    try:
        historical_window_start = datetime(1970, 1, 1, tzinfo=UTC)
        raw_documents = fetch_laundry_report_documents(laundry_id, historical_window_start, as_of_date)
    except ValueError as exc:
        raise WeeklySummaryReportError(str(exc)) from exc
    except Exception as exc:
        raise WeeklySummaryReportError("Failed to load debt-risk data from MongoDB.") from exc

    table = build_debt_risk_table(raw_documents["all_debts"], as_of_date)
    facts = build_debt_risk_facts(raw_documents, as_of_date)

    try:
        summary_text = generate_debt_risk_summary_text(facts, table)
    except WeeklySummaryReportError:
        raise
    except Exception as exc:
        raise WeeklySummaryReportError(
            f"Failed to generate debt-risk summary text: {str(exc)}"
        ) from exc

    return DebtRiskAnalysisResponse(
        success=True,
        laundry_id=laundry_id,
        generated_at=as_of_date.isoformat(),
        summary=summary_text,
        table=table,
    )

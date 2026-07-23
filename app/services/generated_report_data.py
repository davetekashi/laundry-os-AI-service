from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services.context_builder import mask_account_number


@dataclass
class ChartSpec:
    kind: str
    title: str
    labels: list[str]
    values: list[float]


@dataclass
class ReportNarrative:
    executive_summary: str
    chart_explanations: dict[str, str] = field(default_factory=dict)
    key_findings: list[str] = field(default_factory=list)
    recommendation: str = ""

    def explanation_for(self, chart: ChartSpec) -> str:
        return self.chart_explanations.get(
            chart.title,
            "This chart visualizes the verified values shown for the selected reporting period.",
        )


@dataclass
class ReportDataset:
    title: str
    metrics: list[tuple[str, str]]
    headers: list[str]
    rows: list[list[Any]]
    charts: list[ChartSpec] = field(default_factory=list)
    analytical_context: dict[str, Any] = field(default_factory=dict)

    def narrative_facts(self) -> dict:
        return {
            "title": self.title,
            "metrics": dict(self.metrics),
            "record_count": len(self.rows),
            "analytical_context": self.analytical_context,
            "charts": [
                {
                    "title": chart.title,
                    "labels": chart.labels,
                    "values": chart.values,
                }
                for chart in self.charts
            ],
        }


def safe_number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def number_text(value: Any) -> str:
    number = safe_number(value)
    return f"{int(number):,}" if number.is_integer() else f"{number:,.2f}"


def money_text(value: Any, currency: str = "NGN") -> str:
    return f"{currency} {number_text(value)}"


def percentage(numerator: float, denominator: float) -> float:
    return round((numerator / denominator) * 100, 1) if denominator else 0.0


def percentage_text(numerator: float, denominator: float) -> str:
    return f"{percentage(numerator, denominator):.1f}%"


def date_text(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M")


def excel_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def full_name(document: dict, snapshot_field: str | None = None) -> str:
    if snapshot_field:
        snapshot = document.get(snapshot_field) or {}
        if snapshot.get("fullName"):
            return str(snapshot["fullName"])
        snapshot_name = " ".join(
            str(part)
            for part in (snapshot.get("firstName"), snapshot.get("lastName"))
            if part
        ).strip()
        if snapshot_name:
            return snapshot_name
    return " ".join(
        str(part)
        for part in (document.get("firstName"), document.get("lastName"))
        if part
    ).strip() or "Unknown"


def distribution_chart(title: str, values: Counter) -> ChartSpec | None:
    non_zero = [(str(label), float(value)) for label, value in values.items() if value]
    if len(non_zero) < 2:
        return None
    non_zero.sort(key=lambda item: item[1], reverse=True)
    labels, counts = zip(*non_zero[:7])
    return ChartSpec("pie", title, list(labels), list(counts))


def daily_chart(
    title: str,
    documents: list[dict],
    date_field: str,
    value_field: str | None = None,
    kind: str = "line",
) -> ChartSpec | None:
    daily: dict[str, float] = defaultdict(float)
    for document in documents:
        value = document.get(date_field)
        if not isinstance(value, datetime):
            continue
        label = value.strftime("%Y-%m-%d")
        daily[label] += safe_number(document.get(value_field)) if value_field else 1
    if len(daily) < 2:
        return None
    labels = sorted(daily)
    return ChartSpec(kind, title, labels, [daily[label] for label in labels])


def daily_totals(
    documents: list[dict],
    date_field: str,
    value_field: str | None = None,
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for document in documents:
        value = document.get(date_field)
        if isinstance(value, datetime):
            totals[value.strftime("%Y-%m-%d")] += (
                safe_number(document.get(value_field)) if value_field else 1
            )
    return dict(totals)


def peak_and_low_day(totals: dict[str, float]) -> tuple[dict | None, dict | None]:
    if not totals:
        return None, None
    peak = max(totals.items(), key=lambda item: item[1])
    low = min(totals.items(), key=lambda item: item[1])
    return (
        {"date": peak[0], "value": peak[1]},
        {"date": low[0], "value": low[1]},
    )


def top_value_chart(
    title: str,
    labels_and_values: list[tuple[str, float]],
) -> ChartSpec | None:
    positive = [(label, value) for label, value in labels_and_values if value > 0]
    if len(positive) < 2:
        return None
    positive.sort(key=lambda item: item[1], reverse=True)
    labels, values = zip(*positive[:8])
    return ChartSpec("bar", title, list(labels), list(values))


def add_chart(charts: list[ChartSpec], chart: ChartSpec | None) -> None:
    if chart is not None and len(charts) < 3:
        charts.append(chart)


def build_laundry_dataset(documents: list[dict]) -> ReportDataset:
    laundry = documents[0] if documents else {}
    rows = [[
        laundry.get("laundryName", ""),
        laundry.get("laundryCode", ""),
        laundry.get("status", ""),
        laundry.get("planType", ""),
        laundry.get("state", ""),
        laundry.get("country", ""),
        bool(laundry.get("isActive")),
        bool(laundry.get("isVerified")),
        excel_datetime(laundry.get("createdAt")),
    ]] if laundry else []
    return ReportDataset(
        title="Laundry Profile Report",
        metrics=[
            ("Status", str(laundry.get("status", "Unavailable"))),
            ("Subscription", str(laundry.get("subscriptionStatus", "Unavailable"))),
            ("Plan", str(laundry.get("planType", "Unavailable"))),
            ("Commission Due", money_text(laundry.get("commissionBalanceDue"))),
            ("Verified", "Yes" if laundry.get("isVerified") else "No"),
        ],
        headers=["Laundry", "Code", "Status", "Plan", "State", "Country", "Active", "Verified", "Created"],
        rows=rows,
        analytical_context={
            "account_active": bool(laundry.get("isActive")),
            "account_paused": bool(laundry.get("isPaused")),
            "commission_suspended": bool(laundry.get("commissionSuspended")),
            "commission_balance_due": safe_number(laundry.get("commissionBalanceDue")),
            "offline_commission_balance_due": safe_number(laundry.get("offlineCommissionBalanceDue")),
            "subscription_status": laundry.get("subscriptionStatus"),
            "subscription_period_end": date_text(laundry.get("subscriptionPeriodEnd")),
            "verification": {
                "business": bool(laundry.get("isVerified")),
                "email": bool(laundry.get("emailVerified")),
                "phone": bool(laundry.get("phoneVerified")),
            },
        },
    )


def build_bank_account_dataset(documents: list[dict]) -> ReportDataset:
    account = documents[0] if documents else {}
    rows = [[
        account.get("bankName", ""),
        account.get("accountName", ""),
        mask_account_number(account.get("accountNumber")) or "",
        account.get("status", ""),
        bool(account.get("isDefault")),
        excel_datetime(account.get("verifiedAt")),
    ]] if account else []
    return ReportDataset(
        title="Bank Account Report",
        metrics=[
            ("Accounts", str(len(rows))),
            ("Status", str(account.get("status", "Unavailable"))),
            ("Default", "Yes" if account.get("isDefault") else "No"),
        ],
        headers=["Bank", "Account Name", "Account Number", "Status", "Default", "Verified At"],
        rows=rows,
        analytical_context={
            "account_configured": bool(account),
            "bank_name": account.get("bankName"),
            "account_status": account.get("status"),
            "is_default": bool(account.get("isDefault")),
            "verified": bool(account.get("verifiedAt")),
        },
    )


def build_customer_dataset(documents: list[dict]) -> ReportDataset:
    active = sum(1 for row in documents if row.get("isActive"))
    credit = sum(1 for row in documents if row.get("creditEnabled"))
    with_orders = sum(1 for row in documents if row.get("lastOrderAt"))
    charts: list[ChartSpec] = []
    add_chart(charts, daily_chart("Customer Acquisition Trend", documents, "createdAt", kind="bar"))
    add_chart(charts, distribution_chart("Customer Activity", Counter(
        "Active" if row.get("isActive") else "Inactive" for row in documents
    )))
    add_chart(charts, distribution_chart("Credit Access", Counter(
        "Credit enabled" if row.get("creditEnabled") else "Cash only" for row in documents
    )))
    return ReportDataset(
        title="Customer Report",
        metrics=[
            ("Customers Added", str(len(documents))),
            ("Active Rate", percentage_text(active, len(documents))),
            ("Ordered Before", str(with_orders)),
            ("Credit Enabled", percentage_text(credit, len(documents))),
        ],
        headers=["Customer", "Phone Number", "Email", "Status", "Credit Enabled", "Last Order", "Created"],
        rows=[[
            full_name(row), row.get("phoneNumber", ""), row.get("email", ""),
            "Active" if row.get("isActive") else "Inactive",
            bool(row.get("creditEnabled")),
            excel_datetime(row.get("lastOrderAt")), excel_datetime(row.get("createdAt")),
        ] for row in documents],
        charts=charts,
        analytical_context={
            "customers_added": len(documents),
            "active_customers": active,
            "inactive_customers": len(documents) - active,
            "active_rate_percent": percentage(active, len(documents)),
            "credit_enabled_customers": credit,
            "credit_enabled_rate_percent": percentage(credit, len(documents)),
            "customers_with_prior_orders": with_orders,
            "customers_without_recorded_orders": len(documents) - with_orders,
        },
    )


def build_debt_dataset(documents: list[dict]) -> ReportDataset:
    outstanding = sum(safe_number(row.get("balanceDue")) for row in documents)
    paid = sum(safe_number(row.get("amountPaid")) for row in documents)
    total_debt = sum(safe_number(row.get("totalAmount")) for row in documents)
    customer_totals: dict[str, float] = defaultdict(float)
    age_buckets: Counter = Counter()
    ages: list[int] = []
    today = datetime.now(UTC).date()
    for row in documents:
        customer_totals[full_name(row, "customerSnapshot")] += safe_number(row.get("balanceDue"))
        opened_at = row.get("openedAt")
        if not isinstance(opened_at, datetime) or safe_number(row.get("balanceDue")) <= 0:
            continue
        opened_date = opened_at.date()
        age = max((today - opened_date).days, 0)
        ages.append(age)
        if age <= 7:
            age_buckets["0-7 days"] += safe_number(row.get("balanceDue"))
        elif age <= 14:
            age_buckets["8-14 days"] += safe_number(row.get("balanceDue"))
        elif age <= 30:
            age_buckets["15-30 days"] += safe_number(row.get("balanceDue"))
        else:
            age_buckets["Over 30 days"] += safe_number(row.get("balanceDue"))
    charts: list[ChartSpec] = []
    add_chart(charts, daily_chart("New Debt Value Over Time", documents, "openedAt", "totalAmount"))
    add_chart(charts, distribution_chart("Outstanding Debt by Age", age_buckets))
    add_chart(charts, top_value_chart("Largest Outstanding Debts", [
        (customer, balance) for customer, balance in customer_totals.items()
    ]))
    largest_customer_balance = max(customer_totals.values(), default=0)
    return ReportDataset(
        title="Debt Report",
        metrics=[
            ("Debt Records", str(len(documents))),
            ("Total Debt", money_text(total_debt)),
            ("Balance Due", money_text(outstanding)),
            ("Recovery Rate", percentage_text(paid, total_debt)),
            ("Average Debt", money_text(total_debt / len(documents) if documents else 0)),
        ],
        headers=["Customer", "Order", "Total Debt", "Amount Paid", "Balance Due", "Status", "Opened", "Settled"],
        rows=[[
            full_name(row, "customerSnapshot"), row.get("orderCode") or row.get("orderNumber", ""),
            safe_number(row.get("totalAmount")), safe_number(row.get("amountPaid")),
            safe_number(row.get("balanceDue")), row.get("status", ""),
            excel_datetime(row.get("openedAt")), excel_datetime(row.get("settledAt")),
        ] for row in documents],
        charts=charts,
        analytical_context={
            "total_debt_value": total_debt,
            "amount_recovered": paid,
            "outstanding_balance": outstanding,
            "recovery_rate_percent": percentage(paid, total_debt),
            "average_outstanding_age_days": round(sum(ages) / len(ages), 1) if ages else 0,
            "oldest_outstanding_debt_days": max(ages, default=0),
            "largest_customer_balance": largest_customer_balance,
            "largest_customer_share_percent": percentage(largest_customer_balance, outstanding),
            "outstanding_age_buckets": dict(age_buckets),
        },
    )


def build_member_dataset(documents: list[dict]) -> ReportDataset:
    active = sum(1 for row in documents if row.get("isActive"))
    role_counts = Counter(str(row.get("role") or "Unknown") for row in documents)
    recent_cutoff = datetime.now(UTC).timestamp() - (30 * 24 * 60 * 60)
    recently_active = sum(
        1 for row in documents
        if isinstance(row.get("lastLoginAt"), datetime)
        and row["lastLoginAt"].replace(tzinfo=row["lastLoginAt"].tzinfo or UTC).timestamp() >= recent_cutoff
    )
    charts: list[ChartSpec] = []
    add_chart(charts, distribution_chart("Members by Role", role_counts))
    add_chart(charts, distribution_chart("Team Availability", Counter(
        "Active" if row.get("isActive") else "Inactive" for row in documents
    )))
    add_chart(charts, daily_chart("Team Growth", documents, "createdAt", kind="bar"))
    return ReportDataset(
        title="Team Member Report",
        metrics=[
            ("Members", str(len(documents))),
            ("Active Rate", percentage_text(active, len(documents))),
            ("Active in 30 Days", str(recently_active)),
            ("Roles Covered", str(len(role_counts))),
        ],
        headers=["Member", "Username", "Email", "Role", "Status", "Active", "Last Login", "Created"],
        rows=[[
            full_name(row), row.get("username", ""), row.get("email", ""), row.get("role", ""),
            row.get("status", ""), bool(row.get("isActive")),
            excel_datetime(row.get("lastLoginAt")), excel_datetime(row.get("createdAt")),
        ] for row in documents],
        charts=charts,
        analytical_context={
            "total_members": len(documents),
            "active_members": active,
            "inactive_members": len(documents) - active,
            "active_rate_percent": percentage(active, len(documents)),
            "members_active_in_last_30_days": recently_active,
            "role_distribution": dict(role_counts),
        },
    )


def build_wallet_dataset(documents: list[dict]) -> ReportDataset:
    wallet = documents[0] if documents else {}
    currency = str(wallet.get("currency") or "NGN")
    rows = [[
        safe_number(wallet.get("availableBalance")),
        safe_number(wallet.get("pendingBalance")),
        bool(wallet.get("isFrozen")),
        excel_datetime(wallet.get("updatedAt")),
    ]] if wallet else []
    charts: list[ChartSpec] = []
    add_chart(charts, top_value_chart("Wallet Balance Composition", [
        ("Available", safe_number(wallet.get("availableBalance"))),
        ("Pending", safe_number(wallet.get("pendingBalance"))),
    ]))
    available = safe_number(wallet.get("availableBalance"))
    pending = safe_number(wallet.get("pendingBalance"))
    total = available + pending
    return ReportDataset(
        title="Wallet Report",
        metrics=[
            ("Available Balance", money_text(wallet.get("availableBalance"), currency)),
            ("Pending Balance", money_text(wallet.get("pendingBalance"), currency)),
            ("Frozen", "Yes" if wallet.get("isFrozen") else "No"),
            ("Available Share", percentage_text(available, total)),
        ],
        headers=["Available Balance", "Pending Balance", "Frozen", "Last Updated"],
        rows=rows,
        charts=charts,
        analytical_context={
            "total_wallet_balance": total,
            "available_balance": available,
            "pending_balance": pending,
            "available_share_percent": percentage(available, total),
            "pending_share_percent": percentage(pending, total),
            "wallet_frozen": bool(wallet.get("isFrozen")),
            "last_updated": date_text(wallet.get("updatedAt")),
        },
    )


def build_logistics_dataset(documents: list[dict]) -> ReportDataset:
    status_counts = Counter(str(row.get("status") or "Unknown") for row in documents)
    total = sum(safe_number(row.get("amount")) for row in documents)
    paid = sum(safe_number(row.get("amountPaid")) for row in documents)
    balance = sum(safe_number(row.get("balanceDue")) for row in documents)
    completed = sum(
        1 for row in documents
        if str(row.get("status") or "").lower() in {"completed", "delivered", "returned"}
    )
    daily_values = daily_totals(documents, "createdAt", "amount")
    peak_day, low_day = peak_and_low_day(daily_values)
    charts: list[ChartSpec] = []
    add_chart(charts, daily_chart("Logistics Value Trend", documents, "createdAt", "amount"))
    add_chart(charts, daily_chart("Logistics Job Volume", documents, "createdAt", kind="bar"))
    add_chart(charts, top_value_chart("Logistics Collection Position", [
        ("Collected", paid), ("Outstanding", balance),
    ]))
    return ReportDataset(
        title="Logistics Report",
        metrics=[
            ("Jobs", str(len(documents))), ("Total Value", money_text(total)),
            ("Collection Rate", percentage_text(paid, total)),
            ("Balance Due", money_text(balance)),
            ("Average Job Value", money_text(total / len(documents) if documents else 0)),
        ],
        headers=["Order", "Customer", "Status", "Payment Status", "Amount", "Amount Paid", "Balance Due", "Created"],
        rows=[[
            row.get("_orderCode", ""), row.get("_customerName", "Unknown"), row.get("status", ""),
            row.get("paymentStatus") or row.get("orderPaymentStatus", ""),
            safe_number(row.get("amount")), safe_number(row.get("amountPaid")),
            safe_number(row.get("balanceDue")), excel_datetime(row.get("createdAt")),
        ] for row in documents],
        charts=charts,
        analytical_context={
            "total_jobs": len(documents),
            "total_logistics_value": total,
            "amount_collected": paid,
            "outstanding_balance": balance,
            "collection_rate_percent": percentage(paid, total),
            "completion_rate_percent": percentage(completed, len(documents)),
            "status_distribution": dict(status_counts),
            "highest_value_day": peak_day,
            "lowest_value_day": low_day,
        },
    )


def build_payment_dataset(documents: list[dict]) -> ReportDataset:
    total = sum(safe_number(row.get("totalAmount")) for row in documents)
    status_counts = Counter(str(row.get("status") or "Unknown") for row in documents)
    method_counts = Counter(str(row.get("method") or "Unknown") for row in documents)
    successful_statuses = {"successful", "success", "completed", "paid"}
    successful = [
        row for row in documents
        if str(row.get("status") or "").lower() in successful_statuses
    ]
    successful_value = sum(safe_number(row.get("totalAmount")) for row in successful)
    daily_values = daily_totals(documents, "transactionDate", "totalAmount")
    peak_day, low_day = peak_and_low_day(daily_values)
    charts: list[ChartSpec] = []
    add_chart(charts, daily_chart("Payment Value Over Time", documents, "transactionDate", "totalAmount"))
    add_chart(charts, distribution_chart("Payment Methods", method_counts))
    if len(status_counts) > 1:
        add_chart(charts, distribution_chart("Payment Outcome", status_counts))
    return ReportDataset(
        title="Customer Payment Report",
        metrics=[
            ("Payments", str(len(documents))), ("Recorded Value", money_text(total)),
            ("Average Payment", money_text(total / len(documents) if documents else 0)),
            ("Success Rate", percentage_text(len(successful), len(documents))),
            ("Successful Value", money_text(successful_value)),
        ],
        headers=["Customer", "Amount", "Method", "Status", "Transaction Type", "Transaction Date"],
        rows=[[
            row.get("_customerName", "Unknown"), safe_number(row.get("totalAmount")),
            row.get("method", ""), row.get("status", ""), row.get("transactionType", ""),
            excel_datetime(row.get("transactionDate") or row.get("createdAt")),
        ] for row in documents],
        charts=charts,
        analytical_context={
            "payment_count": len(documents),
            "recorded_payment_value": total,
            "successful_payment_count": len(successful),
            "successful_payment_value": successful_value,
            "success_rate_percent": percentage(len(successful), len(documents)),
            "average_payment_value": round(total / len(documents), 2) if documents else 0,
            "payment_method_distribution": dict(method_counts),
            "payment_status_distribution": dict(status_counts),
            "highest_collection_day": peak_day,
            "lowest_collection_day": low_day,
        },
    )


def build_order_dataset(documents: list[dict]) -> ReportDataset:
    total = sum(safe_number(row.get("totalPayable")) for row in documents)
    paid = sum(safe_number(row.get("totalAmountPaid")) for row in documents)
    balance = sum(safe_number(row.get("totalBalanceDue")) for row in documents)
    service_total = sum(safe_number(row.get("serviceTotal")) for row in documents)
    logistics_total = sum(safe_number(row.get("logisticsTotal")) for row in documents)
    item_count = sum(safe_number(row.get("itemCount")) for row in documents)
    daily_values = daily_totals(documents, "createdAt", "totalPayable")
    daily_volumes = daily_totals(documents, "createdAt")
    peak_value_day, low_value_day = peak_and_low_day(daily_values)
    busiest_day, quietest_day = peak_and_low_day(daily_volumes)
    customer_values: dict[str, float] = defaultdict(float)
    for row in documents:
        customer_values[full_name(row, "customerSnapshot")] += safe_number(row.get("totalPayable"))
    largest_customer_value = max(customer_values.values(), default=0)
    charts: list[ChartSpec] = []
    add_chart(charts, daily_chart("Order Value Trend", documents, "createdAt", "totalPayable"))
    add_chart(charts, daily_chart("Order Volume by Day", documents, "createdAt", kind="bar"))
    add_chart(charts, top_value_chart("Payment Collection Position", [
        ("Collected", paid), ("Outstanding", balance),
    ]))
    return ReportDataset(
        title="Order Report",
        metrics=[
            ("Orders", str(len(documents))), ("Order Value", money_text(total)),
            ("Amount Collected", money_text(paid)),
            ("Collection Rate", percentage_text(paid, total)),
            ("Average Order Value", money_text(total / len(documents) if documents else 0)),
            ("Items per Order", number_text(item_count / len(documents) if documents else 0)),
        ],
        headers=["Order", "Customer", "Items", "Service Total", "Logistics Total", "Total Payable", "Paid", "Balance", "Order Status", "Payment Status", "Created"],
        rows=[[
            row.get("orderCode") or row.get("orderNumber", ""), full_name(row, "customerSnapshot"),
            row.get("itemCount", 0), safe_number(row.get("serviceTotal")), safe_number(row.get("logisticsTotal")),
            safe_number(row.get("totalPayable")), safe_number(row.get("totalAmountPaid")),
            safe_number(row.get("totalBalanceDue")), row.get("orderStatus", ""),
            row.get("paymentStatus", ""), excel_datetime(row.get("createdAt")),
        ] for row in documents],
        charts=charts,
        analytical_context={
            "total_orders": len(documents),
            "total_order_value": total,
            "amount_collected": paid,
            "outstanding_balance": balance,
            "collection_rate_percent": percentage(paid, total),
            "average_order_value": round(total / len(documents), 2) if documents else 0,
            "total_items": item_count,
            "average_items_per_order": round(item_count / len(documents), 2) if documents else 0,
            "service_revenue": service_total,
            "logistics_revenue": logistics_total,
            "service_share_percent": percentage(service_total, service_total + logistics_total),
            "logistics_share_percent": percentage(logistics_total, service_total + logistics_total),
            "highest_value_day": peak_value_day,
            "lowest_value_day": low_value_day,
            "busiest_order_day": busiest_day,
            "quietest_order_day": quietest_day,
            "unique_customers": len(customer_values),
            "largest_customer_value": largest_customer_value,
            "largest_customer_share_percent": percentage(largest_customer_value, total),
        },
    )


BUILDERS = {
    "laundry": build_laundry_dataset,
    "bank_account": build_bank_account_dataset,
    "customers": build_customer_dataset,
    "debts": build_debt_dataset,
    "members": build_member_dataset,
    "wallet": build_wallet_dataset,
    "logistics": build_logistics_dataset,
    "payments": build_payment_dataset,
    "orders": build_order_dataset,
}


def build_generated_report_dataset(entity: str, documents: list[dict]) -> ReportDataset:
    return BUILDERS[entity](documents)

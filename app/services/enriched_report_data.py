from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId

from app.services.context_builder import mask_account_number
from app.services.generated_report_data import (
    ChartSpec,
    ReportDataset,
    add_chart,
    daily_chart,
    distribution_chart,
    excel_datetime,
    full_name,
    money_text,
    number_text,
    peak_and_low_day,
    percentage,
    percentage_text,
    safe_number,
    top_value_chart,
)
from app.services.report_repository import ReportSource


CONFIRMED_PAYMENT_STATUSES = {"confirmed", "completed", "paid", "success", "successful"}


def _documents(source: ReportSource, key: str) -> list[dict]:
    value = source.related.get(key, [])
    return value if isinstance(value, list) else []


def _confirmed_payments(payments: list[dict]) -> list[dict]:
    return [
        payment
        for payment in payments
        if str(payment.get("status") or "").lower() in CONFIRMED_PAYMENT_STATUSES
    ]


def _signed_amount(document: dict, field_name: str = "amount") -> float:
    amount = safe_number(document.get(field_name))
    transaction_type = str(document.get("transactionType") or "").lower()
    return -amount if transaction_type == "refund" else amount


def _payment_date(payment: dict) -> datetime | None:
    for field_name in (
        "paidAt",
        "transactionDate",
        "confirmedAt",
        "recordedAt",
        "createdAt",
    ):
        value = payment.get(field_name)
        if isinstance(value, datetime):
            return value
    return None


def _payment_name(payment: dict) -> str:
    for field_name in ("payerSnapshot", "customerSnapshot"):
        snapshot = payment.get(field_name) or {}
        if snapshot.get("fullName"):
            return str(snapshot["fullName"])
    return "Unknown"


def _payment_method(payment: dict) -> str:
    return str(
        payment.get("offlineMethod")
        or payment.get("paymentChannel")
        or payment.get("method")
        or "Unknown"
    )


def _dated_payment_documents(payments: list[dict]) -> list[dict]:
    return [
        {**payment, "_effectiveDate": _payment_date(payment)}
        for payment in payments
        if _payment_date(payment) is not None
    ]


def _daily_totals(
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


def _source_quality(source: ReportSource) -> dict[str, int]:
    return {key: value for key, value in source.data_quality.items() if value}


def _catalog_maps(source: ReportSource) -> tuple[dict, dict, dict]:
    price_names = {
        document.get("_id"): document.get("itemName") or document.get("normalizedItemName")
        for document in _documents(source, "item_prices")
    }
    service_names = {}
    for document in (
        _documents(source, "global_services")
        + _documents(source, "laundry_services")
    ):
        name = document.get("name") or document.get("slug") or document.get("serviceKey")
        for key in (document.get("_id"), document.get("service"), document.get("serviceKey")):
            if key is not None and name:
                service_names[key] = name
    type_documents = _documents(source, "global_item_types")
    category_names = {
        document.get("_id"): document.get("name")
        for document in _documents(source, "global_item_categories")
    }
    type_names = {
        document.get("_id"): {
            "name": document.get("name"),
            "category": category_names.get(document.get("itemCategory")),
        }
        for document in type_documents
    }
    return price_names, service_names, type_names


def _order_item_rows(source: ReportSource) -> list[dict]:
    price_names, service_names, type_names = _catalog_maps(source)
    rows: list[dict] = []
    for order in source.records:
        for item in order.get("items") or []:
            type_info = type_names.get(item.get("itemType"), {})
            item_name = (
                item.get("itemNameSnapshot")
                or price_names.get(item.get("itemPriceId"))
                or type_info.get("name")
                or "Unknown"
            )
            service_name = (
                item.get("serviceNameSnapshot")
                or service_names.get(item.get("service"))
                or "Unknown"
            )
            rows.append(
                {
                    "orderCode": order.get("orderCode") or order.get("orderNumber"),
                    "createdAt": order.get("createdAt"),
                    "customer": full_name(order, "customerSnapshot"),
                    "itemName": str(item_name),
                    "category": type_info.get("category") or "Uncategorized",
                    "serviceName": str(service_name),
                    "basePrice": safe_number(item.get("basePrice")),
                    "unitPrice": safe_number(item.get("unitPrice")),
                    "addOnTotal": safe_number(item.get("addOnTotal")),
                    "variantTotal": safe_number(item.get("variantTotal")),
                    "subtotal": safe_number(item.get("subtotal")),
                }
            )
    return rows


def build_laundry_report(source: ReportSource) -> ReportDataset:
    laundry = source.records[0] if source.records else {}
    business = source.related.get("business") or {}
    settings = source.related.get("workspace_settings") or {}
    business_settings = source.related.get("business_settings") or {}
    branch_settings = _documents(source, "branch_settings")
    operations = (
        settings.get("operations")
        or business_settings.get("operations")
        or (business_settings.get("values") or {}).get("operations")
        or {}
    )
    intents = _documents(source, "subscription_intents")
    latest_intent = intents[-1] if intents else {}
    business_name = (
        business.get("name")
        or business.get("businessName")
        or laundry.get("laundryName")
        or ""
    )
    return ReportDataset(
        title="Laundry Business Configuration Report",
        metrics=[
            ("Status", str(laundry.get("status") or "Unavailable")),
            ("Subscription", str(laundry.get("subscriptionStatus") or "Unavailable")),
            ("Plan", str(laundry.get("planType") or "Unavailable")),
            ("Commission Due", money_text(laundry.get("commissionBalanceDue"))),
            ("Configured Branches", str(len(branch_settings))),
            ("Turnaround Target", f"{operations.get('defaultTurnaroundDays', 0)} days"),
        ],
        headers=[
            "Laundry", "Code", "Plan", "Subscription Status", "Active", "Verified",
            "Default Turnaround Days", "Minimum Payment Percentage", "Latest Plan Intent",
        ],
        rows=[[
            business_name, laundry.get("laundryCode", ""),
            laundry.get("planType", ""), laundry.get("subscriptionStatus", ""),
            bool(laundry.get("isActive")), bool(laundry.get("isVerified")),
            operations.get("defaultTurnaroundDays", 0), operations.get("minimumPaymentPercentage", 0),
            latest_intent.get("status", ""),
        ]] if laundry else [],
        analytical_context={
            "account_active": bool(laundry.get("isActive")),
            "account_paused": bool(laundry.get("isPaused")),
            "commission_suspended": bool(laundry.get("commissionSuspended")),
            "commission_balance_due": safe_number(laundry.get("commissionBalanceDue")),
            "subscription_status": laundry.get("subscriptionStatus"),
            "latest_subscription_intent": latest_intent.get("status"),
            "scope_mode": "migrated" if business else "legacy",
            "configured_branch_count": len(branch_settings),
            "operations": operations,
        },
    )


def build_bank_account_report(source: ReportSource) -> ReportDataset:
    settlements = _documents(source, "settlements")
    completed = sum(
        1 for row in settlements if str(row.get("status") or "").lower() in {"completed", "successful", "paid"}
    )
    return ReportDataset(
        title="Bank Account and Settlement Readiness Report",
        metrics=[
            ("Bank Accounts", str(len(source.records))),
            ("Settlement Requests", str(len(settlements))),
            ("Completed Settlements", str(completed)),
        ],
        headers=["Bank", "Account Name", "Account Number", "Status", "Default", "Verified At"],
        rows=[[
            row.get("bankName", ""), row.get("accountName", ""),
            mask_account_number(row.get("accountNumber")) or "", row.get("status", ""),
            bool(row.get("isDefault")), excel_datetime(row.get("verifiedAt")),
        ] for row in source.records],
        analytical_context={
            "account_count": len(source.records),
            "settlement_request_count": len(settlements),
            "completed_settlement_count": completed,
        },
    )


def build_order_report(source: ReportSource) -> ReportDataset:
    orders = source.records
    order_payments = _confirmed_payments(_documents(source, "order_payments"))
    period_payments = _confirmed_payments(_documents(source, "payments_in_period"))
    payments_by_order: dict[ObjectId, float] = defaultdict(float)
    for payment in order_payments:
        payments_by_order[payment.get("orderId")] += _signed_amount(payment)

    billed = sum(safe_number(order.get("totalPayable")) for order in orders)
    collected_for_orders = sum(payments_by_order.values())
    cash_collected_in_period = sum(_signed_amount(payment) for payment in period_payments)
    outstanding = max(billed - collected_for_orders, 0)
    item_count = sum(safe_number(order.get("itemCount")) for order in orders)
    service_total = sum(safe_number(order.get("serviceTotal")) for order in orders)
    logistics_total = sum(safe_number(order.get("logisticsTotal")) for order in orders)
    customer_values: dict[str, float] = defaultdict(float)
    for order in orders:
        customer_values[full_name(order, "customerSnapshot")] += safe_number(order.get("totalPayable"))
    largest_customer = max(customer_values.values(), default=0)
    daily_values = _daily_totals(orders, "createdAt", "totalPayable")
    daily_volume = _daily_totals(orders, "createdAt")
    peak_value_day, low_value_day = peak_and_low_day(daily_values)
    busiest_day, quietest_day = peak_and_low_day(daily_volume)

    item_rows = _order_item_rows(source)
    service_values: dict[str, float] = defaultdict(float)
    item_values: dict[str, float] = defaultdict(float)
    for item in item_rows:
        service_values[item["serviceName"]] += item["subtotal"]
        item_values[item["itemName"]] += item["subtotal"]

    charts: list[ChartSpec] = []
    add_chart(charts, daily_chart("Order Value Trend", orders, "createdAt", "totalPayable"))
    add_chart(charts, daily_chart("Order Volume by Day", orders, "createdAt", kind="bar"))
    add_chart(charts, top_value_chart("Revenue by Service", list(service_values.items())))
    return ReportDataset(
        title="Order Performance Report",
        metrics=[
            ("Orders", str(len(orders))),
            ("Billed Sales", money_text(billed)),
            ("Collected", money_text(collected_for_orders)),
            ("Collection Rate", percentage_text(collected_for_orders, billed)),
            ("Average Order", money_text(billed / len(orders) if orders else 0)),
            ("Outstanding", money_text(outstanding)),
        ],
        headers=[
            "Order", "Customer", "Items", "Service Total", "Logistics Total", "Total Payable",
            "Confirmed Payments", "Outstanding", "Order Status", "Payment Status", "Created",
        ],
        rows=[[
            order.get("orderCode") or order.get("orderNumber", ""),
            full_name(order, "customerSnapshot"), order.get("itemCount", 0),
            safe_number(order.get("serviceTotal")), safe_number(order.get("logisticsTotal")),
            safe_number(order.get("totalPayable")), payments_by_order.get(order.get("_id"), 0),
            max(safe_number(order.get("totalPayable")) - payments_by_order.get(order.get("_id"), 0), 0),
            order.get("orderStatus", ""), order.get("paymentStatus", ""),
            excel_datetime(order.get("createdAt")),
        ] for order in orders],
        charts=charts,
        analytical_context={
            "billed_sales": billed,
            "confirmed_collections_for_selected_orders": collected_for_orders,
            "cash_collected_during_period": cash_collected_in_period,
            "outstanding_balance": outstanding,
            "collection_rate_percent": percentage(collected_for_orders, billed),
            "average_items_per_order": round(item_count / len(orders), 2) if orders else 0,
            "service_sales": service_total,
            "logistics_sales": logistics_total,
            "unique_customers": len(customer_values),
            "largest_customer_share_percent": percentage(largest_customer, billed),
            "highest_value_day": peak_value_day,
            "lowest_value_day": low_value_day,
            "busiest_day": busiest_day,
            "quietest_day": quietest_day,
            "top_services": sorted(service_values.items(), key=lambda row: row[1], reverse=True)[:5],
            "top_items": sorted(item_values.items(), key=lambda row: row[1], reverse=True)[:5],
            "data_quality": _source_quality(source),
        },
    )


def build_payment_report(source: ReportSource) -> ReportDataset:
    payments = source.records
    confirmed = _confirmed_payments(payments)
    receipts = _documents(source, "customer_payments")
    allocations = _documents(source, "allocations")
    ledger_entries = _documents(source, "ledger_entries")
    confirmed_total = sum(_signed_amount(row) for row in confirmed)
    receipt_total = sum(_signed_amount(row, "totalAmount") for row in receipts)
    service_total = sum(_signed_amount(row, "serviceAmount") for row in confirmed)
    delivery_total = sum(_signed_amount(row, "deliveryAmount") for row in confirmed)
    method_counts = Counter(_payment_method(row) for row in confirmed)
    dated = [
        {**row, "signedAmount": _signed_amount(row)}
        for row in _dated_payment_documents(confirmed)
    ]
    charts: list[ChartSpec] = []
    add_chart(charts, daily_chart("Net Collections Trend", dated, "_effectiveDate", "signedAmount"))
    add_chart(charts, distribution_chart("Collection Methods", method_counts))
    add_chart(charts, top_value_chart("Collection Components", [
        ("Service", service_total), ("Delivery", delivery_total),
    ]))
    return ReportDataset(
        title="Payment Collection Report",
        metrics=[
            ("Payment Events", str(len(payments))),
            ("Confirmed Collections", money_text(confirmed_total)),
            ("Average Payment", money_text(confirmed_total / len(confirmed) if confirmed else 0)),
            ("Confirmation Rate", percentage_text(len(confirmed), len(payments))),
            ("Receipt Headers", str(len(receipts))),
        ],
        headers=[
            "Order ID", "Customer", "Amount", "Service Amount", "Delivery Amount", "Method",
            "Channel", "Status", "Payment Date",
        ],
        rows=[[
            str(row.get("orderId") or ""), _payment_name(row), safe_number(row.get("amount")),
            safe_number(row.get("serviceAmount")), safe_number(row.get("deliveryAmount")),
            _payment_method(row), row.get("paymentChannel", ""), row.get("status", ""),
            excel_datetime(_payment_date(row)),
        ] for row in payments],
        charts=charts,
        analytical_context={
            "confirmed_collection_total": confirmed_total,
            "customer_receipt_total": receipt_total,
            "service_collection_total": service_total,
            "delivery_collection_total": delivery_total,
            "payment_confirmation_rate_percent": percentage(len(confirmed), len(payments)),
            "collection_method_distribution": dict(method_counts),
            "allocation_count": len(allocations),
            "allocated_total": sum(safe_number(row.get("amount")) for row in allocations),
            "ledger_entry_count": len(ledger_entries),
            "data_quality": _source_quality(source),
            "accounting_note": "Payment, receipt, allocation and ledger totals are reconciliation stages and are not additive.",
        },
    )


def build_customer_report(source: ReportSource) -> ReportDataset:
    customers = source.records
    orders = _documents(source, "orders")
    payments = _confirmed_payments(_documents(source, "order_payments"))
    debts = _documents(source, "debts")
    order_values: dict[ObjectId, float] = defaultdict(float)
    order_counts: Counter = Counter()
    collected: dict[ObjectId, float] = defaultdict(float)
    balances: dict[ObjectId, float] = defaultdict(float)
    customer_lookup: dict[ObjectId, ObjectId] = {}
    for customer in customers:
        canonical_id = customer.get("_id")
        if not isinstance(canonical_id, ObjectId):
            continue
        for field_name in (
            "_id",
            "businessCustomerId",
            "legacyLaundryCustomerId",
            "userId",
        ):
            reference = customer.get(field_name)
            if isinstance(reference, ObjectId):
                customer_lookup[reference] = canonical_id
    for order in orders:
        customer_id = customer_lookup.get(
            order.get("laundryCustomerId") or order.get("userId"),
            order.get("laundryCustomerId") or order.get("userId"),
        )
        order_values[customer_id] += safe_number(order.get("totalPayable"))
        order_counts[customer_id] += 1
    for payment in payments:
        customer_id = customer_lookup.get(
            payment.get("laundryCustomerId"), payment.get("laundryCustomerId")
        )
        collected[customer_id] += _signed_amount(payment)
    for debt in debts:
        customer_id = customer_lookup.get(
            debt.get("laundryCustomerId") or debt.get("userId"),
            debt.get("laundryCustomerId") or debt.get("userId"),
        )
        balances[customer_id] += safe_number(debt.get("balanceDue"))

    total_billed = sum(order_values.values())
    total_collected = sum(collected.values())
    credit_enabled = sum(1 for row in customers if row.get("creditEnabled"))
    charts: list[ChartSpec] = []
    add_chart(charts, daily_chart("Customer Acquisition Trend", customers, "createdAt", kind="bar"))
    add_chart(charts, top_value_chart("Highest-Value New Customers", [
        (full_name(customer), order_values.get(customer.get("_id"), 0)) for customer in customers
    ]))
    add_chart(charts, distribution_chart("Credit Access", Counter(
        "Credit enabled" if row.get("creditEnabled") else "Cash only" for row in customers
    )))
    return ReportDataset(
        title="Customer Value Report",
        metrics=[
            ("Customers Added", str(len(customers))),
            ("Orders Generated", str(len(orders))),
            ("Billed Value", money_text(total_billed)),
            ("Collected", money_text(total_collected)),
            ("Debt Exposure", money_text(sum(balances.values()))),
        ],
        headers=[
            "Customer", "Phone", "Email", "Credit Enabled", "Orders", "Billed Value",
            "Confirmed Collections", "Debt Balance", "Created",
        ],
        rows=[[
            full_name(customer), customer.get("phoneNumber", ""), customer.get("email", ""),
            bool(customer.get("creditEnabled")), order_counts.get(customer.get("_id"), 0),
            order_values.get(customer.get("_id"), 0), collected.get(customer.get("_id"), 0),
            balances.get(customer.get("_id"), 0), excel_datetime(customer.get("createdAt")),
        ] for customer in customers],
        charts=charts,
        analytical_context={
            "customers_added": len(customers),
            "customers_who_ordered": sum(1 for customer in customers if order_counts.get(customer.get("_id"), 0)),
            "credit_enabled_rate_percent": percentage(credit_enabled, len(customers)),
            "billed_value_from_new_customers": total_billed,
            "confirmed_collections_from_new_customers": total_collected,
            "debt_exposure_from_new_customers": sum(balances.values()),
        },
    )


def build_debt_report(source: ReportSource) -> ReportDataset:
    debts = source.records
    payments = _confirmed_payments(_documents(source, "order_payments"))
    payment_by_order: dict[ObjectId, float] = defaultdict(float)
    for payment in payments:
        payment_by_order[payment.get("orderId")] += _signed_amount(payment)
    total = sum(safe_number(row.get("totalAmount")) for row in debts)
    debt_paid = sum(safe_number(row.get("amountPaid")) for row in debts)
    outstanding = sum(safe_number(row.get("balanceDue")) for row in debts)
    today = datetime.now(UTC).date()
    age_values: Counter = Counter()
    customer_values: dict[str, float] = defaultdict(float)
    ages: list[int] = []
    for debt in debts:
        balance = safe_number(debt.get("balanceDue"))
        customer_values[full_name(debt, "customerSnapshot")] += balance
        opened_at = debt.get("openedAt")
        if not isinstance(opened_at, datetime) or balance <= 0:
            continue
        age = max((today - opened_at.date()).days, 0)
        ages.append(age)
        bucket = "0-7 days" if age <= 7 else "8-14 days" if age <= 14 else "15-30 days" if age <= 30 else "Over 30 days"
        age_values[bucket] += balance
    charts: list[ChartSpec] = []
    add_chart(charts, daily_chart("New Debt Value", debts, "openedAt", "totalAmount"))
    add_chart(charts, distribution_chart("Outstanding Debt by Age", age_values))
    add_chart(charts, top_value_chart("Largest Customer Debt Exposure", list(customer_values.items())))
    largest = max(customer_values.values(), default=0)
    return ReportDataset(
        title="Debt Exposure and Recovery Report",
        metrics=[
            ("Debt Records", str(len(debts))),
            ("Debt Opened", money_text(total)),
            ("Recovered", money_text(debt_paid)),
            ("Outstanding", money_text(outstanding)),
            ("Recovery Rate", percentage_text(debt_paid, total)),
        ],
        headers=[
            "Customer", "Order", "Debt Amount", "Debt Amount Paid", "Confirmed Order Payments",
            "Balance Due", "Status", "Opened", "Settled",
        ],
        rows=[[
            full_name(row, "customerSnapshot"), row.get("orderCode") or row.get("orderNumber", ""),
            safe_number(row.get("totalAmount")), safe_number(row.get("amountPaid")),
            payment_by_order.get(row.get("orderId"), 0), safe_number(row.get("balanceDue")),
            row.get("status", ""), excel_datetime(row.get("openedAt")), excel_datetime(row.get("settledAt")),
        ] for row in debts],
        charts=charts,
        analytical_context={
            "total_debt_opened": total,
            "debt_amount_recovered": debt_paid,
            "outstanding_balance": outstanding,
            "recovery_rate_percent": percentage(debt_paid, total),
            "average_outstanding_age_days": round(sum(ages) / len(ages), 1) if ages else 0,
            "oldest_outstanding_debt_days": max(ages, default=0),
            "largest_customer_share_percent": percentage(largest, outstanding),
            "data_quality": _source_quality(source),
        },
    )


def build_member_report(source: ReportSource) -> ReportDataset:
    members = source.records
    orders = _documents(source, "orders")
    payments = _confirmed_payments(_documents(source, "order_payments"))
    member_lookup: dict[ObjectId, ObjectId] = {}
    for member in members:
        canonical_id = member.get("_id")
        if not isinstance(canonical_id, ObjectId):
            continue
        for field_name in ("_id", "userId", "legacyMemberId"):
            reference = member.get(field_name)
            if isinstance(reference, ObjectId):
                member_lookup[reference] = canonical_id

    def member_id_for(document: dict, *fields: str):
        reference = next((document.get(field) for field in fields if document.get(field)), None)
        return member_lookup.get(reference, reference)

    orders_by_member: Counter = Counter(
        member_id_for(order, "createdByStaffId", "createdByMemberId", "createdByUserId")
        for order in orders
    )
    order_value_by_member: dict[ObjectId, float] = defaultdict(float)
    payments_by_member: Counter = Counter()
    payment_value_by_member: dict[ObjectId, float] = defaultdict(float)
    for order in orders:
        member_id = member_id_for(
            order, "createdByStaffId", "createdByMemberId", "createdByUserId"
        )
        order_value_by_member[member_id] += safe_number(order.get("totalPayable"))
    for payment in payments:
        member_id = member_id_for(
            payment, "recordedByMemberId", "confirmedByMemberId"
        )
        payments_by_member[member_id] += 1
        payment_value_by_member[member_id] += _signed_amount(payment)
    active = sum(1 for row in members if row.get("isActive"))
    charts: list[ChartSpec] = []
    add_chart(charts, top_value_chart("Order Value Created by Team Member", [
        (full_name(member), order_value_by_member.get(member.get("_id"), 0)) for member in members
    ]))
    add_chart(charts, top_value_chart("Collections Handled by Team Member", [
        (full_name(member), payment_value_by_member.get(member.get("_id"), 0)) for member in members
    ]))
    add_chart(charts, distribution_chart("Members by Role", Counter(
        str(member.get("role") or "Unknown") for member in members
    )))
    return ReportDataset(
        title="Team Activity Report",
        metrics=[
            ("Members", str(len(members))),
            ("Active Members", str(active)),
            ("Orders Created", str(len(orders))),
            ("Payments Handled", str(len(payments))),
            ("Collections Handled", money_text(sum(payment_value_by_member.values()))),
        ],
        headers=[
            "Member", "Role", "Status", "Active", "Orders Created", "Order Value Created",
            "Payments Handled", "Collection Value Handled", "Last Login",
        ],
        rows=[[
            full_name(member), member.get("role", ""), member.get("status", ""),
            bool(member.get("isActive")), orders_by_member.get(member.get("_id"), 0),
            order_value_by_member.get(member.get("_id"), 0), payments_by_member.get(member.get("_id"), 0),
            payment_value_by_member.get(member.get("_id"), 0), excel_datetime(member.get("lastLoginAt")),
        ] for member in members],
        charts=charts,
        analytical_context={
            "active_member_rate_percent": percentage(active, len(members)),
            "orders_created_in_period": len(orders),
            "confirmed_collections_handled": sum(payment_value_by_member.values()),
            "unattributed_orders": orders_by_member.get(None, 0),
            "unattributed_payments": payments_by_member.get(None, 0),
        },
    )


def build_wallet_report(source: ReportSource) -> ReportDataset:
    wallet = source.records[0] if source.records else {}
    transactions = _documents(source, "wallet_transactions")
    settlements = _documents(source, "settlements")
    credits = sum(safe_number(row.get("amount")) for row in transactions if str(row.get("direction")).lower() == "credit")
    debits = sum(safe_number(row.get("amount")) for row in transactions if str(row.get("direction")).lower() == "debit")
    pending_settlements = sum(
        safe_number(row.get("amount")) for row in settlements
        if str(row.get("status") or "").lower() not in {"completed", "successful", "paid", "cancelled", "failed"}
    )
    available = safe_number(wallet.get("availableBalance"))
    pending = safe_number(wallet.get("pendingBalance"))
    charts: list[ChartSpec] = []
    add_chart(charts, top_value_chart("Wallet Position", [("Available", available), ("Pending", pending)]))
    add_chart(charts, top_value_chart("Wallet Movement", [("Credits", credits), ("Debits", debits)]))
    return ReportDataset(
        title="Wallet Position and Movement Report",
        metrics=[
            ("Available", money_text(available)),
            ("Pending", money_text(pending)),
            ("Period Credits", money_text(credits)),
            ("Period Debits", money_text(debits)),
            ("Pending Settlements", money_text(pending_settlements)),
        ],
        headers=["Available Balance", "Pending Balance", "Frozen", "Last Transaction", "Last Updated"],
        rows=[[
            available, pending, bool(wallet.get("isFrozen")),
            excel_datetime(wallet.get("lastTransactionAt")), excel_datetime(wallet.get("updatedAt")),
        ]] if wallet else [],
        charts=charts,
        analytical_context={
            "available_balance": available,
            "pending_balance": pending,
            "period_wallet_credits": credits,
            "period_wallet_debits": debits,
            "net_wallet_movement": credits - debits,
            "pending_settlement_value": pending_settlements,
            "wallet_frozen": bool(wallet.get("isFrozen")),
        },
    )


def build_logistics_report(source: ReportSource) -> ReportDataset:
    jobs = source.records
    orders = {row.get("_id"): row for row in _documents(source, "orders")}
    customers = {row.get("_id"): row for row in _documents(source, "customers")}
    dispatches = _documents(source, "dispatches")
    drivers = _documents(source, "drivers")
    total = sum(safe_number(row.get("amount")) for row in jobs)
    paid = sum(safe_number(row.get("amountPaid")) for row in jobs)
    balance = sum(safe_number(row.get("balanceDue")) for row in jobs)
    status_counts = Counter(str(row.get("status") or "Unknown") for row in jobs)
    charts: list[ChartSpec] = []
    add_chart(charts, daily_chart("Logistics Value Trend", jobs, "createdAt", "amount"))
    add_chart(charts, daily_chart("Logistics Job Volume", jobs, "createdAt", kind="bar"))
    add_chart(charts, top_value_chart("Logistics Collection Position", [("Collected", paid), ("Outstanding", balance)]))
    return ReportDataset(
        title="Logistics Performance Report",
        metrics=[
            ("Jobs", str(len(jobs))), ("Job Value", money_text(total)),
            ("Collected", money_text(paid)), ("Outstanding", money_text(balance)),
            ("Dispatches", str(len(dispatches))),
        ],
        headers=["Order", "Customer", "Status", "Amount", "Amount Paid", "Balance Due", "Created"],
        rows=[[
            (orders.get(row.get("orderId")) or {}).get("orderCode", ""),
            full_name(customers.get(row.get("laundryCustomerId"), {})), row.get("status", ""),
            safe_number(row.get("amount")), safe_number(row.get("amountPaid")),
            safe_number(row.get("balanceDue")), excel_datetime(row.get("createdAt")),
        ] for row in jobs],
        charts=charts,
        analytical_context={
            "job_count": len(jobs),
            "job_value": total,
            "collection_rate_percent": percentage(paid, total),
            "outstanding_balance": balance,
            "dispatch_count": len(dispatches),
            "driver_count": len(drivers),
            "status_distribution": dict(status_counts),
            "data_quality": _source_quality(source),
        },
    )


def build_expense_report(source: ReportSource) -> ReportDataset:
    rows: list[list[Any]] = []
    category_totals: dict[str, float] = defaultdict(float)
    month_totals: dict[str, float] = defaultdict(float)
    for document in source.records:
        expense_date = document.get("expenseDate") or document.get("createdAt")
        if isinstance(expense_date, datetime):
            month_label = expense_date.strftime("%Y-%m")
            date_value = excel_datetime(expense_date)
        else:
            month_label = f"{document.get('year', '')}-{int(document.get('monthNumber', 0) or 0):02d}"
            date_value = month_label
        entries = document.get("entries") or []
        direct_amount = safe_number(document.get("amount"))
        if not entries and direct_amount:
            category = str(document.get("category") or "Uncategorized")
            description = str(
                document.get("description")
                or document.get("title")
                or document.get("subcategory")
                or ""
            )
            rows.append([date_value, category, description, direct_amount])
            category_totals[category] += direct_amount
            month_totals[month_label] += direct_amount
        elif not entries:
            legacy_total = safe_number(document.get("totalExpenses"))
            rows.append([date_value, "Uncategorized", "", legacy_total])
            category_totals["Uncategorized"] += legacy_total
            month_totals[month_label] += legacy_total
        for entry in entries:
            category = str(entry.get("category") or "Uncategorized")
            amount = safe_number(entry.get("amount"))
            rows.append([date_value, category, entry.get("subcategory", ""), amount])
            category_totals[category] += amount
            month_totals[month_label] += amount
    total = sum(month_totals.values())
    charts: list[ChartSpec] = []
    add_chart(charts, top_value_chart("Expenses by Category", list(category_totals.items())))
    if len(month_totals) >= 2:
        labels = sorted(month_totals)
        add_chart(charts, ChartSpec("line", "Monthly Expense Trend", labels, [month_totals[label] for label in labels]))
    return ReportDataset(
        title="Recorded Expense Report",
        metrics=[
            ("Recorded Expenses", money_text(total)),
            ("Months Included", str(len(month_totals))),
            ("Expense Entries", str(len(rows))),
            ("Average per Month", money_text(total / len(month_totals) if month_totals else 0)),
        ],
        headers=["Date", "Category", "Description", "Amount"],
        rows=rows,
        charts=charts,
        analytical_context={
            "recorded_expense_total": total,
            "months_included": sorted(month_totals),
            "category_totals": dict(category_totals),
            "expense_scope_note": "Expenses are included from actual dated expense records in the selected period; legacy monthly records are not prorated.",
        },
    )


def build_profitability_report(source: ReportSource) -> ReportDataset:
    orders = source.records
    payments = _confirmed_payments(_documents(source, "order_payments"))
    expenses = _documents(source, "monthly_expenses")
    billed = sum(safe_number(row.get("totalPayable")) for row in orders)
    service_sales = sum(safe_number(row.get("serviceTotal")) for row in orders)
    logistics_sales = sum(safe_number(row.get("logisticsTotal")) for row in orders)
    cash_collected = sum(_signed_amount(row) for row in payments)
    expense_total = sum(
        safe_number(row.get("amount"))
        or safe_number(row.get("totalExpenses"))
        for row in expenses
    )
    platform_fees = sum(safe_number(row.get("seanosisServiceFee")) for row in orders)
    estimated_operating_result = service_sales - expense_total - platform_fees
    cash_contribution = cash_collected - expense_total
    charts: list[ChartSpec] = []
    add_chart(charts, top_value_chart("Billed Sales Composition", [
        ("Services", service_sales), ("Logistics", logistics_sales),
    ]))
    add_chart(charts, top_value_chart("Revenue and Cost Position", [
        ("Billed", billed), ("Cash Collected", cash_collected), ("Recorded Expenses", expense_total),
    ]))
    return ReportDataset(
        title="Profitability and Cash Contribution Report",
        metrics=[
            ("Billed Sales", money_text(billed)),
            ("Cash Collected", money_text(cash_collected)),
            ("Recorded Expenses", money_text(expense_total)),
            ("Operating Result", money_text(estimated_operating_result)),
            ("Cash Contribution", money_text(cash_contribution)),
        ],
        headers=[
            "Billed Sales", "Service Sales", "Logistics Sales", "Cash Collected",
            "Recorded Expenses", "Platform Fees", "Estimated Operating Result", "Cash Contribution",
        ],
        rows=[[
            billed, service_sales, logistics_sales, cash_collected, expense_total,
            platform_fees, estimated_operating_result, cash_contribution,
        ]],
        charts=charts,
        analytical_context={
            "billed_sales": billed,
            "service_sales": service_sales,
            "logistics_sales": logistics_sales,
            "cash_collected": cash_collected,
            "recorded_expenses": expense_total,
            "platform_fees_accrued": platform_fees,
            "estimated_operating_result": estimated_operating_result,
            "cash_contribution_after_recorded_expenses": cash_contribution,
            "collection_rate_percent": percentage(cash_collected, billed),
            "expense_scope_note": "Expenses use actual dated records in the selected period; legacy monthly records are not prorated.",
        },
    )


def build_settlement_report(source: ReportSource) -> ReportDataset:
    settlements = source.records
    status_counts = Counter(str(row.get("status") or "Unknown") for row in settlements)
    total = sum(safe_number(row.get("amount")) for row in settlements)
    completed = [row for row in settlements if str(row.get("status") or "").lower() in {"completed", "successful", "paid"}]
    completed_total = sum(safe_number(row.get("amount")) for row in completed)
    charts: list[ChartSpec] = []
    add_chart(charts, distribution_chart("Settlement Outcomes", status_counts))
    add_chart(charts, daily_chart("Settlement Request Value", settlements, "createdAt", "amount"))
    return ReportDataset(
        title="Settlement Report",
        metrics=[
            ("Requests", str(len(settlements))),
            ("Requested Value", money_text(total)),
            ("Completed Value", money_text(completed_total)),
            ("Completion Rate", percentage_text(len(completed), len(settlements))),
        ],
        headers=["Reference", "Amount", "Currency", "Provider", "Source", "Status", "Requested", "Updated"],
        rows=[[
            row.get("reference", ""), safe_number(row.get("amount")), row.get("currency", ""),
            row.get("paymentProvider", ""), row.get("source", ""), row.get("status", ""),
            excel_datetime(row.get("requestedAt") or row.get("createdAt")), excel_datetime(row.get("updatedAt")),
        ] for row in settlements],
        charts=charts,
        analytical_context={
            "settlement_request_count": len(settlements),
            "requested_value": total,
            "completed_value": completed_total,
            "completion_rate_percent": percentage(len(completed), len(settlements)),
            "status_distribution": dict(status_counts),
            "settlement_note": "Settlements are wallet transfers and are not treated as revenue or operating expenses.",
        },
    )


def build_wallet_transaction_report(source: ReportSource) -> ReportDataset:
    transactions = source.records
    credits = sum(safe_number(row.get("amount")) for row in transactions if str(row.get("direction")).lower() == "credit")
    debits = sum(safe_number(row.get("amount")) for row in transactions if str(row.get("direction")).lower() == "debit")
    type_counts = Counter(str(row.get("type") or "Unknown") for row in transactions)
    signed_rows = [
        {
            **row,
            "_effectiveDate": row.get("postedAt") or row.get("createdAt"),
            "signedAmount": safe_number(row.get("amount"))
            * (-1 if str(row.get("direction")).lower() == "debit" else 1),
        }
        for row in transactions
    ]
    charts: list[ChartSpec] = []
    add_chart(charts, daily_chart("Net Wallet Movement", signed_rows, "_effectiveDate", "signedAmount"))
    add_chart(charts, top_value_chart("Wallet Inflow and Outflow", [("Credits", credits), ("Debits", debits)]))
    add_chart(charts, distribution_chart("Wallet Transaction Types", type_counts))
    return ReportDataset(
        title="Wallet Transaction Report",
        metrics=[
            ("Transactions", str(len(transactions))),
            ("Credits", money_text(credits)),
            ("Debits", money_text(debits)),
            ("Net Movement", money_text(credits - debits)),
        ],
        headers=["Reference", "Direction", "Type", "Amount", "Balance Before", "Balance After", "Status", "Posted"],
        rows=[[
            row.get("reference", ""), row.get("direction", ""), row.get("type", ""),
            safe_number(row.get("amount")), safe_number(row.get("balanceBefore")), safe_number(row.get("balanceAfter")),
            row.get("status", ""), excel_datetime(row.get("postedAt") or row.get("createdAt")),
        ] for row in transactions],
        charts=charts,
        analytical_context={
            "wallet_credit_total": credits,
            "wallet_debit_total": debits,
            "net_wallet_movement": credits - debits,
            "transaction_type_distribution": dict(type_counts),
            "transaction_note": "Wallet movement is cash movement and is not automatically classified as revenue or expense.",
        },
    )


def _build_item_or_service_report(source: ReportSource, dimension: str) -> ReportDataset:
    item_rows = _order_item_rows(source)
    key = "serviceName" if dimension == "services" else "itemName"
    aggregates: dict[str, dict[str, float]] = defaultdict(lambda: {"lines": 0, "revenue": 0, "add_ons": 0, "variants": 0})
    for row in item_rows:
        aggregate = aggregates[row[key]]
        aggregate["lines"] += 1
        aggregate["revenue"] += row["subtotal"]
        aggregate["add_ons"] += row["addOnTotal"]
        aggregate["variants"] += row["variantTotal"]
    total_revenue = sum(row["revenue"] for row in aggregates.values())
    charts: list[ChartSpec] = []
    label = "Service" if dimension == "services" else "Item"
    add_chart(charts, top_value_chart(f"Revenue by {label}", [
        (name, values["revenue"]) for name, values in aggregates.items()
    ]))
    add_chart(charts, top_value_chart(f"Volume by {label}", [
        (name, values["lines"]) for name, values in aggregates.items()
    ]))
    sorted_rows = sorted(aggregates.items(), key=lambda row: row[1]["revenue"], reverse=True)
    return ReportDataset(
        title=f"{label} Performance Report",
        metrics=[
            (f"Distinct {label}s", str(len(aggregates))),
            ("Item Lines", str(len(item_rows))),
            ("Attributed Revenue", money_text(total_revenue)),
            ("Average per Line", money_text(total_revenue / len(item_rows) if item_rows else 0)),
        ],
        headers=[label, "Item Lines", "Revenue", "Average Revenue", "Add-on Revenue", "Variant Revenue"],
        rows=[[
            name, int(values["lines"]), values["revenue"],
            values["revenue"] / values["lines"] if values["lines"] else 0,
            values["add_ons"], values["variants"],
        ] for name, values in sorted_rows],
        charts=charts,
        analytical_context={
            "distinct_dimensions": len(aggregates),
            "item_line_count": len(item_rows),
            "attributed_revenue": total_revenue,
            "top_performers": [
                {"name": name, "revenue": values["revenue"], "lines": values["lines"]}
                for name, values in sorted_rows[:5]
            ],
            "unknown_line_count": int(aggregates.get("Unknown", {}).get("lines", 0)),
        },
    )


def build_financial_reconciliation_report(source: ReportSource) -> ReportDataset:
    payments = source.records
    receipts = _documents(source, "customer_payments")
    allocations = _documents(source, "allocations")
    ledger_entries = _documents(source, "ledger_entries")
    orders = {row.get("_id"): row for row in _documents(source, "orders")}
    receipts_by_id = {row.get("_id"): row for row in receipts}
    allocations_by_payment: dict[ObjectId, float] = defaultdict(float)
    allocations_by_order: dict[ObjectId, float] = defaultdict(float)
    for allocation in allocations:
        allocations_by_payment[allocation.get("customerPaymentId")] += safe_number(allocation.get("amount"))
        allocations_by_order[allocation.get("orderId")] += safe_number(allocation.get("amount"))
    ledger_by_payment: dict[ObjectId, dict[str, float]] = defaultdict(lambda: {"credit": 0, "debit": 0})
    for entry in ledger_entries:
        direction = str(entry.get("direction") or "").lower()
        if direction in {"credit", "debit"}:
            ledger_by_payment[entry.get("orderPaymentId")][direction] += safe_number(entry.get("amount"))

    confirmed = _confirmed_payments(payments)
    payment_total = sum(_signed_amount(row) for row in confirmed)
    receipt_total = sum(_signed_amount(row, "totalAmount") for row in receipts)
    allocation_total = sum(safe_number(row.get("amount")) for row in allocations)
    ledger_credit = sum(safe_number(row.get("amount")) for row in ledger_entries if str(row.get("direction")).lower() == "credit")
    ledger_debit = sum(safe_number(row.get("amount")) for row in ledger_entries if str(row.get("direction")).lower() == "debit")
    charts: list[ChartSpec] = []
    add_chart(charts, top_value_chart("Reconciliation Stage Coverage", [
        ("Confirmed Payments", payment_total),
        ("Receipt Headers", receipt_total),
        ("Allocations", allocation_total),
        ("Ledger Credits", ledger_credit),
    ]))
    return ReportDataset(
        title="Financial Reconciliation Report",
        metrics=[
            ("Confirmed Payments", money_text(payment_total)),
            ("Receipt Headers", money_text(receipt_total)),
            ("Allocated", money_text(allocation_total)),
            ("Ledger Credits", money_text(ledger_credit)),
            ("Missing Receipts", str(source.data_quality.get("missing_receipt_references", 0))),
        ],
        headers=[
            "Order", "Customer", "Payment Amount", "Payment Status", "Receipt Found",
            "Receipt Amount", "Allocated Amount", "Ledger Credit", "Ledger Debit", "Payment Date",
        ],
        rows=[[
            (orders.get(row.get("orderId")) or {}).get("orderCode", ""), _payment_name(row),
            safe_number(row.get("amount")), row.get("status", ""),
            row.get("customerPaymentId") in receipts_by_id,
            safe_number((receipts_by_id.get(row.get("customerPaymentId")) or {}).get("totalAmount")),
            allocations_by_payment.get(row.get("customerPaymentId"), 0)
            or allocations_by_order.get(row.get("orderId"), 0),
            ledger_by_payment.get(row.get("_id"), {}).get("credit", 0),
            ledger_by_payment.get(row.get("_id"), {}).get("debit", 0),
            excel_datetime(_payment_date(row)),
        ] for row in payments],
        charts=charts,
        analytical_context={
            "confirmed_order_payment_total": payment_total,
            "customer_receipt_total": receipt_total,
            "payment_allocation_total": allocation_total,
            "ledger_credit_total": ledger_credit,
            "ledger_debit_total": ledger_debit,
            "missing_receipt_references": source.data_quality.get("missing_receipt_references", 0),
            "missing_order_references": source.data_quality.get("missing_order_references", 0),
            "reconciliation_note": "These totals represent stages of the same money flow and must not be added together.",
        },
    )


BUILDERS = {
    "laundry": build_laundry_report,
    "bank_account": build_bank_account_report,
    "customers": build_customer_report,
    "debts": build_debt_report,
    "members": build_member_report,
    "wallet": build_wallet_report,
    "logistics": build_logistics_report,
    "payments": build_payment_report,
    "orders": build_order_report,
    "expenses": build_expense_report,
    "profitability": build_profitability_report,
    "settlements": build_settlement_report,
    "wallet_transactions": build_wallet_transaction_report,
    "services": lambda source: _build_item_or_service_report(source, "services"),
    "items": lambda source: _build_item_or_service_report(source, "items"),
    "financial_reconciliation": build_financial_reconciliation_report,
}


def build_enriched_report_dataset(entity: str, source: ReportSource) -> ReportDataset:
    builder = BUILDERS.get(entity)
    if builder is None:
        raise ValueError("Unsupported report entity.")
    return builder(source)

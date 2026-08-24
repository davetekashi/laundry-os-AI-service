from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from app.schemas.context import ContextRole


def isoformat_or_none(value: Any) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    return None


def datetime_sort_key(value: Any) -> float:
    if not isinstance(value, datetime):
        return float("-inf")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def mask_account_number(account_number: str | None) -> str | None:
    if not account_number:
        return None
    if len(account_number) <= 4:
        return account_number
    return f"{'*' * (len(account_number) - 4)}{account_number[-4:]}"


def sum_numbers(documents: list[dict], field_name: str) -> float:
    return float(sum(float(doc.get(field_name, 0) or 0) for doc in documents))


def build_laundry_summary(laundry: dict) -> dict:
    return {
        "laundry_name": laundry.get("laundryName"),
        "laundry_code": laundry.get("laundryCode"),
        "slug": laundry.get("slug"),
        "state": laundry.get("state"),
        "country": laundry.get("country"),
        "plan_type": laundry.get("planType"),
        "account_type": laundry.get("accountType"),
        "status": laundry.get("status"),
        "is_active": laundry.get("isActive"),
        "is_paused": laundry.get("isPaused"),
        "is_verified": laundry.get("isVerified"),
        "email_verified": laundry.get("emailVerified"),
        "phone_verified": laundry.get("phoneVerified"),
        "commission_balance_due": laundry.get("commissionBalanceDue", 0),
        "offline_commission_accrued": laundry.get("offlineCommissionAccrued", 0),
        "offline_commission_settled": laundry.get("offlineCommissionSettled", 0),
        "offline_commission_balance_due": laundry.get("offlineCommissionBalanceDue", 0),
        "commission_suspended": laundry.get("commissionSuspended"),
        "debt_policy": laundry.get("debtPolicy", {}),
        "created_at": isoformat_or_none(laundry.get("createdAt")),
        "updated_at": isoformat_or_none(laundry.get("updatedAt")),
    }


def build_bank_account_summary(bank_account: dict | None) -> dict | None:
    if not bank_account:
        return None

    return {
        "bank_name": bank_account.get("bankName"),
        "bank_code": bank_account.get("bankCode"),
        "account_name": bank_account.get("accountName"),
        "account_number_masked": mask_account_number(bank_account.get("accountNumber")),
        "is_default": bank_account.get("isDefault"),
        "status": bank_account.get("status"),
        "verified_at": isoformat_or_none(bank_account.get("verifiedAt")),
    }


def build_wallet_summary(wallet: dict | None) -> dict | None:
    if not wallet:
        return None

    return {
        "currency": wallet.get("currency"),
        "available_balance": wallet.get("availableBalance", 0),
        "pending_balance": wallet.get("pendingBalance", 0),
        "is_frozen": wallet.get("isFrozen"),
        "last_transaction_at": isoformat_or_none(wallet.get("lastTransactionAt")),
        "updated_at": isoformat_or_none(wallet.get("updatedAt")),
    }


def build_customer_summary(customers: list[dict]) -> dict:
    active_count = sum(1 for customer in customers if customer.get("isActive"))
    credit_enabled_count = sum(
        1 for customer in customers if customer.get("creditEnabled")
    )
    recent_customers = sorted(
        customers,
        key=lambda customer: datetime_sort_key(
            customer.get("lastOrderAt") or customer.get("createdAt")
        ),
        reverse=True,
    )[:5]

    return {
        "total_customers": len(customers),
        "active_customers": active_count,
        "inactive_customers": len(customers) - active_count,
        "credit_enabled_customers": credit_enabled_count,
        "recent_customers": [
            {
                "full_name": " ".join(
                    part
                    for part in [customer.get("firstName"), customer.get("lastName")]
                    if part
                ).strip(),
                "phone_number": customer.get("phoneNumber"),
                "email": customer.get("email"),
                "last_order_at": isoformat_or_none(customer.get("lastOrderAt")),
                "created_at": isoformat_or_none(customer.get("createdAt")),
            }
            for customer in recent_customers
        ],
    }


def build_member_summary(members: list[dict]) -> dict:
    role_counts = Counter(member.get("role", "unknown") for member in members)
    status_counts = Counter(member.get("status", "unknown") for member in members)
    active_count = sum(1 for member in members if member.get("isActive"))

    recent_members = sorted(
        members,
        key=lambda member: datetime_sort_key(
            member.get("lastLoginAt") or member.get("createdAt")
        ),
        reverse=True,
    )[:5]

    return {
        "total_members": len(members),
        "active_members": active_count,
        "inactive_members": len(members) - active_count,
        "roles": dict(role_counts),
        "statuses": dict(status_counts),
        "recent_member_activity": [
            {
                "username": member.get("username"),
                "role": member.get("role"),
                "status": member.get("status"),
                "last_login_at": isoformat_or_none(member.get("lastLoginAt")),
            }
            for member in recent_members
        ],
    }


def build_debt_summary(debts: list[dict]) -> dict:
    status_counts = Counter(debt.get("status", "unknown") for debt in debts)
    outstanding_debts = [debt for debt in debts if float(debt.get("balanceDue", 0) or 0) > 0]
    top_outstanding = sorted(
        outstanding_debts,
        key=lambda debt: float(debt.get("balanceDue", 0) or 0),
        reverse=True,
    )[:5]

    return {
        "total_debt_records": len(debts),
        "status_counts": dict(status_counts),
        "total_amount": sum_numbers(debts, "totalAmount"),
        "amount_paid": sum_numbers(debts, "amountPaid"),
        "balance_due": sum_numbers(debts, "balanceDue"),
        "top_outstanding_debts": [
            {
                "customer_name": debt.get("customerSnapshot", {}).get("fullName"),
                "order_code": debt.get("orderCode"),
                "order_number": debt.get("orderNumber"),
                "balance_due": debt.get("balanceDue", 0),
                "status": debt.get("status"),
                "opened_at": isoformat_or_none(debt.get("openedAt")),
                "settled_at": isoformat_or_none(debt.get("settledAt")),
            }
            for debt in top_outstanding
        ],
    }


def build_payment_summary(payments: list[dict]) -> dict:
    status_counts = Counter(payment.get("status", "unknown") for payment in payments)
    method_counts = Counter(payment.get("method", "unknown") for payment in payments)
    channel_counts = Counter(
        payment.get("paymentChannel", "unknown") for payment in payments
    )

    top_payers: dict[str, float] = defaultdict(float)
    for payment in payments:
        payer_name = payment.get("payerSnapshot", {}).get("fullName") or "Unknown"
        top_payers[payer_name] += float(payment.get("totalAmount", 0) or 0)

    top_payer_rows = sorted(top_payers.items(), key=lambda row: row[1], reverse=True)[:5]

    recent_payments = sorted(
        payments,
        key=lambda payment: datetime_sort_key(
            payment.get("paidAt") or payment.get("createdAt")
        ),
        reverse=True,
    )[:5]

    return {
        "total_payments": len(payments),
        "total_amount_received": sum(
            (-1 if str(payment.get("transactionType") or "").lower() == "refund" else 1)
            * float(payment.get("totalAmount", 0) or 0)
            for payment in payments
        ),
        "status_counts": dict(status_counts),
        "method_counts": dict(method_counts),
        "payment_channel_counts": dict(channel_counts),
        "top_payers": [
            {"customer_name": customer_name, "total_paid": total_paid}
            for customer_name, total_paid in top_payer_rows
        ],
        "recent_payments": [
            {
                "customer_name": payment.get("payerSnapshot", {}).get("fullName"),
                "amount": payment.get("totalAmount", 0),
                "method": payment.get("method"),
                "status": payment.get("status"),
                "paid_at": isoformat_or_none(payment.get("paidAt")),
            }
            for payment in recent_payments
        ],
    }


def build_order_summary(orders: list[dict]) -> dict:
    order_status_counts = Counter(order.get("orderStatus", "unknown") for order in orders)
    payment_status_counts = Counter(
        order.get("paymentStatus", "unknown") for order in orders
    )
    service_mode_counts = Counter(
        order.get("fulfillmentInfo", {}).get("method")
        or order.get("fulfillmentInfo", {}).get("serviceMode", "unknown")
        for order in orders
    )

    pickup_completed = sum(1 for order in orders if order.get("pickupCompleted"))
    return_completed = sum(1 for order in orders if order.get("returnCompleted"))

    top_orders = sorted(
        orders,
        key=lambda order: float(order.get("totalPayable", 0) or 0),
        reverse=True,
    )[:5]

    item_volume = sum(int(order.get("itemCount", 0) or 0) for order in orders)

    return {
        "total_orders": len(orders),
        "total_order_value": sum_numbers(orders, "totalPayable"),
        "total_amount_paid": sum_numbers(orders, "totalAmountPaid"),
        "total_balance_due": sum_numbers(orders, "totalBalanceDue"),
        "service_total": sum_numbers(orders, "serviceTotal"),
        "logistics_total": sum_numbers(orders, "logisticsTotal"),
        "item_volume": item_volume,
        "order_status_counts": dict(order_status_counts),
        "payment_status_counts": dict(payment_status_counts),
        "service_mode_counts": dict(service_mode_counts),
        "pickup_completed_count": pickup_completed,
        "return_completed_count": return_completed,
        "top_orders": [
            {
                "order_code": order.get("orderCode"),
                "order_number": order.get("orderNumber"),
                "customer_name": order.get("customerSnapshot", {}).get("fullName"),
                "total_payable": order.get("totalPayable", 0),
                "order_status": order.get("orderStatus"),
                "payment_status": order.get("paymentStatus"),
                "created_at": isoformat_or_none(order.get("createdAt")),
            }
            for order in top_orders
        ],
    }


def build_logistics_summary(logistics_jobs: list[dict], orders: list[dict]) -> dict:
    if logistics_jobs:
        status_counts = Counter(job.get("status", "unknown") for job in logistics_jobs)
        return {
            "jobs_available": True,
            "total_logistics_jobs": len(logistics_jobs),
            "status_counts": dict(status_counts),
        }

    return {
        "jobs_available": False,
        "message": "No logistics job records exist yet; logistics insight currently comes from order totals and fulfillment flags.",
        "order_logistics_total": sum_numbers(orders, "logisticsTotal"),
        "order_logistics_amount_paid": sum_numbers(orders, "logisticsAmountPaid"),
        "order_logistics_balance_due": sum_numbers(orders, "logisticsBalanceDue"),
    }


def build_staff_laundry_summary(laundry: dict) -> dict:
    return {
        "laundry_name": laundry.get("laundryName"),
        "laundry_code": laundry.get("laundryCode"),
        "slug": laundry.get("slug"),
        "state": laundry.get("state"),
        "country": laundry.get("country"),
        "status": laundry.get("status"),
        "is_active": laundry.get("isActive"),
        "is_paused": laundry.get("isPaused"),
    }


def build_workspace_summary(
    settings: dict | None,
    business_settings: dict | None = None,
    branch_settings: list[dict] | None = None,
) -> dict:
    settings = settings or {}
    business_settings = business_settings or {}
    branch_settings = branch_settings or []
    operations = (
        settings.get("operations")
        or business_settings.get("operations")
        or (business_settings.get("values") or {}).get("operations")
        or {}
    )
    branch_values = [setting.get("values") or {} for setting in branch_settings]
    return {
        "default_turnaround_days": operations.get("defaultTurnaroundDays"),
        "operating_hours": operations.get("operatingHours"),
        "pickup_enabled": operations.get("pickupEnabled"),
        "delivery_enabled": operations.get("deliveryEnabled"),
        "notifications_configured": bool(settings.get("notifications")),
        "configured_branch_count": len(branch_settings),
        "payment_methods_configured": any(
            values.get("paymentMethods") for values in branch_values
        ),
    }


def build_conversation_identity(
    laundry: dict,
    members: list[dict],
    role: ContextRole,
) -> dict:
    identity = {"laundry_name": laundry.get("laundryName")}
    if not role.has_financial_access:
        return identity

    owner_member_id = laundry.get("ownerMemberId")
    owner = next(
        (
            member
            for member in members
            if owner_member_id is not None and member.get("_id") == owner_member_id
        ),
        None,
    )
    if owner is None:
        owner = next(
            (
                member
                for member in members
                if str(member.get("role") or "").casefold() == "owner"
            ),
            None,
        )
    if owner and owner.get("firstName"):
        identity["owner_first_name"] = str(owner["firstName"]).strip()
    return identity


def build_staff_customer_summary(customers: list[dict]) -> dict:
    active_count = sum(1 for customer in customers if customer.get("isActive"))
    recent_customers = sorted(
        customers,
        key=lambda customer: datetime_sort_key(
            customer.get("lastOrderAt") or customer.get("createdAt")
        ),
        reverse=True,
    )[:5]
    return {
        "total_customers": len(customers),
        "active_customers": active_count,
        "inactive_customers": len(customers) - active_count,
        "recent_customers": [
            {
                "full_name": " ".join(
                    str(part)
                    for part in (customer.get("firstName"), customer.get("lastName"))
                    if part
                ).strip(),
                "phone_number": customer.get("phoneNumber"),
                "email": customer.get("email"),
                "last_order_at": isoformat_or_none(customer.get("lastOrderAt")),
            }
            for customer in recent_customers
        ],
    }


def build_staff_order_summary(orders: list[dict]) -> dict:
    order_status_counts = Counter(order.get("orderStatus", "unknown") for order in orders)
    payment_status_counts = Counter(
        order.get("paymentStatus", "unknown") for order in orders
    )
    service_mode_counts = Counter(
        (order.get("fulfillmentInfo") or {}).get("method")
        or (order.get("fulfillmentInfo") or {}).get("serviceMode", "unknown")
        for order in orders
    )
    recent_orders = sorted(
        orders,
        key=lambda order: datetime_sort_key(order.get("createdAt")),
        reverse=True,
    )[:10]
    return {
        "total_orders": len(orders),
        "item_volume": sum(int(order.get("itemCount", 0) or 0) for order in orders),
        "order_status_counts": dict(order_status_counts),
        "payment_status_counts": dict(payment_status_counts),
        "service_mode_counts": dict(service_mode_counts),
        "pickup_completed_count": sum(1 for order in orders if order.get("pickupCompleted")),
        "return_completed_count": sum(1 for order in orders if order.get("returnCompleted")),
        "recent_orders": [
            {
                "order_code": order.get("orderCode"),
                "order_number": order.get("orderNumber"),
                "customer_name": (order.get("customerSnapshot") or {}).get("fullName"),
                "item_count": order.get("itemCount", 0),
                "order_status": order.get("orderStatus"),
                "payment_status": order.get("paymentStatus"),
                "created_at": isoformat_or_none(order.get("createdAt")),
            }
            for order in recent_orders
        ],
    }


def build_operational_logistics_summary(
    logistics_jobs: list[dict],
    dispatches: list[dict],
    drivers: list[dict],
) -> dict:
    recent_jobs = sorted(
        logistics_jobs,
        key=lambda job: datetime_sort_key(job.get("createdAt")),
        reverse=True,
    )[:10]
    return {
        "total_logistics_jobs": len(logistics_jobs),
        "job_status_counts": dict(
            Counter(job.get("status", "unknown") for job in logistics_jobs)
        ),
        "total_dispatches": len(dispatches),
        "dispatch_status_counts": dict(
            Counter(dispatch.get("status", "unknown") for dispatch in dispatches)
        ),
        "total_drivers": len(drivers),
        "active_drivers": sum(1 for driver in drivers if driver.get("isActive")),
        "recent_jobs": [
            {
                "job_id": str(job.get("_id")) if job.get("_id") else None,
                "order_id": str(job.get("orderId")) if job.get("orderId") else None,
                "type": job.get("jobType") or job.get("type"),
                "status": job.get("status"),
                "scheduled_at": isoformat_or_none(job.get("scheduledAt")),
                "created_at": isoformat_or_none(job.get("createdAt")),
            }
            for job in recent_jobs
        ],
    }


def _payment_date(payment: dict) -> Any:
    return (
        payment.get("paidAt")
        or payment.get("transactionDate")
        or payment.get("confirmedAt")
        or payment.get("recordedAt")
        or payment.get("createdAt")
    )


def build_order_payment_summary(payments: list[dict]) -> dict:
    confirmed_statuses = {"confirmed", "completed", "paid", "success", "successful"}
    confirmed = [
        payment
        for payment in payments
        if str(payment.get("status") or "").lower() in confirmed_statuses
    ]
    recent = sorted(
        payments,
        key=lambda payment: datetime_sort_key(_payment_date(payment)),
        reverse=True,
    )[:5]
    return {
        "total_payment_events": len(payments),
        "confirmed_payment_events": len(confirmed),
        "confirmed_collection_total": sum(
            (-1 if str(payment.get("transactionType") or "").lower() == "refund" else 1)
            * float(payment.get("amount", 0) or 0)
            for payment in confirmed
        ),
        "service_collection_total": sum(
            (-1 if str(payment.get("transactionType") or "").lower() == "refund" else 1)
            * float(payment.get("serviceAmount", 0) or 0)
            for payment in confirmed
        ),
        "delivery_collection_total": sum(
            (-1 if str(payment.get("transactionType") or "").lower() == "refund" else 1)
            * float(payment.get("deliveryAmount", 0) or 0)
            for payment in confirmed
        ),
        "refund_total": sum(
            float(payment.get("amount", 0) or 0)
            for payment in confirmed
            if str(payment.get("transactionType") or "").lower() == "refund"
        ),
        "status_counts": dict(Counter(payment.get("status", "unknown") for payment in payments)),
        "method_counts": dict(
            Counter(
                payment.get("offlineMethod")
                or payment.get("paymentChannel")
                or payment.get("method")
                or "unknown"
                for payment in confirmed
            )
        ),
        "recent_payments": [
            {
                "customer_name": (
                    (payment.get("payerSnapshot") or {}).get("fullName")
                    or (payment.get("customerSnapshot") or {}).get("fullName")
                ),
                "amount": payment.get("amount", 0),
                "status": payment.get("status"),
                "method": payment.get("offlineMethod")
                or payment.get("paymentChannel")
                or payment.get("method"),
                "payment_date": isoformat_or_none(_payment_date(payment)),
            }
            for payment in recent
        ],
    }


def build_reconciliation_summary(
    customer_payments: list[dict],
    allocations: list[dict],
    ledger_entries: list[dict],
) -> dict:
    return {
        "customer_receipt_count": len(customer_payments),
        "customer_receipt_total": sum(
            (-1 if str(payment.get("transactionType") or "").lower() == "refund" else 1)
            * float(payment.get("totalAmount", 0) or 0)
            for payment in customer_payments
        ),
        "allocation_count": len(allocations),
        "allocated_total": sum_numbers(allocations, "amount"),
        "ledger_entry_count": len(ledger_entries),
        "ledger_credit_total": sum(
            float(entry.get("amount", 0) or 0)
            for entry in ledger_entries
            if str(entry.get("direction") or "").lower() == "credit"
        ),
        "ledger_debit_total": sum(
            float(entry.get("amount", 0) or 0)
            for entry in ledger_entries
            if str(entry.get("direction") or "").lower() == "debit"
        ),
        "accounting_note": (
            "Payment, receipt, allocation and ledger totals are stages of the same money flow "
            "and must not be added together."
        ),
    }


def build_wallet_activity_summary(transactions: list[dict]) -> dict:
    credits = sum(
        float(row.get("amount", 0) or 0)
        for row in transactions
        if str(row.get("direction") or "").lower() == "credit"
    )
    debits = sum(
        float(row.get("amount", 0) or 0)
        for row in transactions
        if str(row.get("direction") or "").lower() == "debit"
    )
    return {
        "transaction_count": len(transactions),
        "credit_total": credits,
        "debit_total": debits,
        "net_movement": credits - debits,
        "type_counts": dict(Counter(row.get("type", "unknown") for row in transactions)),
    }


def build_expense_summary(monthly_expenses: list[dict]) -> dict:
    category_totals: dict[str, float] = defaultdict(float)
    entry_count = 0
    direct_total = 0.0
    for document in monthly_expenses:
        if "amount" in document:
            entry_count += 1
            amount = float(document.get("amount", 0) or 0)
            direct_total += amount
            category_totals[str(document.get("category") or "Uncategorized")] += amount
            continue
        for entry in document.get("entries") or []:
            entry_count += 1
            category_totals[str(entry.get("category") or "Uncategorized")] += float(
                entry.get("amount", 0) or 0
            )
    dated_months = {
                (document.get("expenseDate") or document.get("createdAt")).strftime("%Y-%m")
                for document in monthly_expenses
                if isinstance(
                    document.get("expenseDate") or document.get("createdAt"),
                    datetime,
                )
            }
    legacy_months = {
        (document.get("year"), document.get("monthNumber"))
        for document in monthly_expenses
        if document.get("year") and document.get("monthNumber")
    }
    return {
        "months_recorded": len(dated_months) + len(legacy_months),
        "expense_entry_count": entry_count,
        "recorded_expense_total": direct_total
        + sum_numbers(monthly_expenses, "totalExpenses"),
        "category_totals": dict(category_totals),
    }


def build_settlement_summary(settlements: list[dict]) -> dict:
    completed_statuses = {"completed", "successful", "paid"}
    completed = [
        settlement
        for settlement in settlements
        if str(settlement.get("status") or "").lower() in completed_statuses
    ]
    return {
        "settlement_count": len(settlements),
        "requested_total": sum_numbers(settlements, "amount"),
        "completed_total": sum_numbers(completed, "amount"),
        "status_counts": dict(
            Counter(settlement.get("status", "unknown") for settlement in settlements)
        ),
    }


def build_catalog_summary(raw_context: dict) -> dict:
    global_services = {
        service.get("_id"): service.get("name") or service.get("slug")
        for service in raw_context.get("global_services", [])
    }
    global_types = {
        item_type.get("_id"): item_type.get("name")
        for item_type in raw_context.get("global_item_types", [])
    }
    item_prices = raw_context.get("item_prices", [])
    configured_services = raw_context.get("laundry_services", [])
    service_names_by_key = {
        service.get("serviceKey"): service.get("name") or service.get("slug")
        for service in configured_services
        if service.get("serviceKey")
    }
    return {
        "configured_service_count": len(configured_services),
        "configured_item_count": len(item_prices),
        "active_add_on_count": sum(
            1 for add_on in raw_context.get("add_on_services", []) if add_on.get("isActive")
        ),
        "services": sorted(
            {
                str(
                    global_services.get(service.get("service"))
                    or service.get("name")
                    or service.get("slug")
                )
                for service in configured_services
                if global_services.get(service.get("service"))
                or service.get("name")
                or service.get("slug")
            }
        ),
        "items": [
            {
                "name": item.get("itemName")
                or item.get("normalizedItemName")
                or global_types.get(item.get("itemType")),
                "service": global_services.get(item.get("service"))
                or service_names_by_key.get(item.get("serviceKey")),
                "price": item.get("price"),
                "active": item.get("isActive"),
            }
            for item in item_prices[:100]
        ],
        "catalog_note": "Item prices are operational selling prices, not revenue or collected income.",
    }


def build_subscription_summary(intents: list[dict]) -> dict:
    latest = max(
        intents,
        key=lambda intent: datetime_sort_key(intent.get("createdAt")),
        default={},
    )
    return {
        "intent_count": len(intents),
        "latest_target_plan": latest.get("targetPlan"),
        "latest_intent_type": latest.get("intentType"),
        "latest_status": latest.get("status"),
    }


def build_context_summary(raw_context: dict, role: ContextRole) -> dict:
    laundry = raw_context["laundry"]
    customers = raw_context["customers"]
    members = raw_context["members"]
    orders = raw_context["orders"]
    logistics_jobs = raw_context["logistics_jobs"]

    common_context = {
        "access_scope": {
            "role": role.value,
            "financial_information_available": role.has_financial_access,
        },
        "conversation_identity": build_conversation_identity(laundry, members, role),
        "laundry_profile": (
            build_laundry_summary(laundry)
            if role.has_financial_access
            else build_staff_laundry_summary(laundry)
        ),
        "workspace": build_workspace_summary(
            raw_context.get("workspace_settings"),
            raw_context.get("business_settings"),
            raw_context.get("branch_settings"),
        ),
        "customers": (
            build_customer_summary(customers)
            if role.has_financial_access
            else build_staff_customer_summary(customers)
        ),
        "members": build_member_summary(members),
        "orders": (
            build_order_summary(orders)
            if role.has_financial_access
            else build_staff_order_summary(orders)
        ),
        "logistics": build_operational_logistics_summary(
            logistics_jobs,
            raw_context.get("dispatches", []),
            raw_context.get("drivers", []),
        ),
        "catalog": build_catalog_summary(raw_context),
    }
    if role == ContextRole.STAFF:
        common_context["access_scope"]["restricted_domains"] = [
            "bank accounts",
            "wallets",
            "payments and collections",
            "debts and credit risk",
            "expenses and profitability",
            "settlements and financial reconciliation",
        ]
        return common_context

    common_context.update(
        {
            "bank_account": build_bank_account_summary(raw_context.get("bank_account")),
            "wallet": build_wallet_summary(raw_context.get("wallet")),
            "wallet_activity": build_wallet_activity_summary(
                raw_context.get("wallet_transactions", [])
            ),
            "debts": build_debt_summary(raw_context.get("debts", [])),
            "payments": build_order_payment_summary(raw_context.get("order_payments", [])),
            "payment_reconciliation": build_reconciliation_summary(
                raw_context.get("customer_payments", []),
                raw_context.get("payment_allocations", []),
                raw_context.get("ledger_entries", []),
            ),
            "expenses": build_expense_summary(raw_context.get("monthly_expenses", [])),
            "settlements": build_settlement_summary(raw_context.get("settlements", [])),
            "subscription": build_subscription_summary(
                raw_context.get("subscription_intents", [])
            ),
        }
    )
    return common_context

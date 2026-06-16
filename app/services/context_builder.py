from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any


def isoformat_or_none(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return None


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
        key=lambda customer: customer.get("lastOrderAt") or customer.get("createdAt") or datetime.min.replace(tzinfo=UTC),
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
        key=lambda member: member.get("lastLoginAt") or member.get("createdAt") or datetime.min.replace(tzinfo=UTC),
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
        key=lambda payment: payment.get("paidAt") or payment.get("createdAt") or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )[:5]

    return {
        "total_payments": len(payments),
        "total_amount_received": sum_numbers(payments, "totalAmount"),
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
        order.get("fulfillmentInfo", {}).get("serviceMode", "unknown")
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


def build_context_summary(raw_context: dict) -> dict:
    laundry = raw_context["laundry"]
    bank_account = raw_context["bank_account"]
    customers = raw_context["customers"]
    debts = raw_context["debts"]
    members = raw_context["members"]
    wallet = raw_context["wallet"]
    payments = raw_context["payments"]
    orders = raw_context["orders"]
    logistics_jobs = raw_context["logistics_jobs"]

    return {
        "laundry_profile": build_laundry_summary(laundry),
        "bank_account": build_bank_account_summary(bank_account),
        "wallet": build_wallet_summary(wallet),
        "customers": build_customer_summary(customers),
        "members": build_member_summary(members),
        "debts": build_debt_summary(debts),
        "payments": build_payment_summary(payments),
        "orders": build_order_summary(orders),
        "logistics": build_logistics_summary(logistics_jobs, orders),
    }

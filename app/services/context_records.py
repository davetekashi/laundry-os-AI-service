from datetime import UTC, datetime
from typing import Any

from app.schemas.context import ContextRole


def _id(value: Any) -> str | None:
    return str(value) if value is not None else None


def _date(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _name(document: dict, snapshot_field: str | None = None) -> str:
    if snapshot_field:
        snapshot = document.get(snapshot_field) or {}
        if snapshot.get("fullName"):
            return str(snapshot["fullName"]).strip()
    return " ".join(
        str(part).strip()
        for part in (document.get("firstName"), document.get("lastName"))
        if part
    ).strip()


def _customer(document: dict) -> dict:
    return {
        "id": _id(document.get("businessCustomerId") or document.get("_id")),
        "full_name": _name(document),
        "phone_number": document.get("phoneNumber"),
        "email": document.get("email"),
        "status": document.get("status"),
        "is_active": bool(document.get("isActive")),
        "credit_enabled": bool(document.get("creditEnabled")),
        "last_order_at": _date(document.get("lastOrderAt")),
        "created_at": _date(document.get("createdAt")),
        "event_at": _date(document.get("createdAt")),
    }


def _order_item(item: dict) -> dict:
    return {
        "item_name": item.get("itemNameSnapshot") or item.get("itemName"),
        "service_name": item.get("serviceNameSnapshot") or item.get("serviceName"),
        "quantity": item.get("quantity") or item.get("pieceCount"),
        "piece_count": item.get("pieceCount") or item.get("quantity"),
    }


def _physical_piece_count(document: dict) -> int:
    if document.get("totalPieceCount") is not None:
        return int(_number(document.get("totalPieceCount")))
    nested_counts = [
        int(_number(item.get("pieceCount")))
        for item in document.get("items") or []
        if item.get("pieceCount") is not None
    ]
    if nested_counts:
        return sum(nested_counts)
    return int(_number(document.get("itemCount")))


def _order(document: dict, include_financial: bool) -> dict:
    fulfillment = document.get("fulfillmentInfo") or {}
    row = {
        "id": _id(document.get("_id")),
        "branch_id": _id(document.get("branchId")),
        "laundry_id": _id(document.get("laundryId")),
        "customer_id": _id(document.get("laundryCustomerId")),
        "customer_name": _name(document, "customerSnapshot"),
        "order_code": document.get("orderCode"),
        "order_number": document.get("orderNumber"),
        "order_status": document.get("orderStatus"),
        "payment_status": document.get("paymentStatus"),
        "service_mode": fulfillment.get("method") or fulfillment.get("serviceMode"),
        "item_count": int(_number(document.get("itemCount"))),
        "total_piece_count": _physical_piece_count(document),
        "items": [_order_item(item) for item in document.get("items") or []],
        "pickup_completed": bool(document.get("pickupCompleted")),
        "return_completed": bool(document.get("returnCompleted")),
        "created_at": _date(document.get("createdAt")),
        "confirmed_at": _date(document.get("confirmedAt")),
        "completed_at": _date(document.get("completedAt")),
        "event_at": _date(document.get("createdAt")),
    }
    if include_financial:
        row.update(
            {
                "service_total": _number(document.get("serviceTotal")),
                "logistics_total": _number(document.get("logisticsTotal")),
                "total_payable": _number(document.get("totalPayable")),
                "total_amount_paid": _number(document.get("totalAmountPaid")),
                "total_balance_due": _number(document.get("totalBalanceDue")),
            }
        )
    return row


def _member(document: dict) -> dict:
    return {
        "id": _id(document.get("_id")),
        "full_name": _name(document),
        "username": document.get("username"),
        "role": document.get("role"),
        "status": document.get("status"),
        "is_active": bool(document.get("isActive")),
        "last_login_at": _date(document.get("lastLoginAt")),
        "created_at": _date(document.get("createdAt")),
        "event_at": _date(document.get("createdAt")),
    }


def _logistics(document: dict) -> dict:
    return {
        "id": _id(document.get("_id")),
        "order_id": _id(document.get("orderId")),
        "customer_id": _id(document.get("laundryCustomerId")),
        "job_type": document.get("jobType") or document.get("type"),
        "status": document.get("status"),
        "pickup_address": document.get("pickupAddress"),
        "delivery_address": document.get("deliveryAddress"),
        "scheduled_at": _date(document.get("scheduledAt")),
        "picked_up_at": _date(document.get("pickedUpAt")),
        "delivered_at": _date(document.get("deliveredAt")),
        "created_at": _date(document.get("createdAt")),
        "event_at": _date(document.get("createdAt")),
    }


def _payment(document: dict) -> dict:
    payment_date = (
        document.get("paidAt")
        or document.get("transactionDate")
        or document.get("confirmedAt")
        or document.get("recordedAt")
        or document.get("createdAt")
    )
    return {
        "id": _id(document.get("_id")),
        "order_id": _id(document.get("orderId")),
        "customer_id": _id(document.get("laundryCustomerId")),
        "customer_name": _name(document, "payerSnapshot")
        or _name(document, "customerSnapshot"),
        "amount": _number(document.get("amount", document.get("totalAmount"))),
        "service_amount": _number(document.get("serviceAmount")),
        "delivery_amount": _number(document.get("deliveryAmount")),
        "method": document.get("offlineMethod")
        or document.get("paymentChannel")
        or document.get("method"),
        "status": document.get("status"),
        "transaction_type": document.get("transactionType"),
        "payment_date": _date(payment_date),
        "event_at": _date(payment_date),
    }


def _expense_rows(document: dict) -> list[dict]:
    expense_date = document.get("expenseDate") or document.get("createdAt")
    if not isinstance(expense_date, datetime):
        try:
            if document.get("year") and document.get("monthNumber"):
                expense_date = datetime(
                    int(document["year"]),
                    int(document["monthNumber"]),
                    1,
                    tzinfo=UTC,
                )
        except (TypeError, ValueError):
            expense_date = None
    if document.get("amount") is not None:
        return [
            {
                "id": _id(document.get("_id")),
                "category": document.get("category") or "Uncategorized",
                "description": document.get("description") or document.get("note"),
                "amount": _number(document.get("amount")),
                "expense_date": _date(expense_date),
                "event_at": _date(expense_date),
            }
        ]

    rows: list[dict] = []
    for index, entry in enumerate(document.get("entries") or []):
        rows.append(
            {
                "id": f"{_id(document.get('_id'))}:{index}",
                "category": entry.get("category") or "Uncategorized",
                "description": entry.get("description") or entry.get("note"),
                "amount": _number(entry.get("amount")),
                "expense_date": _date(expense_date),
                "event_at": _date(expense_date),
                "year": document.get("year"),
                "month_number": document.get("monthNumber"),
            }
        )
    if not rows and document.get("totalExpenses") is not None:
        rows.append(
            {
                "id": _id(document.get("_id")),
                "category": "Monthly total",
                "description": None,
                "amount": _number(document.get("totalExpenses")),
                "expense_date": _date(expense_date),
                "event_at": _date(expense_date),
                "year": document.get("year"),
                "month_number": document.get("monthNumber"),
            }
        )
    return rows


def _debt(document: dict) -> dict:
    return {
        "id": _id(document.get("_id")),
        "order_id": _id(document.get("orderId")),
        "customer_id": _id(document.get("laundryCustomerId")),
        "customer_name": _name(document, "customerSnapshot"),
        "order_code": document.get("orderCode"),
        "order_number": document.get("orderNumber"),
        "total_amount": _number(document.get("totalAmount")),
        "amount_paid": _number(document.get("amountPaid")),
        "balance_due": _number(document.get("balanceDue")),
        "status": document.get("status"),
        "opened_at": _date(document.get("openedAt")),
        "settled_at": _date(document.get("settledAt")),
        "event_at": _date(document.get("openedAt")),
    }


def _settlement(document: dict) -> dict:
    event_at = document.get("requestedAt") or document.get("createdAt")
    return {
        "id": _id(document.get("_id")),
        "amount": _number(document.get("amount")),
        "status": document.get("status"),
        "requested_at": _date(document.get("requestedAt")),
        "completed_at": _date(document.get("completedAt")),
        "event_at": _date(event_at),
    }


def build_retrieval_data(raw_context: dict, role: ContextRole) -> dict[str, list[dict]]:
    data: dict[str, list[dict]] = {
        "customers": [_customer(row) for row in raw_context.get("customers", [])],
        "orders": [
            _order(row, role.has_financial_access)
            for row in raw_context.get("orders", [])
        ],
        "members": [_member(row) for row in raw_context.get("members", [])],
        "logistics": [
            _logistics(row) for row in raw_context.get("logistics_jobs", [])
        ],
    }
    if not role.has_financial_access:
        return data

    expenses = [
        row
        for document in raw_context.get("monthly_expenses", [])
        for row in _expense_rows(document)
    ]
    data.update(
        {
            "payments": [
                _payment(row) for row in raw_context.get("order_payments", [])
            ],
            "expenses": expenses,
            "debts": [_debt(row) for row in raw_context.get("debts", [])],
            "settlements": [
                _settlement(row) for row in raw_context.get("settlements", [])
            ],
        }
    )
    return data

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId

from app.services.mongo import (
    fetch_scope_customers,
    fetch_scope_members,
    get_database,
    orders_to_debts,
)
from app.services.scope import ResolvedScope, resolve_scope


MAX_REPORT_RECORDS = 10_000


@dataclass
class ReportSource:
    entity: str
    records: list[dict]
    related: dict[str, Any] = field(default_factory=dict)
    data_quality: dict[str, int] = field(default_factory=dict)


ORDER_PROJECTION = {
    "orderCode": 1,
    "orderNumber": 1,
    "laundryId": 1,
    "laundryCustomerId": 1,
    "customerSnapshot": 1,
    "createdByStaffId": 1,
    "createdByMemberId": 1,
    "createdByUserId": 1,
    "userId": 1,
    "createdByRole": 1,
    "items": 1,
    "itemCount": 1,
    "itemsSubtotal": 1,
    "discountTotal": 1,
    "taxTotal": 1,
    "serviceTotal": 1,
    "logisticsTotal": 1,
    "totalPayable": 1,
    "totalAmountPaid": 1,
    "totalBalanceDue": 1,
    "serviceAmountPaid": 1,
    "serviceBalanceDue": 1,
    "logisticsAmountPaid": 1,
    "logisticsBalanceDue": 1,
    "seanosisServiceFee": 1,
    "commissionAccrued": 1,
    "orderStatus": 1,
    "paymentStatus": 1,
    "fulfillmentInfo": 1,
    "createdAt": 1,
    "confirmedAt": 1,
    "completedAt": 1,
}

ORDER_PAYMENT_PROJECTION = {
    "orderId": 1,
    "customerPaymentId": 1,
    "laundryCustomerId": 1,
    "customerSnapshot": 1,
    "payerSnapshot": 1,
    "amount": 1,
    "serviceAmount": 1,
    "deliveryAmount": 1,
    "method": 1,
    "offlineMethod": 1,
    "paymentChannel": 1,
    "paymentTargetType": 1,
    "transactionType": 1,
    "status": 1,
    "source": 1,
    "recordedByMemberId": 1,
    "confirmedByMemberId": 1,
    "initiatedAt": 1,
    "recordedAt": 1,
    "confirmedAt": 1,
    "paidAt": 1,
    "createdAt": 1,
}

CUSTOMER_PAYMENT_PROJECTION = {
    "customerId": 1,
    "totalAmount": 1,
    "method": 1,
    "status": 1,
    "transactionType": 1,
    "transactionDate": 1,
    "recordedByMemberId": 1,
    "createdAt": 1,
}


def _limited_find(
    collection,
    query: dict,
    projection: dict | None = None,
    sort_field: str | None = None,
) -> list[dict]:
    cursor = collection.find(query, projection)
    if sort_field:
        cursor = cursor.sort(sort_field, 1)
    documents = list(cursor.limit(MAX_REPORT_RECORDS + 1))
    if len(documents) > MAX_REPORT_RECORDS:
        raise ValueError(
            "The selected report contains more than 10,000 records. "
            "Please use a smaller date range."
        )
    return documents


def _range_query(field: str, start_date: datetime, end_date: datetime) -> dict:
    return {field: {"$gte": start_date, "$lte": end_date}}


def _is_in_range(value: Any, start_date: datetime, end_date: datetime) -> bool:
    if not isinstance(value, datetime):
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=UTC)
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=UTC)
    return start_date <= value <= end_date


def _scope_order_query(scope: ResolvedScope, extra: dict | None = None) -> dict:
    scope_query: dict
    if scope.business_id:
        scope_query = {
            "$or": [
                {"businessId": scope.business_id},
                {"laundryId": scope.laundry_id},
            ]
        }
    else:
        scope_query = {"laundryId": scope.laundry_id}
    if extra:
        return {"$and": [scope_query, extra]}
    return scope_query


def _fallback_date_query(
    fields: list[str],
    start_date: datetime,
    end_date: datetime,
) -> dict:
    expression: Any = f"${fields[-1]}"
    for field_name in reversed(fields[:-1]):
        expression = {"$ifNull": [f"${field_name}", expression]}
    return {
        "$expr": {
            "$and": [
                {"$gte": [expression, start_date]},
                {"$lte": [expression, end_date]},
            ]
        }
    }


def _id_set(documents: list[dict], field_name: str = "_id") -> set[ObjectId]:
    return {
        document[field_name]
        for document in documents
        if isinstance(document.get(field_name), ObjectId)
    }


def _missing_reference_count(
    documents: list[dict],
    field_name: str,
    related_documents: list[dict],
) -> int:
    references = _id_set(documents, field_name)
    related_ids = _id_set(related_documents)
    return len(references - related_ids)


def _catalog_related(db, scope: ResolvedScope, orders: list[dict]) -> dict[str, Any]:
    item_price_ids: set[ObjectId] = set()
    item_type_ids: set[ObjectId] = set()
    service_ids: set[ObjectId] = set()
    for order in orders:
        for item in order.get("items") or []:
            if isinstance(item.get("itemPriceId"), ObjectId):
                item_price_ids.add(item["itemPriceId"])
            if isinstance(item.get("itemType"), ObjectId):
                item_type_ids.add(item["itemType"])
            if isinstance(item.get("service"), ObjectId):
                service_ids.add(item["service"])

    if scope.business_id:
        item_prices = _limited_find(
            db.businessitemprices,
            {"businessId": scope.business_id},
            {
                "itemName": 1,
                "normalizedItemName": 1,
                "serviceKey": 1,
                "price": 1,
                "variants": 1,
            },
        )
        laundry_services = _limited_find(
            db.businessservices,
            {"businessId": scope.business_id},
            {"name": 1, "slug": 1, "serviceKey": 1, "categoryKey": 1},
        )
    else:
        item_prices = _limited_find(
            db.laundryitemprices,
            {"laundryId": scope.laundry_id},
            {
                "itemName": 1,
                "normalizedItemName": 1,
                "service": 1,
                "serviceKey": 1,
                "price": 1,
                "variants": 1,
            },
        )
        laundry_services = _limited_find(
            db.laundryservices,
            {"laundryId": scope.laundry_id},
            {"service": 1, "name": 1, "slug": 1, "serviceKey": 1},
        )
    service_ids.update(_id_set(laundry_services, "service"))
    global_services = _limited_find(
        db.globallaundryservices,
        {"_id": {"$in": list(service_ids)}},
        {"name": 1, "slug": 1},
    )
    global_item_types = _limited_find(
        db.globallaundryitemtypes,
        {"_id": {"$in": list(item_type_ids)}},
        {"name": 1, "itemCategory": 1},
    )
    category_ids = _id_set(global_item_types, "itemCategory")
    categories = _limited_find(
        db.globalitemcategories,
        {"_id": {"$in": list(category_ids)}},
        {"name": 1, "slug": 1},
    )
    add_ons = _limited_find(
        db.businessaddonservices if scope.business_id else db.laundryaddonservices,
        {"businessId": scope.business_id}
        if scope.business_id
        else {"laundryId": scope.laundry_id},
        {"name": 1, "defaultPrice": 1, "isActive": 1},
    )
    return {
        "item_prices": item_prices,
        "laundry_services": laundry_services,
        "global_services": global_services,
        "global_item_types": global_item_types,
        "global_item_categories": categories,
        "add_on_services": add_ons,
    }


def _enrich_payments(
    payments: list[dict],
    receipts: list[dict],
    customers: list[dict] | None = None,
) -> list[dict]:
    receipts_by_id = {row.get("_id"): row for row in receipts}
    customer_names: dict[ObjectId, str] = {}
    for customer in customers or []:
        name = " ".join(
            str(part)
            for part in (customer.get("firstName"), customer.get("lastName"))
            if part
        ).strip()
        if not name:
            continue
        for field_name in (
            "_id",
            "businessCustomerId",
            "legacyLaundryCustomerId",
            "userId",
        ):
            reference = customer.get(field_name)
            if isinstance(reference, ObjectId):
                customer_names[reference] = name

    enriched: list[dict] = []
    for payment in payments:
        row = dict(payment)
        receipt = receipts_by_id.get(payment.get("customerPaymentId"), {})
        if not row.get("method"):
            row["method"] = receipt.get("method")
        if not row.get("paidAt"):
            row["paidAt"] = receipt.get("transactionDate")
        if not row.get("transactionType"):
            row["transactionType"] = receipt.get("transactionType")
        if not row.get("payerSnapshot"):
            customer_name = customer_names.get(payment.get("laundryCustomerId"))
            if customer_name:
                row["payerSnapshot"] = {"fullName": customer_name}
        enriched.append(row)
    return enriched


def _payment_documents_for_period(
    db,
    base_query: dict,
    start_date: datetime,
    end_date: datetime,
    customers: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    receipts = _limited_find(
        db.customerpayments,
        {**base_query, **_range_query("transactionDate", start_date, end_date)},
        CUSTOMER_PAYMENT_PROJECTION,
        "transactionDate",
    )
    receipt_ids = _id_set(receipts)
    payment_query = {
        **base_query,
        "$or": [
            {"customerPaymentId": {"$in": list(receipt_ids)}},
            _fallback_date_query(
                ["paidAt", "confirmedAt", "recordedAt", "createdAt"],
                start_date,
                end_date,
            ),
        ],
    }
    payments = _limited_find(
        db.orderpayments,
        payment_query,
        ORDER_PAYMENT_PROJECTION,
        "createdAt",
    )
    return _enrich_payments(payments, receipts, customers), receipts


def fetch_report_source(
    laundry_id: str | None,
    entity: str,
    start_date: datetime | None,
    end_date: datetime | None,
    business_id: str | None = None,
) -> tuple[dict, ReportSource]:
    db = get_database()
    scope = resolve_scope(db, laundry_id, business_id)
    laundry_object_id = scope.laundry_id
    laundry = scope.laundry

    base_query = {"laundryId": laundry_object_id}
    related: dict[str, Any] = {}
    quality: dict[str, int] = {}
    related["scope"] = scope
    related["business"] = scope.business
    scope_customers = fetch_scope_customers(db, scope)

    if entity == "laundry":
        records = [laundry]
        related["workspace_settings"] = db.laundryworkspacesettings.find_one(base_query)
        related["business_settings"] = (
            db.businesssettings.find_one({"businessId": scope.business_id})
            if scope.business_id
            else None
        )
        related["branch_settings"] = (
            _limited_find(db.branchsettings, {"businessId": scope.business_id})
            if scope.business_id
            else []
        )
        related["subscription_intents"] = _limited_find(
            db.laundrysubscriptionintents,
            base_query,
            {"targetPlan": 1, "intentType": 1, "status": 1, "amount": 1, "createdAt": 1, "activatedAt": 1},
            "createdAt",
        )
    elif entity == "bank_account":
        records = _limited_find(db.laundrybankaccounts, base_query, None, "createdAt")
        related["settlements"] = _limited_find(db.laundrysettlements, base_query, None, "createdAt")
    elif entity == "wallet":
        wallet = db.laundrywallets.find_one(base_query)
        records = [wallet] if wallet else []
        transaction_query = dict(base_query)
        settlement_query = dict(base_query)
        if start_date and end_date:
            transaction_query.update(_fallback_date_query(["postedAt", "createdAt"], start_date, end_date))
            settlement_query.update(_fallback_date_query(["requestedAt", "createdAt"], start_date, end_date))
        related["wallet_transactions"] = _limited_find(
            db.laundrywallettransactions, transaction_query, None, "createdAt"
        )
        related["settlements"] = _limited_find(
            db.laundrysettlements, settlement_query, None, "createdAt"
        )
    else:
        if start_date is None or end_date is None:
            raise ValueError("start_date and end_date are required for this report entity.")

        if entity == "orders":
            records = _limited_find(
                db.orders,
                _scope_order_query(scope, _range_query("createdAt", start_date, end_date)),
                ORDER_PROJECTION,
                "createdAt",
            )
            order_ids = _id_set(records)
            order_payments = _limited_find(
                db.orderpayments,
                {**base_query, "orderId": {"$in": list(order_ids)}},
                ORDER_PAYMENT_PROJECTION,
                "createdAt",
            )
            receipt_ids = _id_set(order_payments, "customerPaymentId")
            order_receipts = _limited_find(
                db.customerpayments,
                {**base_query, "_id": {"$in": list(receipt_ids)}},
                CUSTOMER_PAYMENT_PROJECTION,
            )
            related["order_payments"] = _enrich_payments(
                order_payments, order_receipts, scope_customers
            )
            related["payments_in_period"], related["customer_payments"] = (
                _payment_documents_for_period(
                    db, base_query, start_date, end_date, scope_customers
                )
            )
            related.update(_catalog_related(db, scope, records))
        elif entity == "customers":
            records = [
                customer
                for customer in scope_customers
                if _is_in_range(customer.get("createdAt"), start_date, end_date)
            ]
            customer_ids: set[ObjectId] = set()
            for customer in records:
                for field_name in (
                    "_id",
                    "businessCustomerId",
                    "legacyLaundryCustomerId",
                    "userId",
                ):
                    value = customer.get(field_name)
                    if isinstance(value, ObjectId):
                        customer_ids.add(value)
            related["orders"] = _limited_find(
                db.orders,
                _scope_order_query(
                    scope,
                    {"$or": [
                        {"laundryCustomerId": {"$in": list(customer_ids)}},
                        {"userId": {"$in": list(customer_ids)}},
                    ]},
                ),
                ORDER_PROJECTION,
                "createdAt",
            )
            customer_orders = related["orders"]
            related["debts"] = orders_to_debts(customer_orders)
            payments = _limited_find(
                db.orderpayments,
                {**base_query, "laundryCustomerId": {"$in": list(customer_ids)}},
                ORDER_PAYMENT_PROJECTION,
                "createdAt",
            )
            receipt_ids = _id_set(payments, "customerPaymentId")
            receipts = _limited_find(
                db.customerpayments,
                {**base_query, "_id": {"$in": list(receipt_ids)}},
                CUSTOMER_PAYMENT_PROJECTION,
            )
            related["order_payments"] = _enrich_payments(
                payments, receipts, scope_customers
            )
        elif entity == "debts":
            debt_orders = _limited_find(
                db.orders,
                _scope_order_query(
                    scope,
                    _range_query("createdAt", start_date, end_date),
                ),
                ORDER_PROJECTION,
                "createdAt",
            )
            records = orders_to_debts(debt_orders)
            order_ids = _id_set(records, "orderId")
            related["orders"] = _limited_find(
                db.orders,
                _scope_order_query(scope, {"_id": {"$in": list(order_ids)}}),
                ORDER_PROJECTION,
            )
            related["order_payments"] = _limited_find(
                db.orderpayments,
                {**base_query, "orderId": {"$in": list(order_ids)}},
                ORDER_PAYMENT_PROJECTION,
            )
            quality["missing_order_references"] = _missing_reference_count(
                records, "orderId", related["orders"]
            )
        elif entity == "members":
            records = fetch_scope_members(db, scope)
            related["orders"] = _limited_find(
                db.orders,
                _scope_order_query(scope, _range_query("createdAt", start_date, end_date)),
                ORDER_PROJECTION,
                "createdAt",
            )
            related["order_payments"] = _limited_find(
                db.orderpayments,
                {**base_query, **_fallback_date_query(["paidAt", "confirmedAt", "recordedAt", "createdAt"], start_date, end_date)},
                ORDER_PAYMENT_PROJECTION,
                "createdAt",
            )
        elif entity == "logistics":
            records = _limited_find(
                db.laundrylogisticsjobs,
                {**base_query, **_range_query("createdAt", start_date, end_date)},
                None,
                "createdAt",
            )
            order_ids = _id_set(records, "orderId")
            customer_ids = _id_set(records, "laundryCustomerId")
            related["orders"] = _limited_find(
                db.orders, _scope_order_query(scope, {"_id": {"$in": list(order_ids)}}), ORDER_PROJECTION
            )
            related["customers"] = _limited_find(
                db.laundrycustomers, {**base_query, "_id": {"$in": list(customer_ids)}}
            )
            related["order_payments"] = _limited_find(
                db.orderpayments, {**base_query, "orderId": {"$in": list(order_ids)}}, ORDER_PAYMENT_PROJECTION
            )
            related["dispatches"] = _limited_find(
                db.laundrydispatches,
                {**base_query, **_range_query("createdAt", start_date, end_date)},
            )
            driver_ids = _id_set(related["dispatches"], "driverId")
            related["drivers"] = _limited_find(
                db.laundrydrivers, {**base_query, "_id": {"$in": list(driver_ids)}}
            )
        elif entity == "payments":
            records, period_receipts = _payment_documents_for_period(
                db, base_query, start_date, end_date, scope_customers
            )
            receipt_ids = _id_set(records, "customerPaymentId")
            order_ids = _id_set(records, "orderId")
            related["customer_payments"] = period_receipts
            related["allocations"] = _limited_find(
                db.paymentallocations,
                {**base_query, "$or": [
                    {"customerPaymentId": {"$in": list(receipt_ids)}},
                    {"orderId": {"$in": list(order_ids)}},
                ]},
            )
            allocation_ids = _id_set(related["allocations"])
            payment_ids = _id_set(records)
            related["ledger_entries"] = _limited_find(
                db.ledgerentries,
                {**base_query, "$or": [
                    {"orderPaymentId": {"$in": list(payment_ids)}},
                    {"allocationId": {"$in": list(allocation_ids)}},
                ]},
            )
            related["orders"] = _limited_find(
                db.orders,
                _scope_order_query(scope, {"_id": {"$in": list(order_ids)}}),
                ORDER_PROJECTION,
            )
            quality["missing_receipt_references"] = _missing_reference_count(
                records, "customerPaymentId", related["customer_payments"]
            )
        elif entity == "expenses":
            records = _limited_find(
                db.laundryexpenses,
                {
                    **base_query,
                    **_range_query("expenseDate", start_date, end_date),
                },
                None,
                "expenseDate",
            )
        elif entity == "profitability":
            records = _limited_find(
                db.orders,
                _scope_order_query(scope, _range_query("createdAt", start_date, end_date)),
                ORDER_PROJECTION,
                "createdAt",
            )
            related["order_payments"], related["customer_payments"] = (
                _payment_documents_for_period(
                    db, base_query, start_date, end_date, scope_customers
                )
            )
            related["monthly_expenses"] = _limited_find(
                db.laundryexpenses,
                {
                    **base_query,
                    **_range_query("expenseDate", start_date, end_date),
                },
            )
        elif entity == "settlements":
            records = _limited_find(
                db.laundrysettlements,
                {**base_query, **_fallback_date_query(["requestedAt", "createdAt"], start_date, end_date)},
                None,
                "createdAt",
            )
            related["wallet_transactions"] = _limited_find(
                db.laundrywallettransactions,
                {**base_query, **_fallback_date_query(["postedAt", "createdAt"], start_date, end_date)},
            )
            related["bank_accounts"] = _limited_find(db.laundrybankaccounts, base_query)
        elif entity == "wallet_transactions":
            records = _limited_find(
                db.laundrywallettransactions,
                {**base_query, **_fallback_date_query(["postedAt", "createdAt"], start_date, end_date)},
                None,
                "createdAt",
            )
            wallet = db.laundrywallets.find_one(base_query)
            related["wallet"] = wallet
            related["settlements"] = _limited_find(
                db.laundrysettlements,
                {**base_query, **_fallback_date_query(["requestedAt", "createdAt"], start_date, end_date)},
            )
        elif entity in {"services", "items"}:
            records = _limited_find(
                db.orders,
                _scope_order_query(scope, _range_query("createdAt", start_date, end_date)),
                ORDER_PROJECTION,
                "createdAt",
            )
            related.update(_catalog_related(db, scope, records))
        elif entity == "financial_reconciliation":
            records, period_receipts = _payment_documents_for_period(
                db, base_query, start_date, end_date, scope_customers
            )
            receipt_ids = _id_set(records, "customerPaymentId")
            order_ids = _id_set(records, "orderId")
            related["customer_payments"] = period_receipts
            related["allocations"] = _limited_find(
                db.paymentallocations,
                {**base_query, "$or": [
                    {"customerPaymentId": {"$in": list(receipt_ids)}},
                    {"orderId": {"$in": list(order_ids)}},
                ]},
            )
            allocation_ids = _id_set(related["allocations"])
            related["ledger_entries"] = _limited_find(
                db.ledgerentries,
                {**base_query, "$or": [
                    {"orderPaymentId": {"$in": list(_id_set(records))}},
                    {"allocationId": {"$in": list(allocation_ids)}},
                ]},
            )
            related["orders"] = _limited_find(
                db.orders, _scope_order_query(scope, {"_id": {"$in": list(order_ids)}}), ORDER_PROJECTION
            )
            quality["missing_receipt_references"] = _missing_reference_count(
                records, "customerPaymentId", related["customer_payments"]
            )
            quality["missing_order_references"] = _missing_reference_count(
                records, "orderId", related["orders"]
            )
        else:
            raise ValueError("Unsupported report entity.")

    return laundry, ReportSource(
        entity=entity,
        records=records,
        related=related,
        data_quality=quality,
    )

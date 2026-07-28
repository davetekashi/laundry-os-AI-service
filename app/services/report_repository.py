from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from bson import ObjectId

from app.services.mongo import get_database, to_object_id


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


def _monthly_expense_query(
    laundry_id: ObjectId,
    start_date: datetime,
    end_date: datetime,
) -> dict:
    months: list[dict[str, int]] = []
    year, month = start_date.year, start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        months.append({"year": year, "monthNumber": month})
        month += 1
        if month == 13:
            year += 1
            month = 1
    return {"laundryId": laundry_id, "$or": months}


def _catalog_related(db, laundry_id: ObjectId, orders: list[dict]) -> dict[str, Any]:
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

    item_prices = _limited_find(
        db.laundryitemprices,
        {"laundryId": laundry_id, "_id": {"$in": list(item_price_ids)}},
        {"itemName": 1, "normalizedItemName": 1, "service": 1, "price": 1, "variants": 1},
    )
    laundry_services = _limited_find(
        db.laundryservices,
        {"laundryId": laundry_id},
        {"service": 1},
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
        db.laundryaddonservices,
        {"laundryId": laundry_id},
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


def fetch_report_source(
    laundry_id: str,
    entity: str,
    start_date: datetime | None,
    end_date: datetime | None,
) -> tuple[dict, ReportSource]:
    db = get_database()
    laundry_object_id = to_object_id(laundry_id)
    laundry = db.laundries.find_one({"_id": laundry_object_id})
    if not laundry:
        raise ValueError("Laundry not found.")

    base_query = {"laundryId": laundry_object_id}
    related: dict[str, Any] = {}
    quality: dict[str, int] = {}

    if entity == "laundry":
        records = [laundry]
        related["workspace_settings"] = db.laundryworkspacesettings.find_one(base_query)
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
                {**base_query, **_range_query("createdAt", start_date, end_date)},
                ORDER_PROJECTION,
                "createdAt",
            )
            order_ids = _id_set(records)
            related["order_payments"] = _limited_find(
                db.orderpayments,
                {**base_query, "orderId": {"$in": list(order_ids)}},
                ORDER_PAYMENT_PROJECTION,
                "createdAt",
            )
            related["payments_in_period"] = _limited_find(
                db.orderpayments,
                {**base_query, **_fallback_date_query(["paidAt", "confirmedAt", "recordedAt", "createdAt"], start_date, end_date)},
                ORDER_PAYMENT_PROJECTION,
                "createdAt",
            )
            related.update(_catalog_related(db, laundry_object_id, records))
        elif entity == "customers":
            records = _limited_find(
                db.laundrycustomers,
                {**base_query, **_range_query("createdAt", start_date, end_date)},
                None,
                "createdAt",
            )
            customer_ids = _id_set(records)
            related["orders"] = _limited_find(
                db.orders,
                {**base_query, "laundryCustomerId": {"$in": list(customer_ids)}},
                ORDER_PROJECTION,
                "createdAt",
            )
            related["debts"] = _limited_find(
                db.laundrydebts,
                {**base_query, "laundryCustomerId": {"$in": list(customer_ids)}},
            )
            related["order_payments"] = _limited_find(
                db.orderpayments,
                {**base_query, "laundryCustomerId": {"$in": list(customer_ids)}},
                ORDER_PAYMENT_PROJECTION,
                "createdAt",
            )
        elif entity == "debts":
            records = _limited_find(
                db.laundrydebts,
                {**base_query, **_range_query("openedAt", start_date, end_date)},
                None,
                "openedAt",
            )
            order_ids = _id_set(records, "orderId")
            related["orders"] = _limited_find(
                db.orders,
                {**base_query, "_id": {"$in": list(order_ids)}},
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
            records = _limited_find(
                db.laundrymembers,
                base_query,
                {"password": 0},
                "createdAt",
            )
            related["orders"] = _limited_find(
                db.orders,
                {**base_query, **_range_query("createdAt", start_date, end_date)},
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
                db.orders, {**base_query, "_id": {"$in": list(order_ids)}}, ORDER_PROJECTION
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
            records = _limited_find(
                db.orderpayments,
                {**base_query, **_fallback_date_query(["paidAt", "confirmedAt", "recordedAt", "createdAt"], start_date, end_date)},
                ORDER_PAYMENT_PROJECTION,
                "createdAt",
            )
            receipt_ids = _id_set(records, "customerPaymentId")
            order_ids = _id_set(records, "orderId")
            related["customer_payments"] = _limited_find(
                db.customerpayments,
                {**base_query, "$or": [
                    {"_id": {"$in": list(receipt_ids)}},
                    _range_query("transactionDate", start_date, end_date),
                ]},
                CUSTOMER_PAYMENT_PROJECTION,
                "transactionDate",
            )
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
                db.orders, {**base_query, "_id": {"$in": list(order_ids)}}, ORDER_PROJECTION
            )
            quality["missing_receipt_references"] = _missing_reference_count(
                records, "customerPaymentId", related["customer_payments"]
            )
        elif entity == "expenses":
            records = _limited_find(
                db.laundrymonthlyexpenses,
                _monthly_expense_query(laundry_object_id, start_date, end_date),
                None,
                "year",
            )
        elif entity == "profitability":
            records = _limited_find(
                db.orders,
                {**base_query, **_range_query("createdAt", start_date, end_date)},
                ORDER_PROJECTION,
                "createdAt",
            )
            related["order_payments"] = _limited_find(
                db.orderpayments,
                {**base_query, **_fallback_date_query(["paidAt", "confirmedAt", "recordedAt", "createdAt"], start_date, end_date)},
                ORDER_PAYMENT_PROJECTION,
                "createdAt",
            )
            related["monthly_expenses"] = _limited_find(
                db.laundrymonthlyexpenses,
                _monthly_expense_query(laundry_object_id, start_date, end_date),
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
                {**base_query, **_range_query("createdAt", start_date, end_date)},
                ORDER_PROJECTION,
                "createdAt",
            )
            related.update(_catalog_related(db, laundry_object_id, records))
        elif entity == "financial_reconciliation":
            records = _limited_find(
                db.orderpayments,
                {**base_query, **_fallback_date_query(["paidAt", "confirmedAt", "recordedAt", "createdAt"], start_date, end_date)},
                ORDER_PAYMENT_PROJECTION,
                "createdAt",
            )
            receipt_ids = _id_set(records, "customerPaymentId")
            order_ids = _id_set(records, "orderId")
            related["customer_payments"] = _limited_find(
                db.customerpayments,
                {**base_query, "$or": [
                    {"_id": {"$in": list(receipt_ids)}},
                    _range_query("transactionDate", start_date, end_date),
                ]},
                CUSTOMER_PAYMENT_PROJECTION,
                "transactionDate",
            )
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
                db.orders, {**base_query, "_id": {"$in": list(order_ids)}}, ORDER_PROJECTION
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

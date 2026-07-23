from functools import lru_cache
from datetime import datetime

from bson import ObjectId
from pymongo import MongoClient

from app.core.config import get_settings


@lru_cache
def get_mongo_client() -> MongoClient:
    settings = get_settings()
    return MongoClient(settings.mongodb_uri)


def get_database():
    settings = get_settings()
    client = get_mongo_client()
    return client.get_default_database()


def to_object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise ValueError("Invalid laundry_id format.") from exc


def fetch_laundry_context_documents(laundry_id: str) -> dict:
    db = get_database()
    laundry_object_id = to_object_id(laundry_id)

    laundry = db.laundries.find_one({"_id": laundry_object_id})
    if not laundry:
        raise ValueError("Laundry not found.")

    context = {
        "laundry": laundry,
        "bank_account": db.laundrybankaccounts.find_one(
            {"laundryId": laundry_object_id},
            sort=[("isDefault", -1), ("createdAt", -1)],
        ),
        "customers": list(db.laundrycustomers.find({"laundryId": laundry_object_id})),
        "debts": list(db.laundrydebts.find({"laundryId": laundry_object_id})),
        "members": list(db.laundrymembers.find({"laundryId": laundry_object_id})),
        "wallet": db.laundrywallets.find_one({"laundryId": laundry_object_id}),
        "payments": list(db.customerpayments.find({"laundryId": laundry_object_id})),
        "orders": list(db.orders.find({"laundryId": laundry_object_id})),
        "logistics_jobs": list(
            db.laundrylogisticsjobs.find({"laundryId": laundry_object_id})
        ),
    }

    return context


def fetch_laundry_report_documents(
    laundry_id: str,
    start_date: datetime,
    end_date: datetime,
) -> dict:
    db = get_database()
    laundry_object_id = to_object_id(laundry_id)

    laundry = db.laundries.find_one({"_id": laundry_object_id})
    if not laundry:
        raise ValueError("Laundry not found.")

    payments_query = {
        "laundryId": laundry_object_id,
        "paidAt": {"$gte": start_date, "$lte": end_date},
    }
    orders_query = {
        "laundryId": laundry_object_id,
        "createdAt": {"$gte": start_date, "$lte": end_date},
    }
    logistics_query = {
        "laundryId": laundry_object_id,
        "createdAt": {"$gte": start_date, "$lte": end_date},
    }

    return {
        "laundry": laundry,
        "bank_account": db.laundrybankaccounts.find_one(
            {"laundryId": laundry_object_id},
            sort=[("isDefault", -1), ("createdAt", -1)],
        ),
        "wallet": db.laundrywallets.find_one({"laundryId": laundry_object_id}),
        "customers": list(db.laundrycustomers.find({"laundryId": laundry_object_id})),
        "members": list(db.laundrymembers.find({"laundryId": laundry_object_id})),
        "payments_in_range": list(db.customerpayments.find(payments_query)),
        "orders_in_range": list(db.orders.find(orders_query)),
        "all_orders": list(db.orders.find({"laundryId": laundry_object_id})),
        "all_debts": list(db.laundrydebts.find({"laundryId": laundry_object_id})),
        "logistics_jobs_in_range": list(
            db.laundrylogisticsjobs.find(logistics_query)
        ),
    }


REPORT_ENTITY_CONFIG = {
    "laundry": ("laundries", "_id", None, True),
    "bank_account": ("laundrybankaccounts", "laundryId", None, True),
    "customers": ("laundrycustomers", "laundryId", "createdAt", False),
    "debts": ("laundrydebts", "laundryId", "openedAt", False),
    "members": ("laundrymembers", "laundryId", "createdAt", False),
    "wallet": ("laundrywallets", "laundryId", None, True),
    "logistics": ("laundrylogisticsjobs", "laundryId", "createdAt", False),
    "payments": ("customerpayments", "laundryId", "transactionDate", False),
    "orders": ("orders", "laundryId", "createdAt", False),
}
MAX_REPORT_RECORDS = 10_000


def fetch_generated_report_documents(
    laundry_id: str,
    entity: str,
    start_date: datetime | None,
    end_date: datetime | None,
) -> tuple[dict, list[dict]]:
    db = get_database()
    laundry_object_id = to_object_id(laundry_id)
    laundry = db.laundries.find_one({"_id": laundry_object_id})
    if not laundry:
        raise ValueError("Laundry not found.")

    config = REPORT_ENTITY_CONFIG.get(entity)
    if config is None:
        raise ValueError("Unsupported report entity.")

    collection_name, laundry_field, date_field, singleton = config
    query: dict = {laundry_field: laundry_object_id}
    if date_field and start_date and end_date:
        query[date_field] = {"$gte": start_date, "$lte": end_date}

    collection = db[collection_name]
    if singleton:
        document = collection.find_one(query, sort=[("updatedAt", -1)])
        documents = [document] if document else []
    else:
        documents = list(
            collection.find(query).sort(date_field, 1).limit(MAX_REPORT_RECORDS + 1)
        )
        if len(documents) > MAX_REPORT_RECORDS:
            raise ValueError(
                "The selected report contains more than 10,000 records. "
                "Please use a smaller date range."
            )

    if entity in {"payments", "logistics"} and documents:
        customer_field = "customerId" if entity == "payments" else "laundryCustomerId"
        customer_ids = {
            document.get(customer_field)
            for document in documents
            if document.get(customer_field)
        }
        customers = db.laundrycustomers.find(
            {"_id": {"$in": list(customer_ids)}, "laundryId": laundry_object_id}
        )
        customer_names = {
            customer["_id"]: " ".join(
                str(part)
                for part in (customer.get("firstName"), customer.get("lastName"))
                if part
            ).strip()
            for customer in customers
        }
        for document in documents:
            document["_customerName"] = customer_names.get(
                document.get(customer_field), "Unknown"
            )

    if entity == "logistics" and documents:
        order_ids = {
            document.get("orderId")
            for document in documents
            if document.get("orderId")
        }
        orders = db.orders.find(
            {"_id": {"$in": list(order_ids)}, "laundryId": laundry_object_id}
        )
        order_codes = {
            order["_id"]: order.get("orderCode") or order.get("orderNumber") or ""
            for order in orders
        }
        for document in documents:
            document["_orderCode"] = order_codes.get(document.get("orderId"), "")

    return laundry, documents

from functools import lru_cache
from datetime import datetime

from bson import ObjectId
from pymongo import MongoClient

from app.core.config import get_settings
from app.schemas.context import ContextRole


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


STAFF_LAUNDRY_PROJECTION = {
    "laundryName": 1,
    "laundryCode": 1,
    "slug": 1,
    "state": 1,
    "country": 1,
    "status": 1,
    "isActive": 1,
    "isPaused": 1,
}

STAFF_CUSTOMER_PROJECTION = {
    "firstName": 1,
    "lastName": 1,
    "phoneNumber": 1,
    "email": 1,
    "isActive": 1,
    "lastOrderAt": 1,
    "createdAt": 1,
}

STAFF_MEMBER_PROJECTION = {
    "firstName": 1,
    "lastName": 1,
    "username": 1,
    "role": 1,
    "status": 1,
    "isActive": 1,
    "lastLoginAt": 1,
    "createdAt": 1,
}

STAFF_ORDER_PROJECTION = {
    "orderCode": 1,
    "orderNumber": 1,
    "laundryCustomerId": 1,
    "customerSnapshot": 1,
    "createdByStaffId": 1,
    "items.itemNameSnapshot": 1,
    "items.serviceNameSnapshot": 1,
    "items.itemType": 1,
    "items.service": 1,
    "items.quantity": 1,
    "itemCount": 1,
    "orderStatus": 1,
    "paymentStatus": 1,
    "fulfillmentInfo": 1,
    "pickupCompleted": 1,
    "returnCompleted": 1,
    "createdAt": 1,
    "confirmedAt": 1,
    "completedAt": 1,
}

STAFF_LOGISTICS_PROJECTION = {
    "orderId": 1,
    "laundryCustomerId": 1,
    "jobType": 1,
    "type": 1,
    "status": 1,
    "pickupAddress": 1,
    "deliveryAddress": 1,
    "assignedDriverId": 1,
    "scheduledAt": 1,
    "pickedUpAt": 1,
    "deliveredAt": 1,
    "createdAt": 1,
    "updatedAt": 1,
}

STAFF_DISPATCH_PROJECTION = {
    "orderId": 1,
    "driverId": 1,
    "status": 1,
    "dispatchType": 1,
    "scheduledAt": 1,
    "assignedAt": 1,
    "completedAt": 1,
    "createdAt": 1,
}


def _context_catalog_documents(db, laundry_object_id: ObjectId, orders: list[dict]) -> dict:
    item_prices = list(
        db.laundryitemprices.find(
            {"laundryId": laundry_object_id},
            {
                "itemName": 1,
                "normalizedItemName": 1,
                "itemType": 1,
                "service": 1,
                "price": 1,
                "variants": 1,
                "isActive": 1,
            },
        )
    )
    laundry_services = list(
        db.laundryservices.find(
            {"laundryId": laundry_object_id},
            {"service": 1, "isActive": 1},
        )
    )
    add_on_services = list(
        db.laundryaddonservices.find(
            {"laundryId": laundry_object_id},
            {"name": 1, "defaultPrice": 1, "isActive": 1},
        )
    )

    service_ids: set[ObjectId] = set()
    item_type_ids: set[ObjectId] = set()
    for document in item_prices + laundry_services:
        if isinstance(document.get("service"), ObjectId):
            service_ids.add(document["service"])
        if isinstance(document.get("itemType"), ObjectId):
            item_type_ids.add(document["itemType"])
    for order in orders:
        for item in order.get("items") or []:
            if isinstance(item.get("service"), ObjectId):
                service_ids.add(item["service"])
            if isinstance(item.get("itemType"), ObjectId):
                item_type_ids.add(item["itemType"])

    global_services = list(
        db.globallaundryservices.find(
            {"_id": {"$in": list(service_ids)}},
            {"name": 1, "slug": 1},
        )
    )
    global_item_types = list(
        db.globallaundryitemtypes.find(
            {"_id": {"$in": list(item_type_ids)}},
            {"name": 1, "itemCategory": 1},
        )
    )
    category_ids = {
        document["itemCategory"]
        for document in global_item_types
        if isinstance(document.get("itemCategory"), ObjectId)
    }
    global_categories = list(
        db.globalitemcategories.find(
            {"_id": {"$in": list(category_ids)}},
            {"name": 1, "slug": 1},
        )
    )
    return {
        "item_prices": item_prices,
        "laundry_services": laundry_services,
        "add_on_services": add_on_services,
        "global_services": global_services,
        "global_item_types": global_item_types,
        "global_item_categories": global_categories,
    }


def fetch_laundry_context_documents(laundry_id: str, role: ContextRole) -> dict:
    db = get_database()
    laundry_object_id = to_object_id(laundry_id)

    laundry_projection = None if role == ContextRole.OWNER else STAFF_LAUNDRY_PROJECTION
    laundry = db.laundries.find_one(
        {"_id": laundry_object_id},
        laundry_projection,
    )
    if not laundry:
        raise ValueError("Laundry not found.")

    base_query = {"laundryId": laundry_object_id}
    customer_projection = None if role == ContextRole.OWNER else STAFF_CUSTOMER_PROJECTION
    order_projection = None if role == ContextRole.OWNER else STAFF_ORDER_PROJECTION
    logistics_projection = None if role == ContextRole.OWNER else STAFF_LOGISTICS_PROJECTION
    orders = list(db.orders.find(base_query, order_projection))
    context = {
        "laundry": laundry,
        "workspace_settings": db.laundryworkspacesettings.find_one(
            base_query,
            {"operations": 1, "notifications": 1},
        ),
        "customers": list(db.laundrycustomers.find(base_query, customer_projection)),
        "members": list(db.laundrymembers.find(base_query, STAFF_MEMBER_PROJECTION)),
        "orders": orders,
        "logistics_jobs": list(
            db.laundrylogisticsjobs.find(base_query, logistics_projection)
        ),
        "dispatches": list(
            db.laundrydispatches.find(
                base_query,
                None if role == ContextRole.OWNER else STAFF_DISPATCH_PROJECTION,
            )
        ),
        "drivers": list(
            db.laundrydrivers.find(
                base_query,
                {"firstName": 1, "lastName": 1, "status": 1, "isActive": 1},
            )
        ),
    }
    context.update(_context_catalog_documents(db, laundry_object_id, orders))

    if role == ContextRole.OWNER:
        context.update(
            {
                "bank_account": db.laundrybankaccounts.find_one(
                    base_query,
                    {
                        "bankName": 1,
                        "bankCode": 1,
                        "accountName": 1,
                        "accountNumber": 1,
                        "isDefault": 1,
                        "status": 1,
                        "verifiedAt": 1,
                    },
                    sort=[("isDefault", -1), ("createdAt", -1)],
                ),
                "wallet": db.laundrywallets.find_one(base_query),
                "wallet_transactions": list(db.laundrywallettransactions.find(base_query)),
                "debts": list(db.laundrydebts.find(base_query)),
                "order_payments": list(db.orderpayments.find(base_query)),
                "customer_payments": list(db.customerpayments.find(base_query)),
                "payment_allocations": list(db.paymentallocations.find(base_query)),
                "ledger_entries": list(db.ledgerentries.find(base_query)),
                "settlements": list(db.laundrysettlements.find(base_query)),
                "monthly_expenses": list(db.laundrymonthlyexpenses.find(base_query)),
                "subscription_intents": list(db.laundrysubscriptionintents.find(base_query)),
            }
        )

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

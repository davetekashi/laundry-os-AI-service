from functools import lru_cache

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
        "logistics_jobs": list(db.logisticsjobs.find({"laundryId": laundry_object_id})),
    }

    return context

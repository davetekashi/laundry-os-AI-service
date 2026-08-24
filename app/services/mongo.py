from functools import lru_cache
from datetime import datetime

from bson import ObjectId
from pymongo import MongoClient

from app.core.config import get_settings
from app.schemas.context import ContextRole
from app.services.scope import (
    ResolvedScope,
    resolve_scope,
    scope_legacy_query,
    scope_order_query,
)


@lru_cache
def get_mongo_client() -> MongoClient:
    settings = get_settings()
    return MongoClient(settings.mongodb_uri)


def get_database():
    settings = get_settings()
    client = get_mongo_client()
    return client.get_default_database()


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


def _dedupe_documents(documents: list[dict]) -> list[dict]:
    seen: set[ObjectId] = set()
    result: list[dict] = []
    for document in documents:
        document_id = document.get("_id")
        if isinstance(document_id, ObjectId) and document_id in seen:
            continue
        if isinstance(document_id, ObjectId):
            seen.add(document_id)
        result.append(document)
    return result


def _aggregate_wallets(wallets: list[dict]) -> dict | None:
    if not wallets:
        return None
    currencies = {
        str(wallet.get("currency"))
        for wallet in wallets
        if wallet.get("currency")
    }
    dated_wallets = [
        wallet
        for wallet in wallets
        if isinstance(wallet.get("updatedAt"), datetime)
    ]
    latest = max(dated_wallets, key=lambda row: row["updatedAt"], default={})
    return {
        "currency": next(iter(currencies)) if len(currencies) == 1 else "multiple",
        "availableBalance": sum(
            float(wallet.get("availableBalance", 0) or 0) for wallet in wallets
        ),
        "pendingBalance": sum(
            float(wallet.get("pendingBalance", 0) or 0) for wallet in wallets
        ),
        "isFrozen": any(wallet.get("isFrozen") for wallet in wallets),
        "lastTransactionAt": max(
            (
                wallet["lastTransactionAt"]
                for wallet in wallets
                if isinstance(wallet.get("lastTransactionAt"), datetime)
            ),
            default=None,
        ),
        "updatedAt": latest.get("updatedAt"),
        "walletCount": len(wallets),
    }


def orders_to_debts(orders: list[dict]) -> list[dict]:
    debts: list[dict] = []
    for order in orders:
        balance_due = float(order.get("totalBalanceDue", 0) or 0)
        if balance_due <= 0:
            continue
        debts.append(
            {
                "_id": order.get("_id"),
                "orderId": order.get("_id"),
                "laundryId": order.get("laundryId"),
                "laundryCustomerId": order.get("laundryCustomerId"),
                "customerSnapshot": order.get("customerSnapshot") or {},
                "orderCode": order.get("orderCode"),
                "orderNumber": order.get("orderNumber"),
                "totalAmount": order.get("totalPayable", 0),
                "amountPaid": order.get("totalAmountPaid", 0),
                "balanceDue": balance_due,
                "status": "outstanding",
                "openedAt": order.get("confirmedAt") or order.get("createdAt"),
                "settledAt": None,
            }
        )
    return debts


def _context_catalog_documents(db, scope: ResolvedScope, orders: list[dict]) -> dict:
    if scope.business_id:
        item_prices = list(
            db.businessitemprices.find(
                {"businessId": scope.business_id},
                {
                    "itemName": 1,
                    "normalizedItemName": 1,
                    "serviceKey": 1,
                    "price": 1,
                    "variants": 1,
                    "isActive": 1,
                },
            )
        )
        laundry_services = list(
            db.businessservices.find(
                {"businessId": scope.business_id},
                {
                    "name": 1,
                    "slug": 1,
                    "serviceKey": 1,
                    "categoryKey": 1,
                    "isActive": 1,
                },
            )
        )
        add_on_services = list(
            db.businessaddonservices.find(
                {"businessId": scope.business_id},
                {"name": 1, "defaultPrice": 1, "isActive": 1},
            )
        )
    else:
        item_prices = list(
            db.laundryitemprices.find(
                {"laundryId": scope.laundry_id},
                {
                    "itemName": 1,
                    "normalizedItemName": 1,
                    "itemType": 1,
                    "service": 1,
                    "serviceKey": 1,
                    "price": 1,
                    "variants": 1,
                    "isActive": 1,
                },
            )
        )
        laundry_services = list(
            db.laundryservices.find(
                {"laundryId": scope.laundry_id},
                {
                    "service": 1,
                    "name": 1,
                    "slug": 1,
                    "serviceKey": 1,
                    "categoryKey": 1,
                    "isActive": 1,
                },
            )
        )
        add_on_services = list(
            db.laundryaddonservices.find(
                {"laundryId": scope.laundry_id},
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


def fetch_scope_customers(
    db,
    scope: ResolvedScope,
    projection: dict | None = None,
) -> list[dict]:
    legacy_customers = _dedupe_documents(
        list(db.laundrycustomers.find(scope_legacy_query(scope), projection))
    )
    if not scope.business_id:
        return legacy_customers

    legacy_ids = {
        customer.get("_id")
        for customer in legacy_customers
        if isinstance(customer.get("_id"), ObjectId)
    }
    legacy_by_id = {
        customer.get("_id"): customer
        for customer in legacy_customers
        if isinstance(customer.get("_id"), ObjectId)
    }
    profile_query = {"businessId": scope.business_id}
    if scope.branch_id:
        profile_query["branchId"] = scope.branch_id
    profiles = list(
        db.branchcustomerprofiles.find(
            profile_query,
            {
                "businessCustomerId": 1,
                "legacyLaundryCustomerId": 1,
                "creditEnabled": 1,
                "lastOrderAt": 1,
                "status": 1,
                "notes": 1,
            },
        )
    )
    profiles_by_customer = {
        profile.get("businessCustomerId"): profile for profile in profiles
    }
    migrated_customer_query: dict = {"businessId": scope.business_id}
    if scope.branch_id:
        migrated_customer_query["_id"] = {
            "$in": [
                profile.get("businessCustomerId")
                for profile in profiles
                if isinstance(profile.get("businessCustomerId"), ObjectId)
            ]
        }
    migrated_customers = list(
        db.businesscustomers.find(
            migrated_customer_query,
            {
                "firstName": 1,
                "lastName": 1,
                "email": 1,
                "phoneNumbers": 1,
                "status": 1,
                "createdAt": 1,
                "legacyLaundryCustomerId": 1,
                "userId": 1,
            },
        )
    )
    for customer in migrated_customers:
        legacy_id = customer.get("legacyLaundryCustomerId")
        profile = profiles_by_customer.get(customer.get("_id"), {})
        phone_numbers = customer.get("phoneNumbers") or []
        primary_phone = phone_numbers[0] if phone_numbers else None
        if isinstance(primary_phone, dict):
            primary_phone = primary_phone.get("number") or primary_phone.get("phoneNumber")
        if legacy_id in legacy_ids:
            legacy_customer = legacy_by_id[legacy_id]
            legacy_customer["businessCustomerId"] = customer.get("_id")
            legacy_customer["userId"] = customer.get("userId")
            legacy_customer["legacyLaundryCustomerId"] = legacy_id
            if profile.get("lastOrderAt"):
                legacy_customer["lastOrderAt"] = profile["lastOrderAt"]
            if "creditEnabled" in profile:
                legacy_customer["creditEnabled"] = profile["creditEnabled"]
            continue
        legacy_customers.append(
            {
                "_id": legacy_id or customer.get("_id"),
                "businessCustomerId": customer.get("_id"),
                "userId": customer.get("userId"),
                "legacyLaundryCustomerId": legacy_id,
                "firstName": customer.get("firstName"),
                "lastName": customer.get("lastName"),
                "email": customer.get("email"),
                "phoneNumber": primary_phone,
                "isActive": str(profile.get("status") or customer.get("status") or "").lower()
                == "active",
                "creditEnabled": profile.get("creditEnabled", False),
                "lastOrderAt": profile.get("lastOrderAt"),
                "createdAt": customer.get("createdAt"),
                "notes": profile.get("notes"),
            }
        )
    return legacy_customers


def fetch_scope_members(db, scope: ResolvedScope) -> list[dict]:
    members = _dedupe_documents(
        list(
            db.laundrymembers.find(
                scope_legacy_query(scope),
                STAFF_MEMBER_PROJECTION,
            )
        )
    )
    if not scope.business_id:
        return members

    legacy_member_ids = {
        member.get("_id") for member in members if isinstance(member.get("_id"), ObjectId)
    }
    legacy_members_by_id = {
        member.get("_id"): member
        for member in members
        if isinstance(member.get("_id"), ObjectId)
    }
    memberships = list(
        db.businessmemberships.find(
            {"businessId": scope.business_id},
            {
                "userId": 1,
                "legacyMemberId": 1,
                "username": 1,
                "role": 1,
                "status": 1,
                "createdAt": 1,
            },
        )
    )
    assignment_query = {"businessId": scope.business_id}
    if scope.branch_id:
        assignment_query["branchId"] = scope.branch_id
    assignments = list(
        db.branchassignments.find(
            assignment_query,
            {
                "userId": 1,
                "legacyLaundryMemberId": 1,
                "username": 1,
                "role": 1,
                "status": 1,
                "createdAt": 1,
            },
        )
    )
    user_ids = {
        document.get("userId")
        for document in memberships + assignments
        if isinstance(document.get("userId"), ObjectId)
    }
    account_users = {
        user.get("_id"): user
        for user in db.accountusers.find(
            {"_id": {"$in": list(user_ids)}},
            {"firstName": 1, "lastName": 1, "email": 1, "lastLoginAt": 1},
        )
    }
    seen_users: set[ObjectId] = set()
    for document in memberships + assignments:
        legacy_id = document.get("legacyMemberId") or document.get("legacyLaundryMemberId")
        user_id = document.get("userId")
        if legacy_id in legacy_member_ids:
            legacy_member = legacy_members_by_id[legacy_id]
            legacy_member["userId"] = user_id
            user = account_users.get(user_id, {})
            for field_name in ("firstName", "lastName", "email", "lastLoginAt"):
                if not legacy_member.get(field_name) and user.get(field_name):
                    legacy_member[field_name] = user[field_name]
            if isinstance(user_id, ObjectId):
                seen_users.add(user_id)
            continue
        if user_id in seen_users:
            continue
        if isinstance(user_id, ObjectId):
            seen_users.add(user_id)
        user = account_users.get(user_id, {})
        members.append(
            {
                "_id": legacy_id or document.get("_id"),
                "firstName": user.get("firstName"),
                "lastName": user.get("lastName"),
                "email": user.get("email"),
                "username": document.get("username"),
                "role": document.get("role"),
                "status": document.get("status"),
                "isActive": str(document.get("status") or "").lower() == "active",
                "lastLoginAt": user.get("lastLoginAt"),
                "createdAt": document.get("createdAt"),
            }
        )
    return members


def _enrich_order_payments(
    db,
    payments: list[dict],
    customers: list[dict],
) -> list[dict]:
    receipt_ids = {
        payment.get("customerPaymentId")
        for payment in payments
        if isinstance(payment.get("customerPaymentId"), ObjectId)
    }
    receipts = {
        receipt.get("_id"): receipt
        for receipt in db.customerpayments.find({"_id": {"$in": list(receipt_ids)}})
    }
    customer_names = {
        customer.get("_id"): " ".join(
            str(part)
            for part in (customer.get("firstName"), customer.get("lastName"))
            if part
        ).strip()
        for customer in customers
    }
    enriched: list[dict] = []
    for payment in payments:
        row = dict(payment)
        receipt = receipts.get(payment.get("customerPaymentId"), {})
        if not row.get("method"):
            row["method"] = receipt.get("method")
        if not row.get("paidAt"):
            row["paidAt"] = receipt.get("transactionDate")
        if not row.get("transactionType"):
            row["transactionType"] = receipt.get("transactionType")
        customer_name = customer_names.get(payment.get("laundryCustomerId"))
        if customer_name and not row.get("payerSnapshot"):
            row["payerSnapshot"] = {"fullName": customer_name}
        enriched.append(row)
    return enriched


def fetch_laundry_context_documents(
    laundry_id: str | None,
    role: ContextRole,
    business_id: str | None = None,
) -> dict:
    db = get_database()
    scope = resolve_scope(db, laundry_id, business_id)
    laundry_object_id = scope.laundry_id

    laundry_projection = None if role.has_financial_access else STAFF_LAUNDRY_PROJECTION
    laundry = (
        scope.laundry
        if laundry_projection is None
        else db.laundries.find_one({"_id": laundry_object_id}, laundry_projection)
    )

    base_query = scope_legacy_query(scope)
    customer_projection = None if role.has_financial_access else STAFF_CUSTOMER_PROJECTION
    order_projection = None if role.has_financial_access else STAFF_ORDER_PROJECTION
    logistics_projection = None if role.has_financial_access else STAFF_LOGISTICS_PROJECTION
    orders = list(db.orders.find(scope_order_query(scope), order_projection))
    customers = fetch_scope_customers(db, scope, customer_projection)
    laundries = list(
        db.laundries.find(
            {"_id": {"$in": list(scope.legacy_laundry_ids)}}
            if scope.is_business_wide
            else {"_id": laundry_object_id},
            laundry_projection,
        )
    )
    context = {
        "_scope": scope,
        "laundry": laundry,
        "laundries": laundries or [laundry],
        "business": scope.business,
        "business_branches": list(scope.branches),
        "workspace_settings": db.laundryworkspacesettings.find_one(
            base_query,
            {"operations": 1, "notifications": 1},
        ),
        "business_settings": (
            db.businesssettings.find_one({"businessId": scope.business_id})
            if scope.business_id
            else None
        ),
        "branch_settings": (
            list(
                db.branchsettings.find(
                    {"branchId": scope.branch_id}
                    if scope.branch_id
                    else {"businessId": scope.business_id}
                )
            )
            if scope.business_id
            else []
        ),
        "customers": customers,
        "members": fetch_scope_members(db, scope),
        "orders": orders,
        "logistics_jobs": list(
            db.laundrylogisticsjobs.find(base_query, logistics_projection)
        ),
        "dispatches": list(
            db.laundrydispatches.find(
                base_query,
                None if role.has_financial_access else STAFF_DISPATCH_PROJECTION,
            )
        ),
        "drivers": list(
            db.laundrydrivers.find(
                base_query,
                {"firstName": 1, "lastName": 1, "status": 1, "isActive": 1},
            )
        ),
    }
    context.update(_context_catalog_documents(db, scope, orders))

    if role.has_financial_access:
        payments = list(db.orderpayments.find(base_query))
        bank_accounts = list(
            db.laundrybankaccounts.find(
                base_query,
                {
                    "laundryId": 1,
                    "bankName": 1,
                    "bankCode": 1,
                    "accountName": 1,
                    "accountNumber": 1,
                    "isDefault": 1,
                    "status": 1,
                    "verifiedAt": 1,
                    "createdAt": 1,
                },
            )
        )
        wallets = list(db.laundrywallets.find(base_query))
        context.update(
            {
                "bank_account": next(
                    (
                        account
                        for account in bank_accounts
                        if account.get("isDefault")
                    ),
                    bank_accounts[0] if bank_accounts else None,
                ),
                "bank_accounts": bank_accounts,
                "wallet": _aggregate_wallets(wallets),
                "wallets": wallets,
                "wallet_transactions": list(db.laundrywallettransactions.find(base_query)),
                "debts": orders_to_debts(orders),
                "order_payments": _enrich_order_payments(db, payments, customers),
                "customer_payments": list(db.customerpayments.find(base_query)),
                "payment_allocations": list(db.paymentallocations.find(base_query)),
                "ledger_entries": list(db.ledgerentries.find(base_query)),
                "settlements": list(db.laundrysettlements.find(base_query)),
                "monthly_expenses": list(db.laundryexpenses.find(base_query)),
                "subscription_intents": list(db.laundrysubscriptionintents.find(base_query)),
            }
        )

    return context


def fetch_laundry_report_documents(
    laundry_id: str | None,
    start_date: datetime,
    end_date: datetime,
    business_id: str | None = None,
) -> dict:
    db = get_database()
    scope = resolve_scope(db, laundry_id, business_id)
    laundry_object_id = scope.laundry_id
    laundry = scope.laundry

    payments_query = {
        "laundryId": laundry_object_id,
        "transactionDate": {"$gte": start_date, "$lte": end_date},
    }
    orders_query = {
        "$and": [
            scope_order_query(scope),
            {"createdAt": {"$gte": start_date, "$lte": end_date}},
        ]
    }
    logistics_query = {
        "laundryId": laundry_object_id,
        "createdAt": {"$gte": start_date, "$lte": end_date},
    }

    all_orders = list(db.orders.find(scope_order_query(scope)))
    return {
        "_scope": scope,
        "laundry": laundry,
        "bank_account": db.laundrybankaccounts.find_one(
            {"laundryId": laundry_object_id},
            sort=[("isDefault", -1), ("createdAt", -1)],
        ),
        "wallet": db.laundrywallets.find_one({"laundryId": laundry_object_id}),
        "customers": fetch_scope_customers(db, scope),
        "members": fetch_scope_members(db, scope),
        "payments_in_range": list(db.customerpayments.find(payments_query)),
        "orders_in_range": list(db.orders.find(orders_query)),
        "all_orders": all_orders,
        "all_debts": orders_to_debts(all_orders),
        "logistics_jobs_in_range": list(
            db.laundrylogisticsjobs.find(logistics_query)
        ),
    }

from datetime import date, datetime, time

from app.core.config import get_settings
from app.schemas.order_import import (
    ExtractedHistoricalOrder,
    HistoricalCustomerSnapshot,
    HistoricalOrderData,
    HistoricalOrderItem,
    HistoricalOrderStatus,
    HistoricalPaymentStatus,
    OrderSourceReference,
    ReviewRequiredOrder,
)
from app.services.order_consolidator import SourcedOrderDraft


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned or None


def _date_value(value: str | None, field: str, issues: list[str]) -> datetime | None:
    cleaned = _text(value)
    if not cleaned:
        return None
    try:
        if len(cleaned) == 10:
            return datetime.combine(date.fromisoformat(cleaned), time.min)
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        issues.append(f"{field} could not be converted to an ISO 8601 date.")
        return None


def _money(value: int | None, field: str, issues: list[str]) -> int | None:
    if value is None:
        return None
    if value < 0:
        issues.append(f"{field} cannot be negative.")
        return None
    return value


def _currency(value: str | None, issues: list[str]) -> str:
    default = get_settings().default_currency.upper()
    cleaned = (_text(value) or default).upper()
    if len(cleaned) != 3 or not cleaned.isalpha():
        issues.append(f"Currency '{cleaned}' is not a valid three-letter currency code.")
        return default
    return cleaned


def _derive_payment_status(
    total: int | None,
    paid: int | None,
    balance: int | None,
) -> HistoricalPaymentStatus | None:
    if total is None:
        return None
    if balance == 0 and (paid is None or paid == total):
        return HistoricalPaymentStatus.PAID
    if balance is not None and balance > 0:
        if paid is not None and paid > 0:
            return HistoricalPaymentStatus.PARTIAL
        if paid == 0 or balance == total:
            return HistoricalPaymentStatus.UNPAID
    return None


def validate_order_draft(
    sourced: SourcedOrderDraft,
) -> tuple[HistoricalOrderData, list[str]]:
    draft = sourced.draft
    issues = list(draft.extraction_issues)
    currency = _currency(draft.currency, issues)
    items: list[HistoricalOrderItem] = []

    for index, item in enumerate(draft.items, start=1):
        name = _text(item.item_name_snapshot)
        if not name:
            issues.append(f"Item {index} has no readable item name.")
            continue
        piece_count = item.piece_count
        if piece_count is not None and piece_count < 1:
            issues.append(f"Item {index} has an invalid piece count.")
            piece_count = None
        unit_price = _money(item.unit_price, f"Item {index} unitPrice", issues)
        subtotal = _money(item.subtotal, f"Item {index} subtotal", issues)
        if subtotal is None and unit_price is not None and piece_count is not None:
            subtotal = unit_price * piece_count
        elif (
            subtotal is not None
            and unit_price is not None
            and piece_count is not None
            and subtotal != unit_price * piece_count
        ):
            issues.append(
                f"Item {index} subtotal does not equal unitPrice multiplied by pieceCount."
            )
        items.append(
            HistoricalOrderItem(
                item_name_snapshot=name,
                service_name_snapshot=_text(item.service_name_snapshot),
                piece_count=piece_count,
                color=_text(item.color),
                description=_text(item.description),
                unit_price=unit_price,
                subtotal=subtotal,
                currency=_currency(item.currency or currency, issues),
            )
        )

    item_count = draft.item_count if draft.item_count is not None else len(items)
    if item_count < 0:
        issues.append("itemCount cannot be negative.")
        item_count = len(items)

    total_piece_count = draft.total_piece_count
    if total_piece_count is None and items and all(item.piece_count is not None for item in items):
        total_piece_count = sum(item.piece_count or 0 for item in items)
    elif total_piece_count is not None and total_piece_count < 0:
        issues.append("totalPieceCount cannot be negative.")
        total_piece_count = None

    item_subtotals_complete = bool(items) and all(item.subtotal is not None for item in items)
    calculated_items_subtotal = (
        sum(item.subtotal or 0 for item in items) if item_subtotals_complete else None
    )
    items_subtotal = _money(draft.items_subtotal, "itemsSubtotal", issues)
    if items_subtotal is None:
        items_subtotal = calculated_items_subtotal
    elif calculated_items_subtotal is not None and items_subtotal != calculated_items_subtotal:
        issues.append("itemsSubtotal does not equal the sum of the extracted item subtotals.")

    discount_total = _money(draft.discount_total, "discountTotal", issues)
    service_total = _money(draft.service_total, "serviceTotal", issues)
    logistics_total = _money(draft.logistics_total, "logisticsTotal", issues)
    tax_total = _money(draft.tax_total, "taxTotal", issues)
    express_surcharge = _money(draft.express_surcharge, "expressSurcharge", issues)
    total_payable = _money(draft.total_payable, "totalPayable", issues)
    total_amount_paid = _money(draft.total_amount_paid, "totalAmountPaid", issues)
    total_balance_due = _money(draft.total_balance_due, "totalBalanceDue", issues)

    if total_amount_paid is None and total_payable is not None and total_balance_due is not None:
        if total_balance_due <= total_payable:
            total_amount_paid = total_payable - total_balance_due
        else:
            issues.append("totalBalanceDue is greater than totalPayable.")

    if (
        total_payable is not None
        and total_amount_paid is not None
        and total_balance_due is not None
        and total_amount_paid + total_balance_due != total_payable
    ):
        issues.append("totalAmountPaid plus totalBalanceDue does not equal totalPayable.")

    expected_total_base = items_subtotal if items_subtotal is not None else service_total
    if expected_total_base is not None and total_payable is not None:
        expected_total = (
            expected_total_base
            + (logistics_total or 0)
            + (tax_total or 0)
            + (express_surcharge or 0)
            - (discount_total or 0)
        )
        if expected_total != total_payable:
            issues.append(
                "totalPayable does not reconcile with the extracted subtotal, additions, and discount."
            )

    derived_payment_status = _derive_payment_status(
        total_payable,
        total_amount_paid,
        total_balance_due,
    )
    payment_status = (
        HistoricalPaymentStatus(draft.payment_status)
        if draft.payment_status
        else derived_payment_status
    )
    if (
        payment_status is not None
        and derived_payment_status is not None
        and payment_status != derived_payment_status
    ):
        issues.append("paymentStatus conflicts with the extracted payment totals and balance.")

    order_status = (
        HistoricalOrderStatus(draft.order_status) if draft.order_status else None
    )
    customer_values = {
        "full_name": _text(draft.customer_full_name),
        "phone_number": _text(draft.customer_phone_number),
        "email": _text(draft.customer_email),
    }
    customer_snapshot = (
        HistoricalCustomerSnapshot(**customer_values)
        if any(customer_values.values())
        else None
    )
    source_reference = OrderSourceReference(
        file_url=sourced.file_url,
        page=draft.source_page or sourced.page,
        sheet=_text(draft.source_sheet) or sourced.sheet,
        row_numbers=sorted(
            set(draft.source_row_numbers or sourced.row_numbers or [])
        ),
    )
    data = HistoricalOrderData(
        tag_code=_text(draft.tag_code),
        customer_snapshot=customer_snapshot,
        source_staff_name=_text(draft.source_staff_name),
        created_at=_date_value(draft.created_at, "createdAt", issues),
        estimated_completion_time=_date_value(
            draft.estimated_completion_time,
            "estimatedCompletionTime",
            issues,
        ),
        order_note=_text(draft.order_note),
        items=items,
        item_count=item_count,
        total_piece_count=total_piece_count,
        items_subtotal=items_subtotal,
        discount_total=discount_total,
        service_total=service_total,
        logistics_total=logistics_total,
        tax_total=tax_total,
        express_surcharge=express_surcharge,
        total_payable=total_payable,
        total_amount_paid=total_amount_paid,
        total_balance_due=total_balance_due,
        payment_status=payment_status,
        order_status=order_status,
        currency=currency,
        source_reference=source_reference,
    )
    if not items:
        issues.append("No readable order items were extracted.")
    return data, list(dict.fromkeys(issue for issue in issues if issue.strip()))


def classify_order_drafts(
    drafts: list[SourcedOrderDraft],
) -> tuple[list[ExtractedHistoricalOrder], list[ReviewRequiredOrder]]:
    orders: list[ExtractedHistoricalOrder] = []
    review_required: list[ReviewRequiredOrder] = []
    for sourced in drafts:
        data, issues = validate_order_draft(sourced)
        if issues:
            review_required.append(
                ReviewRequiredOrder(extracted_data=data, issues=issues)
            )
            continue
        orders.append(ExtractedHistoricalOrder.model_validate(data.model_dump()))
    return orders, review_required

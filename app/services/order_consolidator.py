from dataclasses import dataclass

from app.schemas.order_import import OrderExtractionDraft


@dataclass
class SourcedOrderDraft:
    draft: OrderExtractionDraft
    file_url: str
    page: int | None = None
    sheet: str | None = None
    row_numbers: list[int] | None = None


_SOURCE_FIELDS = {
    "source_page",
    "source_sheet",
    "source_row_numbers",
    "extraction_issues",
}


def _tag_key(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(value.split()).casefold()
    return cleaned or None


def _semantic_payload(draft: OrderExtractionDraft) -> dict:
    return draft.model_dump(exclude=_SOURCE_FIELDS)


def _identity_conflicts(group: list[SourcedOrderDraft]) -> bool:
    identity_fields = ("customer_full_name", "created_at")
    for field in identity_fields:
        values = {
            " ".join(value.split()).casefold()
            for sourced in group
            if (value := getattr(sourced.draft, field))
        }
        if len(values) > 1:
            return True
    return False


def _mark_tag_collision(group: list[SourcedOrderDraft]) -> list[SourcedOrderDraft]:
    marked: list[SourcedOrderDraft] = []
    tag_code = group[0].draft.tag_code
    for sourced in group:
        issues = list(sourced.draft.extraction_issues)
        issues.append(
            f"Tag code {tag_code} appears on records with different customer or date identities; verify each order before import."
        )
        sourced.draft = sourced.draft.model_copy(
            update={"extraction_issues": list(dict.fromkeys(issues))}
        )
        marked.append(sourced)
    return marked


def _merge_group(group: list[SourcedOrderDraft]) -> SourcedOrderDraft:
    first = group[0]
    if len(group) == 1:
        return first
    if all(_semantic_payload(item.draft) == _semantic_payload(first.draft) for item in group[1:]):
        issues = list(first.draft.extraction_issues)
        issues.append(
            "The same extracted order appears in more than one source segment; verify that it should be imported once."
        )
        first.draft = first.draft.model_copy(update={"extraction_issues": issues})
        return first

    merged = first.draft.model_copy(deep=True)
    issues = list(merged.extraction_issues)
    issues.append(
        "The order was assembled from multiple source segments sharing the same tag code; verify the merged items and totals."
    )
    merged_rows = set(merged.source_row_numbers)
    merged_rows.update(first.row_numbers or [])

    scalar_fields = [
        field
        for field in OrderExtractionDraft.model_fields
        if field not in _SOURCE_FIELDS and field != "items"
    ]
    for sourced in group[1:]:
        other = sourced.draft
        issues.extend(other.extraction_issues)
        merged_rows.update(other.source_row_numbers)
        merged_rows.update(sourced.row_numbers or [])
        for field in scalar_fields:
            current_value = getattr(merged, field)
            other_value = getattr(other, field)
            if current_value is None and other_value is not None:
                setattr(merged, field, other_value)
            elif (
                current_value is not None
                and other_value is not None
                and current_value != other_value
            ):
                issues.append(
                    f"Conflicting {field} values were found for tag code {merged.tag_code}."
                )
        merged.items.extend(other.items)

    pages = {
        value
        for sourced in group
        for value in (sourced.draft.source_page, sourced.page)
        if value is not None
    }
    sheets = {
        value
        for sourced in group
        for value in (sourced.draft.source_sheet, sourced.sheet)
        if value
    }
    merged.source_page = next(iter(pages)) if len(pages) == 1 else None
    merged.source_sheet = next(iter(sheets)) if len(sheets) == 1 else None
    merged.source_row_numbers = sorted(merged_rows)
    merged.extraction_issues = list(dict.fromkeys(issue for issue in issues if issue.strip()))
    return SourcedOrderDraft(
        draft=merged,
        file_url=first.file_url,
        page=merged.source_page,
        sheet=merged.source_sheet,
        row_numbers=merged.source_row_numbers,
    )


def consolidate_order_drafts(
    drafts: list[SourcedOrderDraft],
) -> list[SourcedOrderDraft]:
    tagged_groups: dict[str, list[SourcedOrderDraft]] = {}
    untagged: list[SourcedOrderDraft] = []
    ordered_keys: list[str] = []

    for sourced in drafts:
        key = _tag_key(sourced.draft.tag_code)
        if key is None:
            untagged.append(sourced)
            continue
        if key not in tagged_groups:
            tagged_groups[key] = []
            ordered_keys.append(key)
        tagged_groups[key].append(sourced)

    consolidated: list[SourcedOrderDraft] = []
    for key in ordered_keys:
        group = tagged_groups[key]
        if _identity_conflicts(group):
            consolidated.extend(_mark_tag_collision(group))
        else:
            consolidated.append(_merge_group(group))
    consolidated.extend(untagged)
    return consolidated

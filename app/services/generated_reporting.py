import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from openai import OpenAI

from app.core.config import get_settings
from app.schemas.report import (
    GenerateReportRequest,
    GenerateReportResponse,
    ReportFileFormat,
)
from app.services.generated_report_data import (
    ChartSpec,
    ReportDataset,
    ReportNarrative,
    build_generated_report_dataset,
)
from app.services.mongo import fetch_generated_report_documents
from app.services.r2_storage import upload_report
from app.services.report_renderers import render_pdf_report, render_xlsx_report
from app.services.reporting import ensure_utc


class GeneratedReportError(Exception):
    pass


def safe_filename_part(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip()).strip("_").lower()
    return normalized or "laundry"


def report_period_label(payload: GenerateReportRequest) -> str:
    if payload.start_date and payload.end_date:
        start = ensure_utc(payload.start_date)
        end = ensure_utc(payload.end_date)
        return f"{start:%d %b %Y} to {end:%d %b %Y}"
    return f"Snapshot as of {datetime.now(UTC):%d %b %Y, %H:%M UTC}"


def deterministic_chart_explanation(chart: ChartSpec) -> str:
    if not chart.values:
        return "There is not enough chart data to draw a reliable conclusion."
    total = sum(chart.values)
    peak_index = max(range(len(chart.values)), key=chart.values.__getitem__)
    peak_label = chart.labels[peak_index]
    peak_value = chart.values[peak_index]
    if chart.kind == "pie" and total:
        return (
            f"{peak_label} is the largest component at {(peak_value / total) * 100:.1f}% "
            "of the values represented in this chart."
        )
    low_index = min(range(len(chart.values)), key=chart.values.__getitem__)
    return (
        f"The strongest point is {peak_label} at {peak_value:,.0f}, while "
        f"{chart.labels[low_index]} is the weakest at {chart.values[low_index]:,.0f}."
    )


def deterministic_narrative(dataset: ReportDataset) -> ReportNarrative:
    if not dataset.rows:
        return ReportNarrative(
            executive_summary=(
                "No records were found for this report selection. The available snapshot metrics are "
                "shown, but there is insufficient activity to support trend or performance conclusions."
            ),
            chart_explanations={
                chart.title: deterministic_chart_explanation(chart)
                for chart in dataset.charts
            },
            key_findings=["No activity records matched the selected report scope."],
            recommendation="Confirm the selected dates and entity before making a business decision from this report.",
        )
    metrics = "; ".join(f"{label}: {value}" for label, value in dataset.metrics)
    return ReportNarrative(
        executive_summary=(
            f"This report covers {len(dataset.rows)} record(s). The verified headline position is {metrics}."
        ),
        chart_explanations={
            chart.title: deterministic_chart_explanation(chart)
            for chart in dataset.charts
        },
        key_findings=[f"{label}: {value}." for label, value in dataset.metrics[:3]],
        recommendation="Use the strongest and weakest signals in this report to prioritize the next operational review.",
    )


def generate_report_narrative(dataset: ReportDataset, period_label: str) -> ReportNarrative:
    if not dataset.rows:
        return deterministic_narrative(dataset)

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    chart_titles = [chart.title for chart in dataset.charts]
    prompt = (
        "Prepare decision-focused management commentary for a laundry owner using only the verified facts below. "
        "Prioritize revenue, collections, customer value, concentration, aging, capacity, or financial risk where relevant. "
        "Ignore incidental workflow states and do not manufacture an insight merely because a field exists. "
        "The executive summary must explain the overall position and the most important implication in at most 180 words. "
        "Provide one concise explanation for every chart title listed, using its actual values and explaining why it matters. "
        "Return 2 to 4 high-value findings and one practical recommendation. Do not invent previous-period comparisons, "
        "causes, benchmarks, or targets. Do not use markdown.\n\n"
        f"Reporting period: {period_label}\n"
        f"Required chart titles: {json.dumps(chart_titles)}\n"
        f"Verified facts: {json.dumps(dataset.narrative_facts(), ensure_ascii=True)}"
    )
    try:
        response = client.chat.completions.create(
            model=settings.openai_chat_model,
            messages=[
                {
                    "role": "system",
                    "content": "You write concise, factual management commentary for laundry businesses.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "management_report_narrative",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "executive_summary": {"type": "string"},
                            "chart_explanations": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "explanation": {"type": "string"},
                                    },
                                    "required": ["title", "explanation"],
                                    "additionalProperties": False,
                                },
                            },
                            "key_findings": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "recommendation": {"type": "string"},
                        },
                        "required": [
                            "executive_summary",
                            "chart_explanations",
                            "key_findings",
                            "recommendation",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
        )
        content = response.choices[0].message.content
        if not content:
            return deterministic_narrative(dataset)
        parsed = json.loads(content)
        explanations = {
            item["title"]: item["explanation"]
            for item in parsed["chart_explanations"]
            if item["title"] in chart_titles
        }
        fallback = deterministic_narrative(dataset)
        for chart in dataset.charts:
            explanations.setdefault(chart.title, deterministic_chart_explanation(chart))
        key_findings = [
            finding.strip()
            for finding in parsed["key_findings"][:4]
            if finding.strip()
        ] or fallback.key_findings
        return ReportNarrative(
            executive_summary=(
                parsed["executive_summary"].strip()
                or fallback.executive_summary
            ),
            chart_explanations=explanations,
            key_findings=key_findings,
            recommendation=(
                parsed["recommendation"].strip()
                or fallback.recommendation
            ),
        )
    except Exception:
        return deterministic_narrative(dataset)


def generate_report_file(payload: GenerateReportRequest) -> GenerateReportResponse:
    start_date = ensure_utc(payload.start_date) if payload.start_date else None
    end_date = ensure_utc(payload.end_date) if payload.end_date else None
    try:
        laundry, documents = fetch_generated_report_documents(
            payload.laundry_id,
            payload.entity.value,
            start_date,
            end_date,
        )
    except ValueError as exc:
        raise GeneratedReportError(str(exc)) from exc
    except Exception as exc:
        raise GeneratedReportError("Failed to load report data from MongoDB.") from exc

    dataset = build_generated_report_dataset(payload.entity.value, documents)
    laundry_name = str(laundry.get("laundryName") or "Laundry")
    period_label = report_period_label(payload)

    if payload.format == ReportFileFormat.PDF:
        narrative = generate_report_narrative(dataset, period_label)
        content = render_pdf_report(dataset, laundry_name, period_label, narrative)
        content_type = "application/pdf"
    else:
        content = render_xlsx_report(dataset)
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    laundry_part = safe_filename_part(laundry_name)
    entity_part = payload.entity.value
    if start_date and end_date:
        period_part = f"{start_date:%Y-%m-%d}_to_{end_date:%Y-%m-%d}"
    else:
        period_part = datetime.now(UTC).strftime("%Y-%m-%d")
    filename = f"{laundry_part}_{entity_part}_{period_part}.{payload.format.value}"
    now = datetime.now(UTC)
    object_key = (
        f"reports/{payload.laundry_id}/{entity_part}/{now:%Y/%m}/"
        f"{uuid4().hex}.{payload.format.value}"
    )

    try:
        download_url = upload_report(content, object_key, filename, content_type)
    except Exception as exc:
        raise GeneratedReportError("Failed to upload generated report to Cloudflare R2.") from exc

    return GenerateReportResponse(
        success=True,
        filename=filename,
        object_key=object_key,
        download_url=download_url,
    )

from fastapi import APIRouter, HTTPException

from app.schemas.report import (
    DebtRiskAnalysisRequest,
    DebtRiskAnalysisResponse,
    GenerateReportRequest,
    GenerateReportResponse,
    WeeklySummaryReportRequest,
    WeeklySummaryReportResponse,
)
from app.services.generated_reporting import GeneratedReportError, generate_report_file
from app.services.reporting import (
    WeeklySummaryReportError,
    generate_debt_risk_analysis_report,
    generate_weekly_summary_report,
)


router = APIRouter(tags=["reports"])


@router.post(
    "/reports/generate",
    response_model=GenerateReportResponse,
    summary="Generate and upload an entity report as PDF or Excel",
    description=(
        "Generates an entity-specific management report for one laundry business, uploads it to the configured "
        "private Cloudflare R2 bucket, and returns a temporary download URL.\n\n"
        "Send `laundry_id`, `business_id`, or both. At least one is required. A migrated branch's `laundry_id` "
        "selects that branch and may be sent with its shared `business_id`; generated data is restricted to that "
        "branch. Sending only `business_id` selects the whole business. Legacy laundries remain supported.\n\n"
        "Supported entities are `laundry`, `bank_account`, `customers`, `debts`, `members`, `wallet`, "
        "`logistics`, `payments`, `orders`, `expenses`, `profitability`, `settlements`, "
        "`wallet_transactions`, `services`, `items`, and `financial_reconciliation`. Historical entities "
        "require `start_date` and `end_date`; "
        "snapshot entities (`laundry`, `bank_account`, and `wallet`) do not.\n\n"
        "Reports combine the selected entity with the relevant orders, order payments, customer receipts, "
        "payment allocations, ledger entries, expenses, settlements, wallet movements, and service/item "
        "catalog records where applicable. Refunds reduce net collections. Payment stages are reconciled rather than added together, preventing "
        "the same money from being counted repeatedly. If a selected range contains a dated expense, that actual "
        "expense record is included; legacy monthly records remain compatible without artificial prorating. "
        "`profitability` is therefore an operating estimate that clearly separates billed sales, cash collections, "
        "recorded expenses, and platform fees.\n\n"
        "PDF reports contain verified KPI metrics, a decision-focused executive analysis, only charts "
        "supported by sufficient data, an explanation beneath every chart, key findings, and a recommended action. "
        "PDF files deliberately exclude detailed record tables. XLSX reports contain one clean `Data` worksheet "
        "with typed record values only: no AI commentary, summary sections, or charts. All PDF calculations and chart values are produced in code; "
        "AI is used only to articulate the verified facts. If AI narrative generation is unavailable, report "
        "generation continues with a deterministic summary.\n\n"
        "The `download_url` is a presigned URL and expires after one hour by default."
    ),
    responses={
        400: {
            "description": "Invalid scope id, unsupported request, or report data failure.",
            "content": {"application/json": {"example": {"detail": "Laundry not found."}}},
        },
        500: {
            "description": "Unexpected file-generation or R2 upload failure.",
            "content": {
                "application/json": {
                    "example": {"detail": "Failed to upload generated report to Cloudflare R2."}
                }
            },
        },
    },
)
def generate_report_endpoint(payload: GenerateReportRequest) -> GenerateReportResponse:
    try:
        return generate_report_file(payload)
    except GeneratedReportError as exc:
        message = str(exc)
        status_code = 400 if message in {
            "Laundry not found.",
            "Business not found.",
            "laundry_id and business_id do not belong together.",
            "Unsupported report entity.",
        } or message.startswith(("Invalid ", "The selected report contains")) else 500
        raise HTTPException(status_code=status_code, detail=message) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate report: {str(exc)}",
        ) from exc


@router.post(
    "/reports/weekly-summary",
    response_model=WeeklySummaryReportResponse,
    summary="Generate a weekly summary report for a laundry",
    description=(
        "Generates a plain-text weekly business summary for a laundry within a caller-specified ISO date range. "
        "The endpoint computes factual metrics from MongoDB first, then uses the AI model only to convert those "
        "facts into a narrative summary suitable for insertion into a document by the backend.\n\n"
        "The backend should send a branch `laundry_id`, a business-wide `business_id`, or both, plus `start_date` "
        "and `end_date` in ISO 8601 format. When both ids are sent, the selected branch must belong to the business."
    ),
    responses={
        400: {
            "description": "Invalid scope id, invalid date range, or report-generation validation failure.",
            "content": {
                "application/json": {
                    "example": {"detail": "end_date must be greater than start_date."}
                }
            },
        },
        500: {
            "description": "Unexpected server-side failure while generating the weekly report.",
            "content": {
                "application/json": {
                    "example": {"detail": "Failed to generate weekly summary report."}
                }
            },
        },
    },
)
def weekly_summary_report_endpoint(
    payload: WeeklySummaryReportRequest,
) -> WeeklySummaryReportResponse:
    try:
        return generate_weekly_summary_report(
            payload.laundry_id,
            payload.start_date,
            payload.end_date,
            payload.business_id,
        )
    except WeeklySummaryReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate weekly summary report: {str(exc)}",
        ) from exc


@router.post(
    "/reports/debt-risk-analysis",
    response_model=DebtRiskAnalysisResponse,
    summary="Generate a debt risk analysis report for a laundry",
    description=(
        "Generates a current debt-risk report for a laundry using all currently outstanding debt records. "
        "The response includes a structured debt table with `Customer`, `Debt Owed`, and `Time Frame`, "
        "plus a plain-text summary that explains the debt exposure and trend.\n\n"
        "This endpoint is not tied to a reporting date range. It uses the full current debt position for the resolved "
        "scope. A branch `laundry_id` restricts the report to that branch; sending only `business_id` uses the whole business."
    ),
    responses={
        400: {
            "description": "Invalid scope id or debt-risk generation failure.",
            "content": {
                "application/json": {
                    "example": {"detail": "Laundry not found."}
                }
            },
        },
        500: {
            "description": "Unexpected server-side failure while generating the debt-risk report.",
            "content": {
                "application/json": {
                    "example": {"detail": "Failed to generate debt risk analysis report."}
                }
            },
        },
    },
)
def debt_risk_analysis_report_endpoint(
    payload: DebtRiskAnalysisRequest,
) -> DebtRiskAnalysisResponse:
    try:
        return generate_debt_risk_analysis_report(
            payload.laundry_id,
            payload.business_id,
        )
    except WeeklySummaryReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate debt risk analysis report: {str(exc)}",
        ) from exc

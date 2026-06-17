from fastapi import APIRouter, HTTPException

from app.schemas.report import (
    DebtRiskAnalysisRequest,
    DebtRiskAnalysisResponse,
    WeeklySummaryReportRequest,
    WeeklySummaryReportResponse,
)
from app.services.reporting import (
    WeeklySummaryReportError,
    generate_debt_risk_analysis_report,
    generate_weekly_summary_report,
)


router = APIRouter(tags=["reports"])


@router.post(
    "/reports/weekly-summary",
    response_model=WeeklySummaryReportResponse,
    summary="Generate a weekly summary report for a laundry",
    description=(
        "Generates a plain-text weekly business summary for a laundry within a caller-specified ISO date range. "
        "The endpoint computes factual metrics from MongoDB first, then uses the AI model only to convert those "
        "facts into a narrative summary suitable for insertion into a document by the backend.\n\n"
        "The backend should send `laundry_id`, `start_date`, and `end_date` in ISO 8601 format."
    ),
    responses={
        400: {
            "description": "Invalid laundry id, invalid date range, or report-generation validation failure.",
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
        "This endpoint is not tied to a reporting date range. It uses the full current debt position for the specified laundry."
    ),
    responses={
        400: {
            "description": "Invalid laundry id or debt-risk generation failure.",
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
        return generate_debt_risk_analysis_report(payload.laundry_id)
    except WeeklySummaryReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate debt risk analysis report: {str(exc)}",
        ) from exc

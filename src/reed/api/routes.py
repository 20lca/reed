from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from reed.api.schemas import (
    CalculationAcceptedResponse,
    ConsumeResultResponse,
    JobStatusResponse,
)
from reed.jobs.service import CalculationService, JobNotFoundError, ResultNotReadyError
from reed.pipeline.models import CalculationKind, ProductName

router = APIRouter()


def get_service(request: Request) -> CalculationService:
    return request.app.state.calculation_service


@router.post(
    "/v1/calculations",
    response_model=CalculationAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_calculation(
    request: Request,
    archive: UploadFile = File(...),
    product: ProductName = Form(...),
    country: str | None = Form(default=None),
    calculation_kind: CalculationKind = Form(default=CalculationKind.monitoring),
    finished: bool = Form(default=True),
):
    service = get_service(request)
    try:
        submission = service.submit_archive(
            filename=archive.filename or "upload.tar",
            media_type=archive.content_type,
            content=await archive.read(),
            product=product,
            country=country,
            calculation_kind=calculation_kind,
            finished=finished,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return CalculationAcceptedResponse(
        job_id=submission.job_id,
        result_id=submission.result_id,
        status=submission.status,
        submitted_at=submission.submitted_at,
    )


@router.get("/v1/calculations/{job_id}", response_model=JobStatusResponse)
def get_calculation(job_id: str, request: Request):
    service = get_service(request)
    try:
        job = service.get_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return JobStatusResponse(**job.public_dict())


@router.get("/v1/results/{result_id}")
def get_result(result_id: str, request: Request):
    service = get_service(request)
    try:
        return service.get_result(result_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ResultNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/v1/results/{result_id}/consume", response_model=ConsumeResultResponse)
def consume_result(result_id: str, request: Request):
    service = get_service(request)
    try:
        job = service.consume_result(result_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ResultNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return ConsumeResultResponse(
        result_id=job.result_id,
        status="consumed",
        consumed_at=job.consumed_at,
    )

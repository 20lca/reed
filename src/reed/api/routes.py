from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from reed.api.schemas import (
    CalculationAcceptedResponse,
    ConsumeResultResponse,
    JobStatusResponse,
)
from reed.jobs.service import CalculationService, JobNotFoundError, ResultNotReadyError

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
    product: str | None = Form(default=None),
    country: str | None = Form(default=None),
    finished: bool = Form(default=True),
    transport_metadata: str | None = Form(
        default=None,
        deprecated=True,
        description=(
            "Deprecated diagnostic metadata. It is stored with the request but does "
            "not affect calculation results or idempotency."
        ),
    ),
):
    service = get_service(request)
    try:
        metadata = json.loads(transport_metadata) if transport_metadata else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="transport_metadata must be valid JSON",
        ) from exc

    if not isinstance(metadata, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="transport_metadata must decode to a JSON object",
        )

    try:
        submission = service.submit_archive(
            filename=archive.filename or "upload.tar",
            media_type=archive.content_type,
            content=await archive.read(),
            product=product,
            country=country,
            finished=finished,
            transport_metadata=metadata,
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

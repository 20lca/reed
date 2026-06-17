from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CalculationAcceptedResponse(BaseModel):
    job_id: str
    result_id: str
    status: str
    submitted_at: datetime


class JobStatusResponse(BaseModel):
    job_id: str
    result_id: str
    status: str
    company: str
    event_id: str
    calculation_kind: str
    finished: bool
    submitted_at: datetime
    updated_at: datetime
    error_code: str | None = None
    error_message: str | None = None
    consumed_at: datetime | None = None
    expires_at: datetime | None = None


class ConsumeResultResponse(BaseModel):
    result_id: str
    status: str
    consumed_at: datetime | None = None

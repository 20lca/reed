from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class JobStatus(str, Enum):
    accepted = "accepted"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    expired = "expired"


class JobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    result_id: str
    status: JobStatus
    company: str
    event_id: str
    calculation_kind: str = "monitoring"
    finished: bool = True
    checksum: str
    submitted_at: datetime
    updated_at: datetime
    payload_path: str
    archive_path: str | None = None
    archive_filename: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    consumed_at: datetime | None = None
    expires_at: datetime | None = None

    def public_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "result_id": self.result_id,
            "status": self.status.value,
            "company": self.company,
            "event_id": self.event_id,
            "calculation_kind": self.calculation_kind,
            "finished": self.finished,
            "submitted_at": self.submitted_at,
            "updated_at": self.updated_at,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "consumed_at": self.consumed_at,
            "expires_at": self.expires_at,
        }


class SubmissionResult(BaseModel):
    job_id: str
    result_id: str
    status: str
    submitted_at: datetime

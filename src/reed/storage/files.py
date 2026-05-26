from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from reed.jobs.models import JobRecord, JobStatus
from reed.pipeline.models import NormalizedEventPayload


class FileStorage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.jobs_dir = self.root / "jobs"
        self.payloads_dir = self.root / "payloads"
        self.archives_dir = self.root / "archives"
        self.results_dir = self.root / "results"
        self._lock = Lock()
        for path in (self.jobs_dir, self.payloads_dir, self.archives_dir, self.results_dir):
            path.mkdir(parents=True, exist_ok=True)

    def list_jobs(self) -> list[JobRecord]:
        jobs: list[JobRecord] = []
        for path in self.jobs_dir.glob("*.json"):
            jobs.append(JobRecord.model_validate_json(path.read_text(encoding="utf-8")))
        jobs.sort(key=lambda item: item.submitted_at)
        return jobs

    def get_job(self, job_id: str) -> JobRecord | None:
        path = self.jobs_dir / f"{job_id}.json"
        if not path.exists():
            return None
        return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def get_job_by_result_id(self, result_id: str) -> JobRecord | None:
        for job in self.list_jobs():
            if job.result_id == result_id:
                return job
        return None

    def save_job(self, job: JobRecord) -> JobRecord:
        path = self.jobs_dir / f"{job.job_id}.json"
        path.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        return job

    def create_job(self, job: JobRecord, payload: NormalizedEventPayload) -> JobRecord:
        with self._lock:
            self.save_payload(job.job_id, payload)
            return self.save_job(job)

    def claim_next_accepted_job(self) -> JobRecord | None:
        with self._lock:
            for job in self.list_jobs():
                if job.status is JobStatus.accepted:
                    job.status = JobStatus.processing
                    self.save_job(job)
                    return job
        return None

    def save_payload(self, job_id: str, payload: NormalizedEventPayload) -> Path:
        path = self.payloads_dir / f"{job_id}.json"
        path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        return path

    def save_archive(self, job_id: str, filename: str, content: bytes) -> Path:
        suffix = "".join(Path(filename).suffixes) or ".tar"
        path = self.archives_dir / f"{job_id}{suffix}"
        path.write_bytes(content)
        return path

    def load_payload(self, payload_path: str) -> NormalizedEventPayload:
        path = Path(payload_path)
        return NormalizedEventPayload.model_validate_json(path.read_text(encoding="utf-8"))

    def save_result(self, result_id: str, result: dict[str, Any]) -> Path:
        path = self.results_dir / f"{result_id}.json"
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return path

    def load_result(self, result_id: str) -> dict[str, Any] | None:
        path = self.results_dir / f"{result_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def delete_result(self, result_id: str) -> None:
        path = self.results_dir / f"{result_id}.json"
        if path.exists():
            path.unlink()

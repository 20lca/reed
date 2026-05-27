from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Event, Lock, Thread
from uuid import uuid4

from reed.jobs.models import JobRecord, JobStatus, SubmissionResult
from reed.pipeline.models import NormalizedEventPayload, StoredArchiveReference
from reed.pipeline.service import PipelineError, ReedCalculationPipeline
from reed.sensordata_analysis import parse_uploaded_archive
from reed.storage.files import FileStorage
from reed.utils import Config


class JobNotFoundError(RuntimeError):
    pass


class ResultNotReadyError(RuntimeError):
    pass


class CalculationService:
    def __init__(
        self,
        *,
        storage: FileStorage,
        pipeline: ReedCalculationPipeline,
        settings: Config,
    ):
        self.storage = storage
        self.pipeline = pipeline
        self.settings = settings
        self._worker_stop = Event()
        self._worker_thread: Thread | None = None
        self._worker_lock = Lock()

    def submit(self, payload: NormalizedEventPayload) -> SubmissionResult:
        checksum = payload.archive.sha256 or payload.checksum()
        return self._submit_payload(payload, checksum=checksum)

    def submit_archive(
        self,
        *,
        filename: str,
        media_type: str | None,
        content: bytes,
        product: str | None = None,
        country: str | None = None,
        transport_metadata: dict[str, object] | None = None,
    ) -> SubmissionResult:
        if not content:
            raise ValueError("archive upload must not be empty")
        if not filename.lower().endswith((".tar", ".tar.gz")):
            raise ValueError("archive upload must be a .tar or .tar.gz file")

        checksum = sha256(content).hexdigest()
        parsed = parse_uploaded_archive(
            content,
            archive_name=filename,
            product=product,
            country=country,
            transport_metadata=transport_metadata or {},
        )
        parsed.archive = StoredArchiveReference(
            original_filename=filename,
            media_type=media_type,
            storage_path=None,
            sha256=checksum,
        )
        return self._submit_payload(
            payload=parsed, checksum=checksum, archive_content=content
        )

    def _submit_payload(
        self,
        payload: NormalizedEventPayload,
        *,
        checksum: str,
        archive_content: bytes | None = None,
    ) -> SubmissionResult:
        now = datetime.now(UTC)
        for job in self.storage.list_jobs():
            self._expire_if_needed(job, now)
            if (
                job.company == payload.company
                and job.event_id == payload.event_id
                and job.checksum == checksum
                and job.status
                in {JobStatus.accepted, JobStatus.processing, JobStatus.completed}
                and job.consumed_at is None
            ):
                return SubmissionResult(
                    job_id=job.job_id,
                    result_id=job.result_id,
                    status=job.status.value,
                    submitted_at=job.submitted_at,
                )

        job_id = f"job_{uuid4().hex}"
        result_id = f"res_{uuid4().hex}"
        payload_path = self.storage.payloads_dir / f"{job_id}.json"
        archive_path: str | None = None
        archive_filename: str | None = None
        if archive_content is not None:
            archive_file = self.storage.save_archive(
                job_id,
                payload.archive.original_filename,
                archive_content,
            )
            archive_path = str(archive_file)
            archive_filename = payload.archive.original_filename
            payload.archive.storage_path = archive_path

        job = JobRecord(
            job_id=job_id,
            result_id=result_id,
            status=JobStatus.accepted,
            company=payload.company,
            event_id=payload.event_id,
            checksum=checksum,
            submitted_at=now,
            updated_at=now,
            payload_path=str(payload_path),
            archive_path=archive_path,
            archive_filename=archive_filename,
            expires_at=now + timedelta(hours=self.settings.RESULT_TTL_HOURS),
        )
        self.storage.create_job(job, payload)
        return SubmissionResult(
            job_id=job.job_id,
            result_id=job.result_id,
            status=job.status.value,
            submitted_at=job.submitted_at,
        )

    def get_job(self, job_id: str) -> JobRecord:
        job = self.storage.get_job(job_id)
        if job is None:
            raise JobNotFoundError(f"Job '{job_id}' was not found")
        self._expire_if_needed(job)
        return self.storage.get_job(job_id) or job

    def get_result(self, result_id: str) -> dict[str, object]:
        job = self.storage.get_job_by_result_id(result_id)
        if job is None:
            raise JobNotFoundError(f"Result '{result_id}' was not found")
        self._expire_if_needed(job)
        job = self.storage.get_job(job.job_id) or job
        if job.consumed_at is not None or job.status is JobStatus.expired:
            raise JobNotFoundError(f"Result '{result_id}' was not found")
        if job.status is not JobStatus.completed:
            raise ResultNotReadyError(f"Result '{result_id}' is not ready")
        result = self.storage.load_result(result_id)
        if result is None:
            raise JobNotFoundError(f"Result '{result_id}' was not found")
        return result

    def consume_result(self, result_id: str) -> JobRecord:
        job = self.storage.get_job_by_result_id(result_id)
        if job is None:
            raise JobNotFoundError(f"Result '{result_id}' was not found")
        self._expire_if_needed(job)
        job = self.storage.get_job(job.job_id) or job
        if job.status is JobStatus.expired:
            raise JobNotFoundError(f"Result '{result_id}' was not found")
        if job.status is not JobStatus.completed:
            raise ResultNotReadyError(f"Result '{result_id}' is not ready")
        if job.consumed_at is None:
            job.consumed_at = datetime.now(UTC)
            job.updated_at = job.consumed_at
            self.storage.delete_result(result_id)
            self.storage.save_job(job)
        return job

    def start_worker(self) -> None:
        with self._worker_lock:
            if self._worker_thread and self._worker_thread.is_alive():
                return
            self._worker_stop.clear()
            self._worker_thread = Thread(target=self._worker_loop, daemon=True)
            self._worker_thread.start()

    def stop_worker(self) -> None:
        self._worker_stop.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=2)

    def run_worker_once(self) -> bool:
        for job in self.storage.list_jobs():
            self._expire_if_needed(job)
        job = self.storage.claim_next_accepted_job()
        if job is None:
            return False

        try:
            payload = self.storage.load_payload(job.payload_path)
            result = self.pipeline.run(payload)
            self.storage.save_result(job.result_id, result)
            job.status = JobStatus.completed
            job.error_code = None
            job.error_message = None
        except PipelineError as exc:
            job.status = JobStatus.failed
            job.error_code = exc.code
            job.error_message = exc.message
        except Exception as exc:
            job.status = JobStatus.failed
            job.error_code = "internal_error"
            job.error_message = str(exc)

        job.updated_at = datetime.now(UTC)
        self.storage.save_job(job)
        return True

    def _worker_loop(self) -> None:
        while not self._worker_stop.is_set():
            processed = self.run_worker_once()
            if not processed:
                self._worker_stop.wait(self.settings.WORKER_POLL_INTERVAL_SECONDS)

    def _expire_if_needed(self, job: JobRecord, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        if (
            job.status is JobStatus.completed
            and job.consumed_at is None
            and job.expires_at is not None
            and now >= job.expires_at
        ):
            job.status = JobStatus.expired
            job.updated_at = now
            self.storage.delete_result(job.result_id)
            self.storage.save_job(job)

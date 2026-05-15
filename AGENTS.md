# AGENTS.md

## Purpose
- This repo is evolving from notebook-driven LCA analysis into a service that accepts sensor-derived manufacturing data, runs LCA calculations, stores temporary results, and exposes them for retrieval by a downstream digital product passport (DPP) service.
- The target architecture must preserve the current Brightway-based calculation logic while separating research code from production service behavior.

## Current Codebase Reality
- `src/reed/sensordata_analysis.py` contains the current sensor ingestion, event grouping, tool mapping, and aggregation logic.
- `src/reed/swapping_data.py` contains scenario construction and Brightway technosphere swap helpers used to inject sensor-derived values into REED calculations.
- `src/reed/LCA_functions.py` contains reusable LCA reporting helpers.
- `scripts/import_db.py` sets up the Brightway/Bonsai project and databases required for calculations.
- The notebooks under `scripts/` are the current end-to-end reference flows, including generation of DPP-like JSON output.

## Target Service Architecture
- `Ingestion API`: the v1 REST adapter that accepts calculation requests, validates payloads, assigns identifiers, persists job metadata, and returns immediately with async job status.
- `Calculation Worker`: consumes queued jobs, orchestrates sensor aggregation, process mapping, scenario construction, Brightway execution, and output serialization.
- `Temporary Result Store`: stores job metadata and completed DPP-like result artifacts as files; records are removed after confirmed downstream retrieval or expiry.
- `Retrieval API`: exposes job status and completed result artifacts for the downstream DPP service.

## Architecture Pattern
- The core service shape is `ingestion adapter -> NormalizedEventPayload -> async job/worker -> LCA pipeline -> result store -> retrieval API`.
- `REST` is the committed v1 ingestion adapter and the only public submission interface in the first implementation.
- `MQTT` is a possible future ingestion adapter, not a competing calculation architecture.
- All ingestion adapters must produce the same `NormalizedEventPayload` contract before work is queued.

## Normalized Worker Input
- `NormalizedEventPayload` is the worker-facing contract shared by all ingestion adapters.
- It includes `company`, `event_id`, and the event-bounded sensor measurements required by the current aggregation and process-mapping logic.
- Transport metadata may be retained separately for diagnostics or tracing, but it must not alter calculation semantics.

## Runtime Flow
1. A client submits a sensor calculation payload through the REST ingestion adapter.
2. The adapter validates the request, normalizes it into `NormalizedEventPayload`, computes a payload checksum, allocates `job_id` and `result_id`, and stores job metadata.
3. The API enqueues work and returns `202 Accepted`.
4. The worker loads the payload, runs the sensor-to-event aggregation flow, maps tool data to REED processes, and builds Brightway scenario overrides.
5. The worker executes the LCA calculation and serializes the completed result into the DPP-like JSON contract.
6. The worker marks the job as `completed` or `failed` and persists final metadata.
7. The downstream DPP service polls the retrieval API for status and fetches the completed result.
8. After successful partner retrieval, the result is explicitly consumed and deleted from temporary storage.

## Boundaries and Rules
- Keep Brightway and LCA orchestration out of the HTTP layer.
- Keep transport-specific concerns out of the LCA pipeline.
- The REST adapter owns request validation, normalization, idempotent submission, and job creation.
- Any future MQTT adapter must own topic subscription, buffering, message ordering handling, duplicate delivery handling, and event assembly before submitting work.
- Both REST and MQTT adapters must produce the same `NormalizedEventPayload` for the worker.
- Keep file-backed persistence behind a small storage interface so it can be replaced later.
- Keep DPP output formatting isolated behind a serializer/adapter; do not let downstream JSON shape leak into core calculation code.
- Treat notebooks as reference material only; production behavior must live in importable Python modules.
- Avoid introducing database or queue dependencies until file-backed async execution becomes a proven bottleneck.
- Preserve deterministic behavior for a given `(company, event_id, payload checksum)` input set.

## Public v1 Interfaces
- `POST /v1/calculations`
- `GET /v1/calculations/{job_id}`
- `GET /v1/results/{result_id}`
- `POST /v1/results/{result_id}/consume`

## Architecture Decision Note
- The current repo favors event-level ingestion over stream-first ingestion because `src/reed/sensordata_analysis.py` already expects grouped event data and performs aggregation/mapping on bounded event inputs rather than raw continuous telemetry.
- REST is therefore the practical v1 choice: it matches the current batch/event processing model without forcing the worker or Brightway pipeline to absorb transport-specific streaming concerns.

## Recommended Module Direction
- `src/reed/api/`: FastAPI routes, request/response schemas, and HTTP error handling.
- `src/reed/jobs/`: job models, queue abstraction, status transitions, and idempotency rules.
- `src/reed/storage/`: file-backed metadata/result persistence and cleanup helpers.
- `src/reed/pipeline/`: orchestration layer that adapts the existing analysis and Brightway code into a service-safe workflow.
- `src/reed/serializers/`: DPP-facing JSON generation.

## Storage Model
- Store job metadata separately from completed result artifacts.
- Keep result files temporary and disposable.
- Delete result artifacts only after explicit consume confirmation or expiry cleanup.
- Never make raw storage file layout part of the public API contract.

## Operational Expectations
- Job states: `accepted`, `processing`, `completed`, `failed`, `expired`.
- A failed job must keep enough metadata to diagnose the failure without exposing partial result artifacts.
- A completed job must remain retrievable until consumed or expired.
- Cleanup logic must be idempotent.

## Definition of Done for Future Work
- The API returns quickly and does not block on Brightway execution.
- The worker can reproduce the current notebook-style result flow for a known event.
- The retrieval contract is stable enough for the DPP partner to integrate against.
- Temporary files are cleaned up predictably after consume or expiry.

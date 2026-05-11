# PLAN.md

## Title
Initial v1 specification for the REED sensor-to-LCA API service

## Summary
- Build an async API service on top of the existing `reed` package.
- The service receives sensor-related event data, runs Brightway-based LCA calculations in a worker, stores completed output as temporary DPP-like JSON files, and exposes pull-based retrieval for a downstream DPP service.
- The first implementation prioritizes correctness and separable boundaries over infrastructure complexity.

## Chosen Defaults
- API style: HTTP/JSON.
- Runtime style: async submission with background processing.
- Service stack: FastAPI, Pydantic, Python worker abstraction in-process or file-backed queue wrapper, existing `reed` modules for calculation.
- Persistence: temporary local files only.
- Stored artifact: DPP-like JSON only, plus job/result metadata sidecars.
- Retrieval semantics: result retrieval is non-destructive; explicit consume deletes the record.

## Core User Flow
1. A producer submits a sensor calculation payload.
2. The service validates it and creates a job.
3. The worker processes the job asynchronously.
4. The service exposes job status until the result is ready.
5. The DPP partner fetches the completed result.
6. The DPP partner confirms consumption.
7. The service deletes the temporary result artifact.

## API Contract

### `POST /v1/calculations`
- Purpose: submit a new calculation request.
- Behavior: validate payload, compute checksum, apply idempotency rule, create metadata, enqueue work, return immediately.
- Response: `202 Accepted`.

Example response:

```json
{
  "job_id": "job_01",
  "result_id": "res_01",
  "status": "accepted",
  "submitted_at": "2026-05-11T12:00:00Z"
}
```

### `GET /v1/calculations/{job_id}`
- Purpose: poll calculation status.
- Success states:
  - `accepted`
  - `processing`
  - `completed`
  - `failed`
  - `expired`
- Completed response should include `result_id`.
- Failed response should include a machine-readable error code and a concise message.

### `GET /v1/results/{result_id}`
- Purpose: fetch the completed DPP-like JSON artifact.
- Behavior:
  - return not found or not ready when the job is incomplete,
  - return the JSON artifact when completed and still retained,
  - return not found after consume or expiry.

### `POST /v1/results/{result_id}/consume`
- Purpose: confirm downstream retrieval and trigger deletion.
- Behavior:
  - mark the artifact as consumed,
  - delete the result file,
  - preserve enough metadata to show that the result previously existed,
  - be safe to retry.

## Request Payload
- Minimum required fields:
  - `company`
  - `event_id`
  - `sensor_data`
- `sensor_data` must carry the measurements needed to reproduce the current aggregation and mapping flow from `sensordata_analysis.py`.
- Optional metadata may include product identifier, country, timestamps, and source-system references.
- Unknown fields should be rejected in v1 unless explicitly approved for passthrough.

Example request shape:

```json
{
  "company": "goimek",
  "event_id": "OF10005_G_BQC_S8CF2G",
  "product": "GOIMEK total",
  "country": "ES",
  "sensor_data": {
    "records": []
  }
}
```

## Result Payload
- The result contract should follow the existing repo sample in `scripts/DPP_goimek_OF10005_G_BQC_S8CF2G_2026-05-06.json`.
- Required top-level fields:
  - `DPP`
- Each DPP entry should include:
  - `company`
  - `event_id`
  - `product`
  - `carbonFootprint`
- `carbonFootprint.ProductCarbonFootprints` should contain phase-level PCF entries such as `A1`, `A2`, `A3`, and `A1-A3` when available.
- Each PCF entry should include method, score, phase, reference quantity, explanatory statement, location, and publication date.

## Idempotency and Identity
- Calculate a checksum from the normalized request payload.
- Use `(company, event_id, checksum)` as the idempotency key.
- If the same payload is submitted again while a job is pending or completed, return the existing identifiers instead of creating a duplicate.
- If the payload changes, create a new job and new result identifier.

## Storage Layout
- Metadata file example: `storage/jobs/{job_id}.json`
- Result file example: `storage/results/{result_id}.json`
- Metadata should include:
  - `job_id`
  - `result_id`
  - `status`
  - `company`
  - `event_id`
  - `checksum`
  - `submitted_at`
  - `updated_at`
  - `error`
  - `consumed_at`
  - `expires_at`
- Result file should contain only the DPP-like JSON payload exposed to the downstream service.

## Processing Pipeline
- Normalize and validate incoming payloads.
- Adapt sensor input into the current event-processing model from `sensordata_analysis.py`.
- Aggregate power and time data by event and REED tool.
- Build scenario substitutions using the helpers in `swapping_data.py`.
- Execute Brightway-based LCA calculations with the configured method from `utils.Config`.
- Serialize the output into the DPP-like JSON contract.
- Persist final metadata and result artifact.

## Failure Handling
- Validation failures are rejected at request time with 4xx responses.
- Runtime calculation failures set job status to `failed`.
- A failed job must not expose a result artifact.
- Missing mappings, Brightway setup issues, and serialization failures should each map to stable error codes.

## Cleanup and Retention
- Completed but unconsumed results should expire after a configurable retention window.
- Expired results should delete the result artifact and mark the job as `expired`.
- Consumed results should delete the result artifact immediately.
- Cleanup must be safe to rerun.

## Testing
- Submit a valid payload and verify `202 Accepted` plus metadata creation.
- Poll a job through `accepted -> processing -> completed`.
- Fetch a completed result and verify the DPP-like schema.
- Consume a result and verify the artifact is removed while metadata remains consistent.
- Resubmit an identical payload and verify idempotent reuse of identifiers.
- Submit an invalid payload and verify request rejection with no job creation.
- Force a worker error and verify `failed` status with no result exposure.
- Verify expiry cleanup removes unconsumed results and marks metadata correctly.

## Non-Goals for v1
- No relational database.
- No external queue infrastructure.
- No push delivery to the DPP partner.
- No broad authentication/authorization design in this first spec.
- No attempt to make notebooks production runtime dependencies.

## Acceptance Criteria
- A developer can implement the first service without needing to invent the API contract or storage lifecycle.
- The service boundaries align with the current `reed` calculation code.
- The downstream DPP partner can poll, retrieve, and consume completed results using a stable JSON contract.

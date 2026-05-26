from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NormalizedSensorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str
    Tool_Number: float
    Power_Active: float
    Energy_Total: float | None = None


class ParsedArchiveSensorData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[NormalizedSensorRecord]


class ArchiveMemberMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_name: str
    csv_basename: str
    measurement_type: str | None = None


class StoredArchiveReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_filename: str
    media_type: str | None = None
    storage_path: str | None = None
    sha256: str


class NormalizedEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    event_id: str
    sensor_data: ParsedArchiveSensorData
    archive: StoredArchiveReference
    source_members: list[ArchiveMemberMetadata] = Field(default_factory=list)
    product: str | None = None
    country: str | None = None
    transport_metadata: dict[str, Any] = Field(default_factory=dict)

    def checksum(self) -> str:
        payload = self.model_dump(mode="json", exclude_none=True)
        archive = payload.get("archive")
        if archive:
            archive.pop("storage_path", None)
        body = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(body.encode("utf-8")).hexdigest()

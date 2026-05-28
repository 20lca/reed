from __future__ import annotations

import io
import shutil
import tarfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reed.api.main import create_app
from reed.pipeline.models import NormalizedEventPayload
from reed.utils import Config


class FakePipeline:
    def run(self, payload: NormalizedEventPayload) -> dict[str, object]:
        archive_path = payload.archive.storage_path
        assert archive_path is not None
        with tarfile.open(archive_path, mode="r:*") as tf:
            csv_members = [member.name for member in tf.getmembers() if member.name.endswith(".csv")]

        return {
            "DPP": [
                {
                    "company": payload.company,
                    "event_id": payload.event_id,
                    "product": payload.product or f"{payload.company.upper()} total",
                    "country": payload.country,
                    "archive_members": csv_members,
                    "carbonFootprint": {
                        "ProductCarbonFootprints": [
                            {"LifeCyclePhases": [{"LifeCyclePhase": "A1"}], "PCF in kg CO2eq": 1.0},
                            {"LifeCyclePhases": [{"LifeCyclePhase": "A2"}], "PCF in kg CO2eq": 2.0},
                            {"LifeCyclePhases": [{"LifeCyclePhase": "A3"}], "PCF in kg CO2eq": 3.0},
                            {
                                "LifeCyclePhases": [{"LifeCyclePhase": "A1-A3"}],
                                "PCF in kg CO2eq": 6.0,
                            },
                        ]
                    },
                }
            ]
        }


def make_tar_archive(
    *,
    filename: str = "goimek - machine.tar.gz",
    include_lca_csv: bool = True,
    include_extra_csvs: bool = True,
    missing_power_active: bool = False,
    csv_name: str = "goimek - machine/OF10005_G_BQC_S8CF2G_ABC123.csv",
) -> tuple[str, bytes]:
    buffer = io.BytesIO()
    mode = "w:gz" if filename.endswith(".gz") else "w"
    with tarfile.open(fileobj=buffer, mode=mode) as tf:
        if include_lca_csv:
            columns = ["timestamp", "Tool_Number"]
            if not missing_power_active:
                columns.append("Power_Active")
            columns.append("Energy_Total")
            rows = [
                ["2026-05-13T10:00:00Z", "1", "3600" if not missing_power_active else None, "10"],
                ["2026-05-13T10:00:01Z", "1", "1800" if not missing_power_active else None, "11"],
            ]

            values = []
            for row in rows:
                filtered = [value for value in row if value is not None]
                values.append(",".join(filtered))
            csv_body = ",".join(columns) + "\n" + "\n".join(values) + "\n"
            info = tarfile.TarInfo(name=csv_name)
            data = csv_body.encode("utf-8")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

        if include_extra_csvs:
            extra_names = [
                "goimek - machine/OF10005_G_BQC_S8CF2G_META01.csv",
                "goimek - machine/OF10005_G_BQC_S8CF2G_META02.csv",
                "goimek - machine/OF10005_G_BQC_S8CF2G_META03.csv",
                "goimek - machine/OF10005_G_BQC_S8CF2G_META04.csv",
            ]
            for member_name in extra_names:
                data = b"foo,bar\n1,2\n"
                info = tarfile.TarInfo(name=member_name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))

    return filename, buffer.getvalue()


def create_test_client(tmp_path: Path) -> tuple[TestClient, Config]:
    settings = Config(
        STORAGE_ROOT=tmp_path / "storage",
        WORKER_POLL_INTERVAL_SECONDS=3600,
        RESULT_TTL_HOURS=24,
    )
    app = create_app(settings=settings, pipeline=FakePipeline())
    return TestClient(app), settings


@pytest.fixture
def storage_root() -> Path:
    root = Path("test-artifacts") / f"run-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def post_archive(
    client: TestClient,
    *,
    filename: str,
    content: bytes,
    product: str = "GOIMEK total",
    country: str = "ES",
):
    return client.post(
        "/v1/calculations",
        files={"archive": (filename, content, "application/gzip")},
        data={"product": product, "country": country},
    )


def test_submit_poll_fetch_and_consume_tar_upload(storage_root: Path):
    client, _ = create_test_client(storage_root)
    filename, content = make_tar_archive()

    with client:
        response = post_archive(client, filename=filename, content=content)
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "accepted"

        service = client.app.state.calculation_service
        assert service.run_worker_once() is True

        status_response = client.get(f"/v1/calculations/{body['job_id']}")
        assert status_response.status_code == 200
        status_body = status_response.json()
        assert status_body["status"] == "completed"
        assert status_body["company"] == "goimek"
        assert status_body["event_id"] == "OF10005_G_BQC_S8CF2G"

        result_response = client.get(f"/v1/results/{body['result_id']}")
        assert result_response.status_code == 200
        result_body = result_response.json()
        assert result_body["DPP"][0]["company"] == "goimek"
        assert result_body["DPP"][0]["event_id"] == "OF10005_G_BQC_S8CF2G"
        assert len(result_body["DPP"][0]["archive_members"]) == 5

        consume_response = client.post(f"/v1/results/{body['result_id']}/consume")
        assert consume_response.status_code == 200
        assert consume_response.json()["status"] == "consumed"

        missing_response = client.get(f"/v1/results/{body['result_id']}")
        assert missing_response.status_code == 404


def test_worker_reopens_persisted_archive_after_request_returns(storage_root: Path):
    client, settings = create_test_client(storage_root)
    filename, content = make_tar_archive()

    with client:
        response = post_archive(client, filename=filename, content=content)
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        archives = list((settings.STORAGE_ROOT / "archives").glob(f"{job_id}*"))
        assert len(archives) == 1
        assert archives[0].read_bytes() == content

        service = client.app.state.calculation_service
        assert service.run_worker_once() is True


def test_idempotent_submit_reuses_identifiers_for_same_archive(storage_root: Path):
    client, _ = create_test_client(storage_root)
    filename, content = make_tar_archive()

    with client:
        first = post_archive(client, filename=filename, content=content)
        second = post_archive(client, filename=filename, content=content)
        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["job_id"] == second.json()["job_id"]
        assert first.json()["result_id"] == second.json()["result_id"]


def test_invalid_archive_is_rejected(storage_root: Path):
    client, settings = create_test_client(storage_root)
    with client:
        response = post_archive(client, filename="bad.tar.gz", content=b"not a tar archive")
        assert response.status_code == 400
        assert "valid tar archive" in response.json()["detail"]
        assert list((settings.STORAGE_ROOT / "jobs").glob("*.json")) == []


def test_archive_with_no_csvs_is_rejected(storage_root: Path):
    client, _ = create_test_client(storage_root)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz"):
        pass

    with client:
        response = post_archive(client, filename="goimek - machine.tar.gz", content=buffer.getvalue())
        assert response.status_code == 400
        assert "No CSV files found" in response.json()["detail"]


def test_archive_with_no_lca_csv_is_rejected(storage_root: Path):
    client, _ = create_test_client(storage_root)
    filename, content = make_tar_archive(include_lca_csv=False, include_extra_csvs=True)

    with client:
        response = post_archive(client, filename=filename, content=content)
        assert response.status_code == 400
        assert "expected LCA schema" in response.json()["detail"]


def test_archive_missing_power_active_is_rejected(storage_root: Path):
    client, _ = create_test_client(storage_root)
    filename, content = make_tar_archive(missing_power_active=True)

    with client:
        response = post_archive(client, filename=filename, content=content)
        assert response.status_code == 400
        assert "expected LCA schema" in response.json()["detail"]


def test_real_pipeline_bootstraps_brightway_before_worker(
    monkeypatch: pytest.MonkeyPatch, storage_root: Path
):
    settings = Config(
        STORAGE_ROOT=storage_root / "storage",
        WORKER_POLL_INTERVAL_SECONDS=3600,
        RESULT_TTL_HOURS=24,
    )
    calls: list[str] = []

    monkeypatch.setattr(
        "reed.api.main.ensure_brightway_databases",
        lambda received_settings: calls.append("bootstrap"),
    )
    monkeypatch.setattr(
        "reed.api.main.CalculationService.start_worker",
        lambda self: calls.append("start_worker"),
    )
    monkeypatch.setattr("reed.api.main.CalculationService.stop_worker", lambda self: None)

    app = create_app(settings=settings)

    with TestClient(app):
        pass

    assert calls == ["bootstrap", "start_worker"]


def test_fake_pipeline_skips_brightway_bootstrap(
    monkeypatch: pytest.MonkeyPatch, storage_root: Path
):
    client, _ = create_test_client(storage_root)

    monkeypatch.setattr(
        "reed.api.main.ensure_brightway_databases",
        lambda settings: pytest.fail("fake pipeline should not bootstrap Brightway"),
    )

    with client:
        pass

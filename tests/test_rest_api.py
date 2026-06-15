from __future__ import annotations

import io
import shutil
import tarfile
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from reed.api.main import create_app
from reed.pipeline.models import NormalizedEventPayload
from reed.pipeline.service import ReedCalculationPipeline
from reed.sensordata_analysis import load_records_from_archive_bytes
from reed.utils import Config


class FakePipeline:
    def run(self, payload: NormalizedEventPayload) -> dict[str, object]:
        archive_path = payload.archive.storage_path
        assert archive_path is not None
        with tarfile.open(archive_path, mode="r:*") as tf:
            csv_members = [member.name for member in tf.getmembers() if member.name.endswith(".csv")]

        if payload.calculation_kind == "simulation":
            return {
                "product": payload.product.value,
                "total_climate_impact_kg_co2eq": 6.0,
                "a1_raw_materials": {"total_kg_co2eq": 1.0},
                "a2_transport": {"total_kg_co2eq": 2.0},
                "a3_machining": {
                    "total_kg_co2eq": 3.0,
                    "operations": [
                        {"operation": "drilling", "amount": 2.0},
                        {"operation": "milling", "amount": 1.0},
                    ],
                },
            }

        if not payload.finished:
            return {
                "product": payload.product.value,
                "total_climate_impact_kg_co2eq": 6.0,
                "machining_contributions": [
                    {"operation": "drilling", "amount": 2.0},
                    {"operation": "milling", "amount": 1.0},
                ],
            }

        return {
            "DPP": [
                {
                    "company": payload.company,
                    "event_id": payload.event_id,
                    "product": payload.product.value,
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


def make_split_lca_tar_archive() -> tuple[str, bytes]:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tf:
        files = {
            "goimek - machine/OF10004_G_TWB_7SZ421_92SQBY.csv": (
                "Energy_Total,Power_Active,timestamp\n"
                "10,3600,2025-11-21T08:35:21.839Z\n"
                "11,1800,2025-11-21T08:35:22.839Z\n"
            ),
            "goimek - machine/OF10004_G_TWB_7SZ421_TYZBPS.csv": (
                "Tool_Number,timestamp\n"
                "1,2025-11-21T08:35:21.491Z\n"
                "1,2025-11-21T08:35:22.492Z\n"
            ),
        }
        for name, body in files.items():
            data = body.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

    return "goimek - machine.tar", buffer.getvalue()


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
    calculation_kind: str | None = None,
    finished: bool | None = None,
):
    data = {"product": product, "country": country}
    if calculation_kind is not None:
        data["calculation_kind"] = calculation_kind
    if finished is not None:
        data["finished"] = str(finished).lower()
    return client.post(
        "/v1/calculations",
        files={"archive": (filename, content, "application/gzip")},
        data=data,
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
        assert status_body["calculation_kind"] == "monitoring"
        assert status_body["finished"] is True

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


def test_valid_goimek_product_upload_returns_accepted(storage_root: Path):
    client, _ = create_test_client(storage_root)
    filename, content = make_tar_archive()

    with client:
        response = post_archive(
            client,
            filename=filename,
            content=content,
            product="GOIMEK total",
        )

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"


def test_missing_product_is_rejected(storage_root: Path):
    client, settings = create_test_client(storage_root)
    filename, content = make_tar_archive()

    with client:
        response = client.post(
            "/v1/calculations",
            files={"archive": (filename, content, "application/gzip")},
            data={"country": "ES"},
        )

    assert response.status_code == 422
    assert list((settings.STORAGE_ROOT / "jobs").glob("*.json")) == []


def test_invalid_product_is_rejected_before_job_creation(storage_root: Path):
    client, settings = create_test_client(storage_root)
    filename, content = make_tar_archive()

    with client:
        response = post_archive(
            client,
            filename=filename,
            content=content,
            product="ACME total",
        )

    assert response.status_code == 422
    assert list((settings.STORAGE_ROOT / "jobs").glob("*.json")) == []


def test_calculation_openapi_schema_exposes_allowed_products(storage_root: Path):
    client, _ = create_test_client(storage_root)

    with client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    product_schema = response.json()["components"]["schemas"]["ProductName"]
    assert product_schema["enum"] == ["WWR total", "GOIMEK total", "KOMATSU total"]


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


def test_archive_parser_ignores_machine_suffix_when_inferring_company():
    filename, content = make_tar_archive()

    records = load_records_from_archive_bytes(content, archive_name=filename)

    assert {record["company"] for record in records} == {"goimek"}
    assert {record["event_id"] for record in records} == {"OF10005_G_BQC_S8CF2G"}
    assert all("machine_name" not in record for record in records)


def test_archive_parser_accepts_lca_columns_split_across_csvs():
    filename, content = make_split_lca_tar_archive()

    records = load_records_from_archive_bytes(content, archive_name=filename)

    assert {record["csv_basename"] for record in records} == {
        "OF10004_G_TWB_7SZ421_92SQBY.csv",
        "OF10004_G_TWB_7SZ421_TYZBPS.csv",
    }
    assert {record["event_id"] for record in records} == {"OF10004_G_TWB_7SZ421"}


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


def test_unfinished_submit_returns_monitoring_report(storage_root: Path):
    client, _ = create_test_client(storage_root)
    filename, content = make_tar_archive()

    with client:
        response = post_archive(
            client,
            filename=filename,
            content=content,
            finished=False,
        )
        assert response.status_code == 202
        body = response.json()

        service = client.app.state.calculation_service
        assert service.run_worker_once() is True

        status_response = client.get(f"/v1/calculations/{body['job_id']}")
        assert status_response.json()["finished"] is False

        result_response = client.get(f"/v1/results/{body['result_id']}")
        assert result_response.status_code == 200
        assert result_response.json() == {
            "product": "GOIMEK total",
            "total_climate_impact_kg_co2eq": 6.0,
            "machining_contributions": [
                {"operation": "drilling", "amount": 2.0},
                {"operation": "milling", "amount": 1.0},
            ],
        }


def test_simulation_submit_returns_non_dpp_simulation_report(storage_root: Path):
    client, _ = create_test_client(storage_root)
    filename, content = make_tar_archive()

    with client:
        response = post_archive(
            client,
            filename=filename,
            content=content,
            calculation_kind="simulation",
            finished=True,
        )
        assert response.status_code == 202
        body = response.json()

        service = client.app.state.calculation_service
        assert service.run_worker_once() is True

        status_response = client.get(f"/v1/calculations/{body['job_id']}")
        status_body = status_response.json()
        assert status_body["calculation_kind"] == "simulation"
        assert status_body["finished"] is True

        result_response = client.get(f"/v1/results/{body['result_id']}")
        assert result_response.status_code == 200
        assert result_response.json() == {
            "product": "GOIMEK total",
            "total_climate_impact_kg_co2eq": 6.0,
            "a1_raw_materials": {"total_kg_co2eq": 1.0},
            "a2_transport": {"total_kg_co2eq": 2.0},
            "a3_machining": {
                "total_kg_co2eq": 3.0,
                "operations": [
                    {"operation": "drilling", "amount": 2.0},
                    {"operation": "milling", "amount": 1.0},
                ],
            },
        }
        assert "DPP" not in result_response.json()

        consume_response = client.post(f"/v1/results/{body['result_id']}/consume")
        assert consume_response.status_code == 200


def test_same_archive_finished_state_creates_distinct_jobs(storage_root: Path):
    client, _ = create_test_client(storage_root)
    filename, content = make_tar_archive()

    with client:
        unfinished = post_archive(
            client,
            filename=filename,
            content=content,
            finished=False,
        )
        finished = post_archive(
            client,
            filename=filename,
            content=content,
            finished=True,
        )

        assert unfinished.status_code == 202
        assert finished.status_code == 202
        assert unfinished.json()["job_id"] != finished.json()["job_id"]
        assert unfinished.json()["result_id"] != finished.json()["result_id"]


def test_same_archive_calculation_kind_creates_distinct_jobs(storage_root: Path):
    client, _ = create_test_client(storage_root)
    filename, content = make_tar_archive()

    with client:
        monitoring = post_archive(
            client,
            filename=filename,
            content=content,
            calculation_kind="monitoring",
            finished=False,
        )
        simulation = post_archive(
            client,
            filename=filename,
            content=content,
            calculation_kind="simulation",
            finished=False,
        )

        assert monitoring.status_code == 202
        assert simulation.status_code == 202
        assert monitoring.json()["job_id"] != simulation.json()["job_id"]
        assert monitoring.json()["result_id"] != simulation.json()["result_id"]


def test_same_archive_upload_is_idempotent(storage_root: Path):
    client, _ = create_test_client(storage_root)
    filename, content = make_tar_archive()

    with client:
        first = post_archive(
            client,
            filename=filename,
            content=content,
            calculation_kind="monitoring",
            finished=False,
        )
        second = post_archive(
            client,
            filename=filename,
            content=content,
            calculation_kind="monitoring",
            finished=False,
        )

        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["job_id"] == second.json()["job_id"]
        assert first.json()["result_id"] == second.json()["result_id"]


def test_direct_submit_finished_state_changes_idempotency(storage_root: Path):
    client, _ = create_test_client(storage_root)
    base_payload = {
        "company": "goimek",
        "event_id": "event-1",
        "product": "GOIMEK total",
        "country": "ES",
        "calculation_kind": "monitoring",
        "sensor_data": {
            "records": [
                {
                    "timestamp": "2026-05-13T10:00:00Z",
                    "Tool_Number": 1,
                    "Power_Active": 3600,
                }
            ]
        },
        "archive": {
            "original_filename": "event.tar.gz",
            "sha256": "same-archive",
        },
    }

    with client:
        service = client.app.state.calculation_service
        unfinished = service.submit(
            NormalizedEventPayload.model_validate({**base_payload, "finished": False})
        )
        finished = service.submit(
            NormalizedEventPayload.model_validate({**base_payload, "finished": True})
        )

    assert unfinished.job_id != finished.job_id
    assert unfinished.result_id != finished.result_id


def test_direct_submit_calculation_kind_changes_idempotency(storage_root: Path):
    client, _ = create_test_client(storage_root)
    base_payload = {
        "company": "goimek",
        "event_id": "event-1",
        "product": "GOIMEK total",
        "country": "ES",
        "finished": False,
        "sensor_data": {
            "records": [
                {
                    "timestamp": "2026-05-13T10:00:00Z",
                    "Tool_Number": 1,
                    "Power_Active": 3600,
                }
            ]
        },
        "archive": {
            "original_filename": "event.tar.gz",
            "sha256": "same-archive",
        },
    }

    with client:
        service = client.app.state.calculation_service
        monitoring = service.submit(
            NormalizedEventPayload.model_validate(
                {**base_payload, "calculation_kind": "monitoring"}
            )
        )
        simulation = service.submit(
            NormalizedEventPayload.model_validate(
                {**base_payload, "calculation_kind": "simulation"}
            )
        )

    assert monitoring.job_id != simulation.job_id
    assert monitoring.result_id != simulation.result_id


def test_normalized_event_payload_rejects_invalid_product():
    with pytest.raises(ValidationError):
        NormalizedEventPayload.model_validate(
            {
                "company": "goimek",
                "event_id": "event-1",
                "product": "ACME total",
                "country": "ES",
                "sensor_data": {
                    "records": [
                        {
                            "timestamp": "2026-05-13T10:00:00Z",
                            "Tool_Number": 1,
                            "Power_Active": 3600,
                        }
                    ]
                },
                "archive": {
                    "original_filename": "event.tar.gz",
                    "sha256": "same-archive",
                },
            }
        )


def test_submit_archive_rejects_invalid_product_before_job_creation(storage_root: Path):
    client, settings = create_test_client(storage_root)
    filename, content = make_tar_archive()

    with client:
        service = client.app.state.calculation_service
        with pytest.raises(ValueError, match="product must be one of"):
            service.submit_archive(
                filename=filename,
                media_type="application/gzip",
                content=content,
                product="ACME total",
                country="ES",
            )

    assert list((settings.STORAGE_ROOT / "jobs").glob("*.json")) == []


@pytest.mark.parametrize(("form_value", "expected"), [("0", False), ("1", True)])
def test_finished_accepts_numeric_form_values(
    storage_root: Path,
    form_value: str,
    expected: bool,
):
    client, _ = create_test_client(storage_root)
    filename, content = make_tar_archive()

    with client:
        response = client.post(
            "/v1/calculations",
            files={"archive": (filename, content, "application/gzip")},
            data={
                "product": "GOIMEK total",
                "country": "ES",
                "finished": form_value,
            },
        )
        assert response.status_code == 202

        status_response = client.get(
            f"/v1/calculations/{response.json()['job_id']}"
        )
        assert status_response.json()["finished"] is expected


@pytest.mark.parametrize(
    ("calculation_kind", "finished", "expected_key"),
    [
        ("monitoring", False, "machining_contributions"),
        ("monitoring", True, "DPP"),
        ("simulation", False, "a3_machining"),
        ("simulation", True, "a3_machining"),
    ],
)
def test_real_pipeline_selects_output_by_finished_state(
    monkeypatch: pytest.MonkeyPatch,
    storage_root: Path,
    calculation_kind: str,
    finished: bool,
    expected_key: str,
):
    settings = Config(STORAGE_ROOT=storage_root / "storage")
    pipeline = ReedCalculationPipeline(settings)
    tool_energy = pd.DataFrame(
        {
            "energy_consumption": [10.0, 5.0],
            "hours": [2.5, 1.25],
            "Power_Active": [4.0, 4.0],
        },
        index=pd.MultiIndex.from_tuples(
            [
                ("goimek", "event-1", "drilling"),
                ("goimek", "event-1", "milling"),
            ],
            names=["company", "event_id", "reed tool"],
        ),
    )
    payload = NormalizedEventPayload.model_validate(
        {
            "company": "goimek",
            "event_id": "event-1",
            "calculation_kind": calculation_kind,
            "finished": finished,
            "product": "GOIMEK total",
            "country": "ES",
            "sensor_data": {"records": []},
            "archive": {
                "original_filename": "event.tar.gz",
                "sha256": "checksum",
            },
        }
    )

    monkeypatch.setattr(pipeline, "_aggregate_sensor_data", lambda received: tool_energy)
    monkeypatch.setattr(
        pipeline,
        "_calculate_scores",
        lambda received, aggregated: (
            1.0,
            2.0,
            3.0,
            "GOIMEK total",
            "ES",
            [
                {"operation": "drilling", "amount": 2.5},
                {"operation": "milling", "amount": 1.25},
                {"operation": "soraluce machine, Goimek", "amount": 0.000091},
            ],
        ),
    )

    result = pipeline.run(payload)

    assert expected_key in result
    if calculation_kind == "monitoring" and not finished:
        assert result["total_climate_impact_kg_co2eq"] == 6.0
        assert result["machining_contributions"] == [
            {"operation": "drilling", "amount": 2.5},
            {"operation": "milling", "amount": 1.25},
            {"operation": "soraluce machine, Goimek", "amount": 9.1e-05},
        ]
    if calculation_kind == "simulation":
        assert "DPP" not in result
        assert result["total_climate_impact_kg_co2eq"] == 6.0
        assert result["a1_raw_materials"] == {"total_kg_co2eq": 1.0}
        assert result["a2_transport"] == {"total_kg_co2eq": 2.0}
        assert result["a3_machining"] == {
            "total_kg_co2eq": 3.7501,
            "operations": [
                {"operation": "drilling", "amount": 2.5},
                {"operation": "milling", "amount": 1.25},
                {"operation": "soraluce machine, Goimek", "amount": 9.1e-05},
            ],
        }


def test_monitoring_contributions_overlay_sensor_hours_and_keep_baseline(
    storage_root: Path,
):
    class Activity:
        def __init__(self, activity_id: int, name: str):
            self.id = activity_id
            self.name = name
            self._exchanges = []

        def get(self, key: str, default=None):
            return self.name if key == "name" else default

        def technosphere(self):
            return self._exchanges

    class Exchange:
        def __init__(self, input_activity: Activity, amount: float):
            self.input = input_activity
            self.amount = amount

        def __getitem__(self, key: str):
            if key == "amount":
                return self.amount
            raise KeyError(key)

    machining = Activity(100, "soraluce machining")
    drilling = Activity(1, "drilling, soraluce")
    machine = Activity(2, "soraluce machine, Goimek")
    machining._exchanges = [
        Exchange(drilling, 4.0),
        Exchange(machine, 0.000091),
    ]
    scenarios = pd.DataFrame(
        {"original": [4.0], "goimek_event-1": [50.165556]},
        index=pd.MultiIndex.from_tuples(
            [(drilling.id, machining.id)],
            names=["product", "activity"],
        ),
    )
    pipeline = ReedCalculationPipeline(
        Config(STORAGE_ROOT=storage_root / "storage")
    )

    contributions = pipeline._machining_contributions(machining, scenarios)

    assert contributions == [
        {"operation": "drilling, soraluce", "amount": 50.165556},
        {"operation": "soraluce machine, Goimek", "amount": 0.000091},
    ]


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

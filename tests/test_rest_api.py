from __future__ import annotations

import io
import shutil
import tarfile
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from reed.api.main import create_app
from reed.pipeline.models import NormalizedEventPayload
from reed.pipeline.service import ReedCalculationPipeline
from reed.utils import Config


class FakePipeline:
    def run(self, payload: NormalizedEventPayload) -> dict[str, object]:
        archive_path = payload.archive.storage_path
        assert archive_path is not None
        with tarfile.open(archive_path, mode="r:*") as tf:
            csv_members = [member.name for member in tf.getmembers() if member.name.endswith(".csv")]

        if not payload.finished:
            return {
                "product": payload.product or f"{payload.company.upper()} total",
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
    finished: bool | None = None,
):
    data = {"product": product, "country": country}
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
    ("finished", "expected_key"),
    [(False, "machining_contributions"), (True, "DPP")],
)
def test_real_pipeline_selects_output_by_finished_state(
    monkeypatch: pytest.MonkeyPatch,
    storage_root: Path,
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
    if not finished:
        assert result["total_climate_impact_kg_co2eq"] == 6.0
        assert result["machining_contributions"] == [
            {"operation": "drilling", "amount": 2.5},
            {"operation": "milling", "amount": 1.25},
            {"operation": "soraluce machine, Goimek", "amount": 9.1e-05},
        ]


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

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from reed import brightway_api
from reed.utils import Config


class FakeProjects:
    def __init__(self):
        self.current: str | None = None

    def set_current(self, project_name: str) -> None:
        self.current = project_name


class FakeBrightwayData:
    def __init__(self, databases: set[str]):
        self.projects = FakeProjects()
        self.databases = databases


@pytest.fixture
def workspace_tmp() -> Path:
    root = Path("test-artifacts") / f"brightway-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def make_settings(root: Path) -> Config:
    bonsai_path = root / "bonsai"
    bonsai_path.mkdir()
    return Config(
        PROJECT_NAME="test-reed",
        BONSAI_NAME="BONSAI_TEST",
        BONSAI_PATH=bonsai_path,
        STORAGE_ROOT=root / "storage",
    )


def test_missing_databases_trigger_import(
    monkeypatch: pytest.MonkeyPatch, workspace_tmp: Path
):
    settings = make_settings(workspace_tmp)
    fake_bd = FakeBrightwayData(databases={"reed"})
    calls: list[tuple[str, object]] = []

    def fake_import_bonsai(path: Path) -> None:
        calls.append(("bonsai", path))
        fake_bd.databases.add("BONSAI_TEST")
        fake_bd.databases.add("BONSAI_TEST biosphere")

    def fake_import_reed_db() -> None:
        calls.append(("reed", None))
        fake_bd.databases.add("reed")

    monkeypatch.setattr(brightway_api, "bd", fake_bd)
    monkeypatch.setattr(brightway_api, "import_bonsai", fake_import_bonsai)
    monkeypatch.setattr(brightway_api, "import_reed_db", fake_import_reed_db)

    brightway_api.ensure_brightway_databases(settings)

    assert fake_bd.projects.current == "test-reed"
    assert calls == [("bonsai", settings.BONSAI_PATH), ("reed", None)]


def test_ready_databases_skip_import(
    monkeypatch: pytest.MonkeyPatch, workspace_tmp: Path
):
    settings = make_settings(workspace_tmp)
    fake_bd = FakeBrightwayData(
        databases={"reed", "BONSAI_TEST", "BONSAI_TEST biosphere"}
    )

    monkeypatch.setattr(brightway_api, "bd", fake_bd)
    monkeypatch.setattr(
        brightway_api,
        "import_bonsai",
        lambda path: pytest.fail("import_bonsai should not be called"),
    )
    monkeypatch.setattr(
        brightway_api,
        "import_reed_db",
        lambda: pytest.fail("import_reed_db should not be called"),
    )

    brightway_api.ensure_brightway_databases(settings)

    assert fake_bd.projects.current == "test-reed"


def test_import_failure_names_missing_database_and_path(
    monkeypatch: pytest.MonkeyPatch, workspace_tmp: Path
):
    settings = make_settings(workspace_tmp)
    fake_bd = FakeBrightwayData(databases={"reed"})

    def fail_import(path: Path) -> None:
        raise ValueError("bad tidy files")

    monkeypatch.setattr(brightway_api, "bd", fake_bd)
    monkeypatch.setattr(brightway_api, "import_bonsai", fail_import)
    monkeypatch.setattr(brightway_api, "import_reed_db", lambda: None)

    with pytest.raises(RuntimeError) as exc_info:
        brightway_api.ensure_brightway_databases(settings)

    message = str(exc_info.value)
    assert "Brightway startup import failed" in message
    assert "BONSAI_TEST" in message
    assert str(settings.BONSAI_PATH) in message
    assert "bad tidy files" in message

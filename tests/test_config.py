from __future__ import annotations

from pathlib import Path

from reed.utils import Config


def test_reed_path_env_derives_bonsai_path(monkeypatch):
    reed_path = Path("test-artifacts") / "production-reed-root"
    monkeypatch.setenv("REED_PATH", str(reed_path))
    monkeypatch.delenv("BONSAI_PATH", raising=False)

    settings = Config()

    assert settings.REED_PATH == reed_path
    assert settings.BONSAI_PATH == reed_path / "data" / settings.BONSAI_NAME


def test_explicit_bonsai_path_env_wins(monkeypatch):
    reed_path = Path("test-artifacts") / "production-reed-root"
    bonsai_path = Path("test-artifacts") / "custom-bonsai"
    monkeypatch.setenv("REED_PATH", str(reed_path))
    monkeypatch.setenv("BONSAI_PATH", str(bonsai_path))

    settings = Config()

    assert settings.REED_PATH == reed_path
    assert settings.BONSAI_PATH == bonsai_path


def test_storage_root_env(monkeypatch):
    storage_root = Path("test-artifacts") / "service-storage"
    monkeypatch.setenv("STORAGE_ROOT", str(storage_root))

    settings = Config()

    assert settings.STORAGE_ROOT == storage_root

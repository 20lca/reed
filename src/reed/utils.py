from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_REED_PATH = (
    Path.home()
    / "OneDrive - 2.-0 LCA Consultants ApS"
    / "HorizonEurope"
    / "EU_REED_1277"
)


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", validate_assignment=True
    )

    lcia_gwp100: tuple = (
        "IPCC 2021",
        "climate change",
        "global warming potential (GWP100)",
    )
    # default path. It would work for windows machines with access to the
    # 2-0 LCA sharepoint.
    REED_PATH: Path = DEFAULT_REED_PATH

    BONSAI_PATH: Path = DEFAULT_REED_PATH / "data" / "BONSAI_V2.1.6"

    PROJECT_NAME: str = "reed"
    BONSAI_NAME: str = "BONSAI_V2.1.6"
    TOOL_DESCRIPTIONS_PATH: Path = Path(__file__).resolve().parent
    STORAGE_ROOT: Path = Path("storage")
    RESULT_TTL_HOURS: int = 24
    WORKER_POLL_INTERVAL_SECONDS: float = 0.2
    IMPORT_BRIGHTWAY_ON_STARTUP: bool = True

    @model_validator(mode="before")
    @classmethod
    def derive_bonsai_path(cls, values):
        if not isinstance(values, dict):
            return values
        if "BONSAI_PATH" in values:
            return values
        if "REED_PATH" not in values and "BONSAI_NAME" not in values:
            return values

        reed_path = Path(values.get("REED_PATH", DEFAULT_REED_PATH))
        bonsai_name = values.get("BONSAI_NAME", "BONSAI_V2.1.6")
        values["BONSAI_PATH"] = reed_path / "data" / bonsai_name
        return values


CONFIG = Config()
